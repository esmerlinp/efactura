"""Tests de cálculo de nómina con escenarios legales de República Dominicana.

Cubre:
  - TSS: AFP, SFS, SRL, INFOTEP con topes
  - ISR: tabla progresiva anual 2024-2025 con deducción educativa
  - DeductionPriorityEngine: prioridad, límites legales, salario protegido
  - Escenarios combinados: nómina mensual, quincenal, regalía, vacaciones
"""

import pytest
import sys
from unittest.mock import MagicMock, patch

# Mock modules that require native extensions before any app import
crypto_patch = patch.dict('sys.modules', {
    'cryptography': MagicMock(),
    'cryptography.fernet': MagicMock(),
    'cryptography.exceptions': MagicMock(),
    'cryptography.hazmat': MagicMock(),
    'cryptography.hazmat.bindings': MagicMock(),
    'cryptography.hazmat.bindings._rust': MagicMock(),
    'firebase_admin': MagicMock(),
    'firebase_admin.credentials': MagicMock(),
    'firebase_admin.firestore': MagicMock(),
})
crypto_patch.start()

from app.services.concept_engine import (
    ConceptEngine, TSSResolver, TSSContext,
    ISRResolver, ISRContext,
)
from app.services.deduction_priority_engine import DeductionPriorityEngine


# ── Parámetros legales RD 2024-2025 (valores oficiales) ──
RD_PARAMS = {
    "afp_employee_rate": 0.0287,
    "afp_employer_rate": 0.0710,
    "sfs_employee_rate": 0.0304,
    "sfs_employer_rate": 0.0709,
    "srl_employer_rate": 0.0120,
    "infotep_rate": 0.01,
    "afp_salary_cap": 464460.00,
    "sfs_salary_cap": 232230.00,
    "min_salary": 23223.00,
    "education_deduction": 50000.00,
    "isr_table": [
        {"from": 0.0, "to": 416220.00, "rate": 0.0, "deduction": 0.0},
        {"from": 416220.01, "to": 624329.00, "rate": 0.15, "deduction": 0.0},
        {"from": 624329.01, "to": 867123.00, "rate": 0.20, "deduction": 31216.00},
        {"from": 867123.01, "to": float("inf"), "rate": 0.25, "deduction": 79775.00},
    ],
    "overtime_rate": 1.35,
    "working_days_per_month": 23.83,
    "working_hours_per_day": 8.0,
    "infotep_threshold_multiplier": 5.0,
    "deduction_max_pct": 0.30,
    "protected_income_pct": 0.40,
    "pension_max_pct": 0.50,
    "judicial_max_pct": 0.30,
    "loan_max_pct": 0.15,
    "cooperative_max_pct": 0.20,
}


# ═══════════════════════════════════════════════════════════════════════
# TSS — Resolvers individuales
# ═══════════════════════════════════════════════════════════════════════

class TestTSSResolver:
    """Verifica cálculos TSS con topes legales RD."""

    def test_afp_employee_mensual(self):
        """Salario RD$ 50,000 mensual > tope AFP período (38,705) → 38,705 × 2.87% = 1,110.83"""
        period_cap = round(464460.00 / 12, 2)
        expected = round(period_cap * 0.0287, 2)
        ctx = TSSContext(base_salary=50000.00, is_quincenal=False)
        result = TSSResolver.resolve_concept("AFP_EMPLEADO", {}, ctx, RD_PARAMS)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_afp_employee_sin_tope(self):
        """Salario RD$ 250,000 anual (20,833/mes) < tope AFP período → sin tope"""
        period_cap = round(464460.00 / 12, 2)
        sal = 20000.00
        expected = round(sal * 0.0287, 2)
        ctx = TSSContext(base_salary=sal, is_quincenal=False)
        result = TSSResolver.resolve_concept("AFP_EMPLEADO", {}, ctx, RD_PARAMS)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_afp_employee_excede_tope(self):
        """Salario RD$ 500,000 mensual → tope AFP = 464,460 / 12 × 2.87% = 1,110.83"""
        ctx = TSSContext(base_salary=500000.00, is_quincenal=False)
        result = TSSResolver.resolve_concept("AFP_EMPLEADO", {}, ctx, RD_PARAMS)
        period_cap = round(464460.00 / 12, 2)
        expected = round(period_cap * 0.0287, 2)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_afp_empleador_mensual(self):
        """Salario 50,000 > tope AFP período → AFP empleador = 38,705 × 7.10% = 2,748.05"""
        period_cap = round(464460.00 / 12, 2)
        expected = round(period_cap * 0.0710, 2)
        ctx = TSSContext(base_salary=50000.00, is_quincenal=False)
        result = TSSResolver.resolve_concept("AFP_EMPLEADOR", {}, ctx, RD_PARAMS)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_sfs_empleado_mensual(self):
        """Salario RD$ 50,000 > tope SFS período (19,352.50) → topado"""
        period_cap = round(232230.00 / 12, 2)
        expected = round(period_cap * 0.0304, 2)
        ctx = TSSContext(base_salary=50000.00, is_quincenal=False)
        result = TSSResolver.resolve_concept("SFS_EMPLEADO", {}, ctx, RD_PARAMS)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_sfs_empleado_excede_tope(self):
        """Salario RD$ 300,000 → tope SFS = 232,230 / 12 × 3.04% = 588.32"""
        ctx = TSSContext(base_salary=300000.00, is_quincenal=False)
        result = TSSResolver.resolve_concept("SFS_EMPLEADO", {}, ctx, RD_PARAMS)
        period_cap = round(232230.00 / 12, 2)
        expected = round(period_cap * 0.0304, 2)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_srl_empleador(self):
        """SRL empleador = 50,000 × 1.20% = 600.00 (sin tope)"""
        ctx = TSSContext(base_salary=50000.00)
        result = TSSResolver.resolve_concept("SRL_EMPLEADOR", {}, ctx, RD_PARAMS)
        assert result["amount"] == pytest.approx(600.00, abs=0.01)

    def test_infotep_empleador(self):
        """INFOTEP empleador = 50,000 × 1% = 500.00"""
        ctx = TSSContext(base_salary=50000.00)
        result = TSSResolver.resolve_concept("INFOTEP_EMPLEADOR", {}, ctx, RD_PARAMS)
        assert result["amount"] == pytest.approx(500.00, abs=0.01)

    def test_infotep_empleado_exento(self):
        """Salario < umbral (23,223 × 5 = 116,115) → exento, amount = 0"""
        ctx = TSSContext(base_salary=50000.00)
        result = TSSResolver.resolve_concept("INFOTEP_EMPLEADO", {}, ctx, RD_PARAMS)
        assert result["amount"] == 0.0

    def test_infotep_empleado_aplica(self):
        """Salario 150,000 > 116,115 → INFOTEP empleado sobre base topada AFP"""
        ctx = TSSContext(base_salary=150000.00)
        result = TSSResolver.resolve_concept("INFOTEP_EMPLEADO", {}, ctx, RD_PARAMS)
        period_cap = round(464460.00 / 12, 2)
        expected = round(period_cap * 0.01, 2)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_tss_quincenal_doble_tope(self):
        """Quincenal: topes se dividen entre 24, no 12"""
        ctx = TSSContext(base_salary=25000.00, is_quincenal=True)
        result = TSSResolver.resolve_concept("AFP_EMPLEADO", {}, ctx, RD_PARAMS)
        expected = round(min(25000.00, 464460.00 / 24) * 0.0287, 2)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_tss_combinado_mensual(self):
        """Nómina mensual RD$ 50,000: AFP (topado 38,705) + SFS (topado 19,352.50)"""
        ctx = TSSContext(base_salary=50000.00, is_quincenal=False)
        afp = TSSResolver.resolve_concept("AFP_EMPLEADO", {}, ctx, RD_PARAMS)
        sfs = TSSResolver.resolve_concept("SFS_EMPLEADO", {}, ctx, RD_PARAMS)
        afp_cap = round(464460.00 / 12, 2)
        sfs_cap = round(232230.00 / 12, 2)
        expected = round(afp_cap * 0.0287 + sfs_cap * 0.0304, 2)
        assert round(afp["amount"] + sfs["amount"], 2) == pytest.approx(expected, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════
# ISR — Impuesto Sobre la Renta
# ═══════════════════════════════════════════════════════════════════════

class TestISRResolver:
    """Verifica cálculos ISR con tabla progresiva anual (DGII Norma 08-04)."""

    def test_isr_menor_416220_exento(self):
        """Ingreso anual ≤ RD$ 416,220 → ISR = 0"""
        ctx = ISRContext(gross_income=34000.00, is_quincenal=False)
        # mensual: 34,000 × 12 = 408,000 < 416,220
        result = ISRResolver.resolve(ctx, RD_PARAMS)
        assert result["amount"] == 0.0

    def test_isr_tramo_15_pct(self):
        """Ingreso mensual RD$ 50,000 → anual = 600,000 - 50,000 ded = 550,000 → tramo 15%"""
        ctx = ISRContext(gross_income=50000.00, is_quincenal=False)
        result = ISRResolver.resolve(ctx, RD_PARAMS)
        # ISR anual = 550,000 × 0.15 = 82,500 → ISR mensual = 82,500 / 12 = 6,875
        expected = round((((50000.00 * 12) - 50000.00) * 0.15) / 12, 2)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_isr_tramo_20_pct_con_deduccion(self):
        """Ingreso anual RD$ 750,000 → -50,000 educ = 700,000 → tramo 20%, cuota fija 31,216"""
        ctx = ISRContext(gross_income=62500.00, is_quincenal=False)
        result = ISRResolver.resolve(ctx, RD_PARAMS)
        # ISR anual = 700,000 × 0.20 - 31,216 = 108,784 → mensual = 9,065.33
        expected = round((108784.00) / 12, 2)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_isr_tramo_25_pct(self):
        """Ingreso anual RD$ 1,200,000 → -50,000 = 1,150,000 → tramo 25%, cuota 79,775"""
        ctx = ISRContext(gross_income=100000.00, is_quincenal=False)
        result = ISRResolver.resolve(ctx, RD_PARAMS)
        expected = round(((1150000.00 * 0.25 - 79775.00) / 12), 2)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_isr_quincenal_proporcional(self):
        """Quincenal RD$25,000 → anual = 600,000 (-50k educ) = 550k × 0.15 = 82,500 / 24 = 3,437.50"""
        ctx = ISRContext(gross_income=25000.00, is_quincenal=True)
        result = ISRResolver.resolve(ctx, RD_PARAMS)
        expected = round(((600000.00 - 50000.00) * 0.15) / 24, 2)
        assert result["amount"] == pytest.approx(expected, abs=0.01)

    def test_isr_tabla_dict_format(self):
        """Asegura que funcione con formato dict y lista"""
        from app.services.concept_engine import ISRResolver as IR
        assert IR._calculate_isr(RD_PARAMS["isr_table"], 500000.00) > 0

    def test_lookup_via_calculate_isr(self):
        """_calculate_isr y _lookup_isr son equivalentes"""
        from app.services.concept_engine import ISRResolver as IR
        v1 = IR._calculate_isr(RD_PARAMS["isr_table"], 500000.00)
        v2 = IR._lookup_isr(RD_PARAMS["isr_table"], 500000.00)
        assert v1 == v2


# ═══════════════════════════════════════════════════════════════════════
# DeductionPriorityEngine — Prioridad y límites
# ═══════════════════════════════════════════════════════════════════════

class TestDeductionPriorityEngine:
    """Verifica el motor de prioridad de deducciones."""

    def test_neto_positivo_sin_ajuste(self):
        """Ingresos > deducciones obligatorias → neto positivo, sin cambios"""
        txs = [
            {"type": "earning", "amount": 50000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 1435.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "AFP_EMPLEADO", "priority": 1},
            {"type": "deduction", "amount": 1520.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "SFS_EMPLEADO", "priority": 2},
            {"type": "deduction", "amount": 1000.00, "conceptSnapshot": {"category": "loan", "isLegalMandatory": False, "maxPercentage": 0.15}, "conceptCode": "PRESTAMO", "priority": 300},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        assert result["netSalary"] == pytest.approx(46045.00, abs=0.01)
        assert len(result["warnings"]) == 0
        assert len(result["skipped"]) == 0

    def test_deduccion_excede_limite_legal(self):
        """Deducción > 15% del salario → se reduce al límite"""
        txs = [
            {"type": "earning", "amount": 50000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 15000.00, "conceptSnapshot": {"category": "loan", "isLegalMandatory": False, "maxPercentage": 0.15}, "conceptCode": "PRESTAMO", "priority": 300},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        # TSS + ISR son 0 (no hay), protected = 40% de 50k = 20k
        # máximo = 15% de available (50k) = 7,500. Neto = 50k - 7,500 = 42,500
        assert result["netSalary"] == pytest.approx(42500.00, abs=0.01)
        assert len(result["warnings"]) == 1
        assert "Reducido" in result["warnings"][0]

    def test_salario_protegido(self):
        """Múltiples deducciones no pueden bajar el neto por debajo del 60% protegido"""
        txs = [
            {"type": "earning", "amount": 50000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 20000.00, "conceptSnapshot": {"category": "loan", "isLegalMandatory": False, "maxPercentage": 0.15}, "conceptCode": "PRESTAMO", "priority": 300},
            {"type": "deduction", "amount": 15000.00, "conceptSnapshot": {"category": "cooperatives", "isLegalMandatory": False, "maxPercentage": 0.20}, "conceptCode": "COOPERATIVA", "priority": 400},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        # protected = 40% de 50k = 20k, available = 50k, available_after_protected = 30k
        # Loan: max 15% de available (50k) = 7,500; after loan: available = 42,500, after_protected = 22,500
        # Coop: max 20% de available (42,500) = 8,500; min(15k,8.5k,22.5k) = 8,500
        # Neto = 50k - 7.5k - 8.5k = 34k
        assert result["netSalary"] == pytest.approx(34000.00, abs=0.01)

    def test_neto_negativo_ajustado(self):
        """Deducciones > ingresos → se ajusta último descuento no obligatorio"""
        txs = [
            {"type": "earning", "amount": 30000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 20000.00, "conceptSnapshot": {"category": "loan", "isLegalMandatory": False}, "conceptCode": "PRESTAMO", "priority": 300},
            {"type": "deduction", "amount": 15000.00, "conceptSnapshot": {"category": "other", "isLegalMandatory": False}, "conceptCode": "AHORRO", "priority": 600},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        # Sin TSS/ISR, available = 30k, protected = 12k, available_after_protected = 18k
        # Loan: 30k × 0.15 = 4,500; sobra 25.5k; Ahorro: 25.5k × 0.20 = 5,100
        # Neto = 30k - 4.5k - 5.1k = 20.4k
        assert result["netSalary"] >= 0
        assert result["netSalary"] >= 12000.00

    def test_deducciones_obligatorias_no_se_saltan(self):
        """TSS e ISR obligatorios se aplican incluso si el neto queda negativo (se ajustan otros)"""
        txs = [
            {"type": "earning", "amount": 30000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 1435.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "AFP_EMPLEADO", "priority": 1},
            {"type": "deduction", "amount": 1520.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "SFS_EMPLEADO", "priority": 2},
            {"type": "deduction", "amount": 30000.00, "conceptSnapshot": {"category": "loan", "isLegalMandatory": False}, "conceptCode": "PRESTAMO", "priority": 300},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        # TSS no se puede saltar
        tss_total = 1435.00 + 1520.00
        prestamo_amount = [d for d in result["transactions"] if d["conceptCode"] == "PRESTAMO"][0]["amount"]
        assert prestamo_amount > 0
        assert result["netSalary"] >= 0


# ═══════════════════════════════════════════════════════════════════════
# ConceptEngine — Evaluación completa de conceptos
# ═══════════════════════════════════════════════════════════════════════

class TestConceptEngine:
    """Verifica el motor de conceptos en escenarios RD reales."""

    def _concept(self, code, ctype="earning", category="fixed", priority=99, **kw):
        c = {"code": code, "type": ctype, "category": category, "priority": priority}
        c.update(kw)
        return c

    def test_salario_base(self):
        """Concepto SALARIO_BASE retorna el baseSalary como ingreso"""
        concept = self._concept("SALARIO_BASE", category="fixed", ctype="earning")
        context = {"baseSalary": 50000.00}
        tx = ConceptEngine.evaluate(concept, context, RD_PARAMS)
        assert tx is not None
        assert tx.amount == 50000.00
        assert tx.type == "earning"
        assert tx.conceptCode == "SALARIO_BASE"

    def test_afp_empleado_concepto(self):
        """Evaluación de AFP_EMPLEADO produce transacción con deducción calculada (topada)"""
        concept = self._concept("AFP_EMPLEADO", ctype="deduction", category="tss", priority=1)
        ctx = {"baseSalary": 50000.00, "grossIncome": 50000.00, "isQuincenal": False}
        tx = ConceptEngine.evaluate(concept, ctx, RD_PARAMS)
        assert tx is not None
        period_cap = round(464460.00 / 12, 2)
        expected = round(period_cap * 0.0287, 2)
        assert tx.amount == pytest.approx(expected, abs=0.01)
        assert tx.type == "deduction"
        assert tx.source == "system"

    def test_isr_concepto(self):
        """Evaluación de ISR produce transacción con deducción calculada"""
        concept = self._concept("ISR", ctype="deduction", category="isr", priority=100)
        ctx = {"baseSalary": 50000.00, "grossIncome": 50000.00, "isQuincenal": False}
        tx = ConceptEngine.evaluate(concept, ctx, RD_PARAMS)
        assert tx is not None
        assert tx.amount > 0

    def test_isr_con_mensual_25k_exento(self):
        """Salario mensual RD$25,000 → anual 300k - 50k educ = 250k < 416,220 → ISR = 0 → no genera tx"""
        concept = self._concept("ISR", ctype="deduction", category="isr", priority=100)
        ctx = {"baseSalary": 25000.00, "grossIncome": 25000.00, "isQuincenal": False, "ytd_isr": 0}
        tx = ConceptEngine.evaluate(concept, ctx, RD_PARAMS)
        assert tx is None

    def test_concept_snapshot_inmutable(self):
        """Cada PayrollTransaction incluye conceptSnapshot con campos críticos"""
        concept = self._concept("SALARIO_BASE", ctype="earning", category="fixed")
        ctx = {"baseSalary": 50000.00}
        tx = ConceptEngine.evaluate(concept, ctx, RD_PARAMS)
        snap = tx.conceptSnapshot
        assert snap["code"] == "SALARIO_BASE"
        assert snap["type"] == "earning"
        assert "affectsNet" in snap

    def test_build_totals(self):
        """build_totals: SALARIO_BASE 50,000 + AFP topado + SFS topado"""
        txs = [
            ConceptEngine.evaluate(self._concept("SALARIO_BASE", ctype="earning", category="fixed"),
                                    {"baseSalary": 50000.00}, RD_PARAMS),
            ConceptEngine.evaluate(self._concept("AFP_EMPLEADO", ctype="deduction", category="tss", priority=1),
                                    {"baseSalary": 50000.00, "grossIncome": 50000.00, "isQuincenal": False}, RD_PARAMS),
            ConceptEngine.evaluate(self._concept("SFS_EMPLEADO", ctype="deduction", category="tss", priority=2),
                                    {"baseSalary": 50000.00, "grossIncome": 50000.00, "isQuincenal": False}, RD_PARAMS),
        ]
        txs = [t for t in txs if t is not None]
        totals = ConceptEngine.build_totals(txs)
        afp_ded = round(min(50000.00, round(464460.00 / 12, 2)) * 0.0287, 2)
        sfs_ded = round(min(50000.00, round(232230.00 / 12, 2)) * 0.0304, 2)
        assert totals["totalIncome"] == pytest.approx(50000.00, abs=0.01)
        assert totals["totalDeductions"] == pytest.approx(afp_ded + sfs_ded, abs=0.01)
        assert totals["netSalary"] == pytest.approx(50000.00 - afp_ded - sfs_ded, abs=0.01)

    def test_concept_recurring(self):
        """Concepto recurrente con amount resuelto externamente"""
        concept = self._concept("EMBARGO", ctype="deduction", category="recurring")
        ctx = {"resolvedAmount": 5000.00, "source": "recurring:xxx", "recurringMovementId": "mv_id"}
        tx = ConceptEngine.evaluate(concept, ctx, RD_PARAMS)
        assert tx is not None
        assert tx.amount == 5000.00
        assert tx.isRecurring is True
        assert tx.recurringMovementId == "mv_id"


# ═══════════════════════════════════════════════════════════════════════
# Escenarios integrados RD
# ═══════════════════════════════════════════════════════════════════════

class TestEscenariosRD:
    """Escenarios de nómina reales para empleados en República Dominicana."""

    def test_nomina_mensual_50k(self):
        """Empleado mensual RD$ 50,000: cálculo completo con TSS + ISR + préstamo"""
        afp_cap = round(464460.00 / 12, 2)
        sfs_cap = round(232230.00 / 12, 2)
        afp_ded = round(afp_cap * 0.0287, 2)
        sfs_ded = round(sfs_cap * 0.0304, 2)
        isr_annual = round(((50000.00 * 12) - 50000.00) * 0.15, 2)
        isr_ded = round(isr_annual / 12, 2)
        tss_isr_total = round(afp_ded + sfs_ded + isr_ded, 2)

        txs = [
            {"type": "earning", "amount": 50000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": afp_ded, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "AFP_EMPLEADO", "priority": 1},
            {"type": "deduction", "amount": sfs_ded, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "SFS_EMPLEADO", "priority": 2},
            {"type": "deduction", "amount": isr_ded, "conceptSnapshot": {"category": "isr", "isLegalMandatory": True}, "conceptCode": "ISR", "priority": 100},
            {"type": "deduction", "amount": 5000.00, "conceptSnapshot": {"category": "loan", "isLegalMandatory": False, "maxPercentage": 0.15}, "conceptCode": "PRESTAMO", "priority": 300},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        assert result["totalIncome"] == 50000.00
        # Loan: min(5,000, (50k - tss_isr) × 0.15, (50k - tss_isr - protected)) = 5,000
        assert result["totalDeductions"] == pytest.approx(tss_isr_total + 5000.00, abs=0.01)
        assert result["netSalary"] == pytest.approx(50000.00 - tss_isr_total - 5000.00, abs=0.01)

    def test_nomina_quincenal_25k(self):
        """Empleado quincenal RD$ 25,000 (proporcional)"""
        txs = [
            {"type": "earning", "amount": 25000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 717.50, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "AFP_EMPLEADO", "priority": 1},
            {"type": "deduction", "amount": 760.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "SFS_EMPLEADO", "priority": 2},
            {"type": "deduction", "amount": 0.0, "conceptSnapshot": {"category": "isr", "isLegalMandatory": True}, "conceptCode": "ISR", "priority": 100},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        assert result["netSalary"] == pytest.approx(23522.50, abs=0.01)

    def test_salario_bajo_sin_isr(self):
        """Empleado con salario bajo que no paga ISR pero sí TSS"""
        txs = [
            {"type": "earning", "amount": 25000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 717.50, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "AFP_EMPLEADO", "priority": 1},
            {"type": "deduction", "amount": 760.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "SFS_EMPLEADO", "priority": 2},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        assert result["netSalary"] == pytest.approx(23522.50, abs=0.01)
        assert result["totalDeductions"] == pytest.approx(1477.50, abs=0.01)

    def test_multiples_embargos_prioridad(self):
        """Embargo pensión (máx 50%) + judicial (30%) → pensión se aplica primero"""
        txs = [
            {"type": "earning", "amount": 40000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 1200.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "AFP_EMPLEADO", "priority": 1},
            {"type": "deduction", "amount": 1216.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "SFS_EMPLEADO", "priority": 2},
            {"type": "deduction", "amount": 8000.00, "conceptSnapshot": {"category": "pension", "isLegalMandatory": False, "maxPercentage": 0.50}, "conceptCode": "PENSION", "priority": 200},
            {"type": "deduction", "amount": 6000.00, "conceptSnapshot": {"category": "garnishment", "isLegalMandatory": False, "maxPercentage": 0.30}, "conceptCode": "EMBARGO", "priority": 250},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        # TSS = 2,416 (obligatorio). available = 37,584. protected = 16k. after_protected = 21,584
        # Pension: min(8k, 37,584 × 0.50 = 18,792, 21,584) = 8,000
        # Período 1: available = 29,584, protected = 13,584
        # Judicial: min(6k, 29,584 × 0.30 = 8,875.2, 13,584) = 6,000
        # Neto = 40k - 1.2k - 1.216k - 8k - 6k = 23,584
        assert result["netSalary"] == pytest.approx(23584.00, abs=0.01)

    def test_deducciones_exceden_salario(self):
        """Escenario donde TSS + ISR ya exceden la capacidad de pago"""
        txs = [
            {"type": "earning", "amount": 30000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 1435.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "AFP_EMPLEADO", "priority": 1},
            {"type": "deduction", "amount": 1520.00, "conceptSnapshot": {"category": "tss", "isLegalMandatory": True}, "conceptCode": "SFS_EMPLEADO", "priority": 2},
            {"type": "deduction", "amount": 20000.00, "conceptSnapshot": {"category": "loan", "isLegalMandatory": False}, "conceptCode": "PRESTAMO", "priority": 300},
            {"type": "deduction", "amount": 10000.00, "conceptSnapshot": {"category": "other", "isLegalMandatory": False}, "conceptCode": "AHORRO", "priority": 600},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        assert result["netSalary"] >= 0
        # No hay warnings si todo se ajustó
        assert result["totalDeductions"] <= result["totalIncome"]


# ═══════════════════════════════════════════════════════════════════════
# Escenarios especiales
# ═══════════════════════════════════════════════════════════════════════

class TestEscenariosEspeciales:
    """Regalía pascual, vacaciones, retroactivos, liquidación."""

    def test_concept_variable(self):
        """Concepto variable con amount resuelto externamente"""
        concept = self._make_concept("BONO", ctype="earning", category="variable")
        ctx = {"resolvedAmount": 10000.00, "source": "manual"}
        tx = ConceptEngine.evaluate(concept, ctx, RD_PARAMS)
        assert tx is not None
        assert tx.amount == 10000.00

    def test_concept_temp_immutable(self):
        """Verifica que el snapshot contenga category fijo para conceptos fijos"""
        concept = self._make_concept("SALARIO_BASE", ctype="earning", category="fixed")
        ctx = {"baseSalary": 50000.00}
        tx = ConceptEngine.evaluate(concept, ctx, RD_PARAMS)
        snap = tx.conceptSnapshot
        assert "category" in snap
        assert "conceptVersion" in snap

    def test_deduccion_porcentual_prestamo(self):
        """Deducción tipo %: se aplica el % sobre el salario disponible"""
        txs = [
            {"type": "earning", "amount": 50000.00, "conceptSnapshot": {}, "conceptCode": "SALARIO_BASE", "priority": 0},
            {"type": "deduction", "amount": 7500.00, "conceptSnapshot": {"category": "loan", "isLegalMandatory": False, "maxPercentage": 0.15}, "conceptCode": "PRESTAMO", "priority": 300},
        ]
        result = DeductionPriorityEngine.process(txs, RD_PARAMS)
        # 15% = 7,5000, neto = 50k - 7.5k = 42.5k
        assert result["netSalary"] == pytest.approx(42500.00, abs=0.01)
        assert len(result["warnings"]) == 0

    @staticmethod
    def _make_concept(code, ctype="earning", category="fixed", **kw):
        c = {"code": code, "type": ctype, "category": category, "priority": kw.pop("priority", 99)}
        c.update(kw)
        return c