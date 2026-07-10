"""DeductionPriorityEngine — Motor de prioridad y límites de descuentos.

Ordena los descuentos según prioridad legal y empresarial, aplica límites
configurables, y asegura que el salario neto no quede por debajo de
un mínimo protegido.

Orden de prioridad (configurable por parámetro legal):
  1-99  : TSS obligatorios (AFP, SFS) — no se pueden saltar
  100   : ISR — obligatorio
  200-299: Embargos judiciales (pensión alimenticia > judicial)
  300-399: Préstamos empresa
  400-499: Cooperativas
  500-599: Seguros
  600+  : Ahorro voluntario y otros descuentos
"""

from typing import Tuple, List


class DeductionPriorityEngine:

    # Categorías de prioridad (por defecto)
    PRIORITY_BANDS = {
        "tss":           (1, 99),
        "isr":           (100, 199),
        "garnishment":   (200, 299),
        "loan":          (300, 399),
        "cooperative":   (400, 499),
        "insurance":     (500, 599),
        "savings":       (600, 699),
        "other":         (700, 999),
    }

    @classmethod
    def process(cls, transactions: list, params: dict) -> dict:
        """Procesa una lista de transacciones y aplica prioridad/límites.

        Args:
            transactions: Lista de dicts de PayrollTransaction
            params: Parámetros legales (get_rates format) con límites

        Returns:
            Dict con:
              - transactions: transacciones procesadas (amounts ajustados)
              - skipped: transacciones que no se pudieron aplicar
              - warnings: lista de advertencias
              - totalIncome, totalDeductions, netSalary, totalEmployer
        """
        total_income = 0.0
        total_employer = 0.0
        tss_deductions = []
        isr_deductions = []
        other_deductions = []
        skipped = []
        warnings = []
        protected_pct = params.get("protected_income_pct", 0.40)

        # Clasificar transacciones
        for tx in transactions:
            if not isinstance(tx, dict):
                try:
                    tx = tx.model_dump()
                except AttributeError:
                    continue

            tx_type = tx.get("type", "")
            amount = float(tx.get("amount", 0))

            if amount <= 0:
                continue

            if tx_type == "earning":
                total_income += amount
            elif tx_type == "employer_contrib":
                total_employer += amount
            elif tx_type == "deduction":
                category = tx.get("conceptSnapshot", {}).get("category", "other")
                is_mandatory = tx.get("conceptSnapshot", {}).get("isLegalMandatory", False)

                if is_mandatory and category in ("tss", "isr"):
                    if category == "tss":
                        tss_deductions.append(tx)
                    else:
                        isr_deductions.append(tx)
                else:
                    other_deductions.append(tx)

        # Aplicar TSS obligatorios primero (no se pueden exceder)
        tss_total = sum(float(d.get("amount", 0)) for d in tss_deductions)
        isr_total = sum(float(d.get("amount", 0)) for d in isr_deductions)

        available = total_income - tss_total - isr_total

        # Calcular monto protegido
        protected = max(0, total_income * protected_pct)
        available_after_protected = max(0, available - protected)

        # Ordenar otros descuentos por prioridad
        other_deductions.sort(key=lambda d: (
            d.get("priority", 999),
            d.get("conceptCode", ""),
        ))

        # Aplicar otros descuentos con límites
        for ded in other_deductions:
            code = ded.get("conceptCode", "")
            amount = float(ded.get("amount", 0))
            priority = ded.get("priority", 999)
            snapshot = ded.get("conceptSnapshot", {})
            max_pct = snapshot.get("maxPercentage", 0.0)

            # Determinar el límite máximo según tipo de descuento
            max_rate = max_pct
            if max_rate <= 0:
                # Usar parámetros legales según categoría
                category = snapshot.get("category", "other")
                cat = category or "other"
                max_rate = cls._get_max_rate(cat, params)

            # Límite: porcentaje del salario disponible o del salario total
            max_for_this = max(0, available * max_rate) if max_rate > 0 else available
            # También limitar por el monto protegido
            max_applicable = min(amount, max_for_this, available_after_protected)

            if max_applicable <= 0:
                warnings.append(f"{code}: No hay salario disponible. Se omite.")
                ded["amount"] = 0.0
                skipped.append(ded)
                continue

            if max_applicable < amount:
                warnings.append(f"{code}: Reducido de RD$ {amount:,.2f} a RD$ {max_applicable:,.2f} por límite legal.")
                ded["amount"] = max_applicable

            available -= max_applicable
            available_after_protected = max(0, available_after_protected - max_applicable)

        # Recalcular totales
        all_applied = tss_deductions + isr_deductions + other_deductions
        final_net = total_income - sum(float(d.get("amount", 0)) for d in all_applied)

        # Asegurar neto no negativo
        if final_net < 0:
            warnings.append(f"Salario neto sería negativo (RD$ {final_net:,.2f}). Se ajustan descuentos.")
            # Ajustar último descuento para que neto sea 0
            excess = abs(final_net)
            for ded in reversed(all_applied):
                if ded.get("isLegalMandatory"):
                    continue
                ded_amount = float(ded.get("amount", 0))
                if ded_amount >= excess:
                    ded["amount"] = round(ded_amount - excess, 2)
                    break
                else:
                    excess -= ded_amount
                    ded["amount"] = 0.0

        final_net = max(0, total_income - sum(float(d.get("amount", 0)) for d in all_applied))

        return {
            "transactions": all_applied,
            "skipped": skipped,
            "warnings": warnings,
            "totalIncome": round(total_income, 2),
            "totalDeductions": round(sum(float(d.get("amount", 0)) for d in all_applied), 2),
            "netSalary": round(final_net, 2),
            "totalEmployer": round(total_employer, 2),
        }

    @classmethod
    def _get_max_rate(cls, category: str, params: dict) -> float:
        """Obtiene la tasa máxima legal para una categoría de descuento."""
        rates = {
            "pension":       params.get("pension_max_pct", 0.50),
            "garnishment":   params.get("judicial_max_pct", 0.30),
            "loan":          params.get("loan_max_pct", 0.15),
            "cooperatives":   params.get("cooperative_max_pct", 0.20),
            "insurance":     params.get("deduction_max_pct", 0.20),
            "savings":       params.get("deduction_max_pct", 0.15),
            "other":         params.get("deduction_max_pct", 0.20),
        }
        return rates.get(category, params.get("deduction_max_pct", 0.20))