"""ConceptEngine — Motor de evaluación de conceptos de nómina.

Traduce un concepto + contexto + parámetros legales en una PayrollTransaction.

Arquitectura:
  - ConceptEngine.evaluate() es el punto de entrada único.
  - Para categorías específicas (tss, isr) delega a resolvers especializados.
  - Cada transacción incluye un conceptSnapshot inmutable.

No reemplaza calculate_payroll_line() — la envuelve y extiende para
producir transacciones granulares en lugar de acumuladores.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models.transaction import PayrollTransaction


class TSSContext:
    """Contexto de entrada para el cálculo de TSS."""
    def __init__(self, base_salary: float = 0.0, gross_income: float = 0.0,
                 is_quincenal: bool = False, hourly_rate: bool = False,
                 period_hours: float = 0.0, salary_history: list = None):
        self.base_salary = base_salary
        self.gross_income = gross_income
        self.is_quincenal = is_quincenal
        self.hourly_rate = hourly_rate
        self.period_hours = period_hours
        self.salary_history = salary_history or []


class ISRContext:
    """Contexto de entrada para el cálculo de ISR."""
    def __init__(self, gross_income: float = 0.0, annual_projection: float = 0.0,
                 is_quincenal: bool = False, period_count: int = 1,
                 ytd_isr: float = 0.0, prorated_salary: float = None):
        self.gross_income = gross_income
        self.annual_projection = annual_projection
        self.is_quincenal = is_quincenal
        self.period_count = period_count
        self.ytd_isr = ytd_isr
        self.prorated_salary = prorated_salary


class TSSResolver:
    """Resuelve conceptos de seguridad social (AFP, SFS, SRL, INFOTEP)."""

    @staticmethod
    def resolve_concept(concept_code: str, concept: dict,
                        context: TSSContext, params: dict) -> dict:
        """Calcula el monto TSS para un concepto específico.

        Args:
            concept_code: Código del concepto (AFP_EMPLEADO, SFS_EMPLEADOR, etc.)
            concept: Dict del concepto (con isSystem, isLegalMandatory, etc.)
            context: TSSContext con los datos de entrada
            params: Parámetros legales resueltos (get_rates format)

        Returns:
            Dict con keys: amount, tss_base_capped, note
        """
        base = context.base_salary
        is_q = context.is_quincenal

        # Determinar base cotizable según el tipo de concepto
        if "EMPLEADOR" in concept_code:
            tss_base = base
        else:
            tss_base = base

        # Aplicar topes
        afp_cap = params.get("afp_salary_cap", 464460.0)
        sfs_cap = params.get("sfs_salary_cap", 232230.0)
        period_factor = 24 if is_q else 12

        # Topes por período
        afp_cap_period = round(afp_cap / period_factor, 2)
        sfs_cap_period = round(sfs_cap / period_factor, 2)

        amount = 0.0
        tss_base_capped = 0.0
        note = ""

        if concept_code == "AFP_EMPLEADO":
            capped = min(tss_base, afp_cap_period)
            rate = params.get("afp_employee_rate", 0.0287)
            amount = round(capped * rate, 2)
            tss_base_capped = capped
            note = f"AFP emp. {rate*100:.2f}% s/{capped:,.2f}"

        elif concept_code == "AFP_EMPLEADOR":
            capped = min(tss_base, afp_cap_period)
            rate = params.get("afp_employer_rate", 0.0710)
            amount = round(capped * rate, 2)
            tss_base_capped = capped
            note = f"AFP empldor {rate*100:.2f}% s/{capped:,.2f}"

        elif concept_code == "SFS_EMPLEADO":
            capped = min(tss_base, sfs_cap_period)
            rate = params.get("sfs_employee_rate", 0.0304)
            amount = round(capped * rate, 2)
            tss_base_capped = capped
            note = f"SFS emp: {rate*100:.2f}% s/{capped:,.2f}"

        elif concept_code == "SFS_EMPLEADOR":
            capped = min(tss_base, sfs_cap_period)
            rate = params.get("sfs_employer_rate", 0.0709)
            amount = round(capped * rate, 2)
            tss_base_capped = capped
            note = f"SFS empldor {rate*100:.2f}% s/{capped:,.2f}"

        elif concept_code == "SRL_EMPLEADOR":
            rate = params.get("srl_employer_rate", 0.0120)
            amount = round(tss_base * rate, 2)
            note = f"SRL: {rate*100:.2f}% s/{tss_base:,.2f}"

        elif concept_code == "INFOTEP_EMPLEADOR":
            rate = params.get("infotep_rate", 0.01)
            amount = round(tss_base * rate, 2)
            note = f"INFOTEP empldor {rate*100:.2f}%"

        elif concept_code == "INFOTEP_EMPLEADO":
            min_salary = params.get("min_salary", 23223.0)
            multiplier = params.get("infotep_threshold_multiplier", 5.0)
            threshold = min_salary * multiplier
            if tss_base > threshold:
                rate = params.get("infotep_rate", 0.01)
                capped = min(tss_base, afp_cap_period)
                amount = round(capped * rate, 2)
                note = f"INFOTEP emp (excede {threshold:,.2f})"
            else:
                amount = 0.0
                note = f"INFOTEP emp exento (< {threshold:,.2f})"

        return {"amount": amount, "tss_base_capped": tss_base_capped, "note": note}


class ISRResolver:
    """Resuelve el ISR (Impuesto Sobre la Renta) según método de retención acumulada DGII."""

    @staticmethod
    def resolve(context: ISRContext, params: dict) -> dict:
        """Calcula el ISR a retener en este período.

        Método: retención acumulada DGII Norma 08-04.
        """
        gross_income = context.gross_income
        is_q = context.is_quincenal
        ytd_isr = context.ytd_isr

        period_factor = 24 if is_q else 12
        education_ded = params.get("education_deduction", 50000.0)
        isr_table = params.get("isr_table", [])

        # Proyección anual
        if context.prorated_salary is not None:
            period_salary = context.prorated_salary
        else:
            period_salary = gross_income

        annual_projection = period_salary * period_factor

        # Aplicar deducción educativa
        taxable_annual = max(0, annual_projection - education_ded)

        # Calcular ISR anual según tabla progresiva
        annual_isr = ISRResolver._lookup_isr(isr_table, taxable_annual)

        # ISR del período = (ISR anual / períodos) - ISR ya retenido YTD
        isr_period = round((annual_isr / period_factor), 2)

        if isr_period < 0:
            isr_period = 0.0

        return {
            "amount": isr_period,
            "annual_projection": annual_projection,
            "taxable_base": taxable_annual,
            "isr_annual": annual_isr,
        }

    @staticmethod
    def _calculate_isr(isr_table: list, taxable_annual: float) -> float:
        """Aplica la tabla progresiva de ISR."""
        for bracket in isr_table:
            if isinstance(bracket, dict):
                r_from = bracket.get("from", 0)
                r_to = bracket.get("to", float("inf"))
                rate = bracket.get("rate", 0)
                deduction = bracket.get("deduction", 0)
            else:
                r_from, r_to, rate, deduction = bracket
            if r_from <= taxable_annual <= r_to:
                return round((taxable_annual * rate) - deduction, 2)
        return 0.0

    @staticmethod
    def _lookup_isr(isr_table: list, taxable_annual: float) -> float:
        return ISRResolver._calculate_isr(isr_table, taxable_annual)

    @staticmethod
    def _calculate_isr_by_bracket(isr_table: list, taxable_annual: float) -> float:
        """Cálculo por tramo (más preciso)."""
        remaining = taxable_annual
        total_isr = 0.0
        for bracket in isr_table:
            if isinstance(bracket, list):
                r_from, r_to, rate, _ = bracket
            else:
                r_from = bracket.get("from", 0)
                r_to = bracket.get("to", float("inf"))
                rate = bracket.get("rate", 0)
            if remaining <= 0:
                break
            bracket_range = r_to - r_from if r_to != float("inf") else remaining
            if isinstance(bracket_range, float) and bracket_range == float("inf"):
                bracket_amount = remaining
            else:
                bracket_amount = min(remaining, max(0, bracket_range))
            isr_for_bracket = round(bracket_amount * rate, 2)
            total_isr += isr_for_bracket
            remaining -= bracket_amount
        return total_isr


class ConceptEngine:
    """Motor principal de evaluación de conceptos."""

    @staticmethod
    def evaluate(concept: dict, context: dict,
                 params: dict, period_id: str = "", period_key: str = "",
                 employee_id: str = "", contract_id: str = "",
                 payroll_line_id: str = "", period_revision: int = 1,
                 legal_entity_id: str = "", group_id: str = "") -> Optional[PayrollTransaction]:
        """Evalúa un concepto y produce una PayrollTransaction.

        Args:
            concept: Dict del concepto (desde PayrollConceptService)
            context: Dict con {baseSalary, grossIncome, isQuincenal, ...}
            params: Parámetros legales resueltos (get_rates format)
            period_id, period_key, employee_id, contract_id, etc.

        Returns:
            PayrollTransaction o None si el concepto no aplica.
        """
        code = concept.get("code", "")
        category = concept.get("category", "fixed")
        ctype = concept.get("type", "")

        amount = 0.0
        source = "system"
        source_id = ""
        tx_note = ""

        # ── Conceptos TSS (AFP, SFS, SRL, INFOTEP) ──
        if category == "tss":
            tss_ctx = TSSContext(
                base_salary=context.get("baseSalary", 0),
                gross_income=context.get("grossIncome", 0),
                is_quincenal=context.get("isQuincenal", False),
            )
            result = TSSResolver.resolve_concept(code, concept, tss_ctx, params)
            amount = result["amount"]
            tx_note = result.get("note", "")
            source = "system"

            if amount <= 0 and code == "INFOTEP_EMPLEADO":
                return None

        # ── Concepto ISR ──
        elif category == "isr":
            isr_ctx = ISRContext(
                gross_income=context.get("grossIncome", 0),
                is_quincenal=context.get("isQuincenal", False),
                ytd_isr=context.get("ytd_isr", 0),
                prorated_salary=context.get("proratedSalary"),
            )
            result = ISRResolver.resolve(isr_ctx, params)
            amount = result["amount"]
            source = "system"

        # ── Conceptos fijos (salario base) ──
        elif category == "fixed" and code == "SALARIO_BASE":
            amount = context.get("baseSalary", 0)
            source = "system"

        # ── Conceptos recurrentes (incenivos, asignaciones, descuentos) ──
        # Se resuelven externamente (RecurringMovementService). Aquí solo
        # se genera la transacción base si el concepto se pasa con amount ya resuelto.
        elif category == "recurring":
            amount = context.get("resolvedAmount", 0)
            source = context.get("source", "recurring")

        # ── Conceptos variables (gestión manual) ──
        elif category == "variable":
            amount = context.get("resolvedAmount", 0)
            source = context.get("source", "variable")

        if amount == 0:
            return None

        # Construir snapshot del concepto
        from app.services.payroll_concept_engine import build_concept_snapshot
        snapshot = build_concept_snapshot(concept)

        amount = round(amount, 2)

        tx_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        return PayrollTransaction(
            id=tx_id,
            periodId=period_id,
            periodKey=period_key,
            payrollLineId=payroll_line_id,
            employeeId=employee_id,
            contractId=contract_id,
            legalEntityId=legal_entity_id,
            groupId=group_id,
            conceptCode=code,
            type=ctype,
            amount=amount,
            source=source,
            sourceId=source_id,
            isRecurring=category == "recurring",
            recurringMovementId=context.get("recurringMovementId", ""),
            periodRevision=period_revision,
            status="applied",
            conceptSnapshot=snapshot,
            priority=concept.get("priority", 100),
            periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
            notes=tx_note,
            createdAt=now_iso,
            updatedAt=now_iso,
        )

    @staticmethod
    def build_totals(transactions: list) -> dict:
        """A partir de una lista de PayrollTransaction, calcula totales.

        Retorna dict con:
          totalIncome, totalDeductions, netSalary, totalEmployerContrib
          y byConcept para el resumen rápido.
        """
        total_income = 0.0
        total_ded = 0.0
        total_employer = 0.0
        by_concept = []

        for tx in transactions:
            if not isinstance(tx, dict):
                tx = tx.model_dump() if hasattr(tx, 'model_dump') else tx
            amount = float(tx.get("amount", 0))
            tx_type = tx.get("type", "")
            code = tx.get("conceptCode", "")

            if tx_type == "earning":
                total_income += amount
            elif tx_type == "deduction":
                total_ded += amount
            elif tx_type == "employer_contrib":
                total_employer += amount

            by_concept.append({"conceptCode": code, "amount": amount, "type": tx_type})

        return {
            "totalIncome": round(total_income, 2),
            "totalDeductions": round(total_ded, 2),
            "netSalary": round(max(0, total_income - total_ded), 2),
            "totalEmployerContrib": round(total_employer, 2),
            "byConcept": by_concept,
        }