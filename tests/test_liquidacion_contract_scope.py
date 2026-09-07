"""Aislamiento contractual de salario promedio, liquidación y pagos.

Verifica que una reincorporación no mezcle salarios entre períodos y que el
pago de liquidación sea idempotente.
"""
import pytest

from app.services.liquidacion_service import LiquidacionService


def _tx(tid, period_key, amount, contract_id="", status="applied"):
    return {"id": tid, "periodId": "p-" + period_key, "periodKey": period_key,
            "employeeId": "emp_125", "contractId": contract_id,
            "conceptCode": "SALARIO_BASE", "type": "earning", "amount": amount,
            "source": "payroll", "sourceId": "", "status": status,
            "conceptSnapshot": {"affectsTSS": True}}


def _mixed_transactions():
    txs = []
    for m in range(1, 13):
        txs.append(_tx(f"old-{m:02d}", f"2023-{m:02d}-M", 50000.0, "ctr_001"))
    for m in (9, 10):
        txs.append(_tx(f"new-{m:02d}", f"2026-{m:02d}-M", 65000.0, "ctr_002"))
    return txs


class TestAverageContractScope:
    def test_new_contract_ignores_old_period(self):
        prom = LiquidacionService.calcular_salario_promedio_mensual(
            _mixed_transactions(), contract_id="ctr_002",
            start_date="2026-09-15", end_date="")
        assert prom["promedio_mensual"] == 65000.0

    def test_old_contract_ignores_new_period(self):
        prom = LiquidacionService.calcular_salario_promedio_mensual(
            _mixed_transactions(), contract_id="ctr_001",
            start_date="2022-01-10", end_date="2024-06-30")
        assert prom["promedio_mensual"] == 50000.0

    def test_legacy_without_scope_keeps_behavior(self):
        # Ventana de últimos 12 meses por mes calendario (10×50000 + 2×65000).
        # Este caso documenta la mezcla que el aislamiento corrige.
        prom = LiquidacionService.calcular_salario_promedio_mensual(
            _mixed_transactions())
        assert prom["promedio_mensual"] == 52500.0

    def test_legacy_date_fallback_excludes_previous_relation(self):
        txs = [_tx("old", "2024-05-M", 50000.0, ""),
               _tx("new", "2026-09-M", 65000.0, "")]
        prom = LiquidacionService.calcular_salario_promedio_mensual(
            txs, start_date="2026-09-15", end_date="")
        assert prom["promedio_mensual"] == 65000.0


class TestLiquidacionSnapshot:
    def _ctx(self):
        return {
            "employeeId": "emp_125", "contractId": "ctr_002", "isLegacy": False,
            "periodNumber": 2, "origin": "rehire", "previousContractId": "ctr_001",
            "startDate": "2026-09-15", "endDate": "",
            "salary": 65000.0, "position": "Analista Senior",
            "seniorityPolicy": "reset", "seniorityBaseDate": "2026-09-15",
            "vacationPolicy": "reset", "vacationBaseDate": "2026-09-15",
            "contract": {"id": "ctr_002", "employeeId": "emp_125", "periodNumber": 2,
                         "salary": 65000.0, "startDate": "2026-09-15"},
        }

    def test_snapshot_embedded(self):
        txs = [_tx("new-09", "2026-09-M", 65000.0, "ctr_002")]
        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp_125", hire_date="2026-09-15",
            termination_date="2026-12-31", termination_type="renuncia",
            last_base_salary=65000.0, contract_id="ctr_002",
            employment_context=self._ctx(), salary_transactions_used=txs)
        assert r["contractId"] == "ctr_002"
        assert r["contractPeriodNumber"] == 2
        assert r["employmentStartDate"] == "2026-09-15"
        assert r["seniorityBaseDate"] == "2026-09-15"
        assert r["salaryTransactionsUsed"] == ["new-09"]
        assert r["calculationVersion"] == 1
        assert r["contractSnapshot"]["id"] == "ctr_002"

    def test_legacy_output_defaults(self):
        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp_125", hire_date="2022-01-10",
            termination_date="2024-06-30", last_base_salary=50000.0)
        assert r["contractId"] == ""
        assert r["contractPeriodNumber"] == 0
        assert r["salaryTransactionsUsed"] == []
        assert r["calculationVersion"] == 1


class TestPaymentIdempotency:
    def test_already_paid_raises(self):
        from app.services.offboarding_service import check_payment_idempotency
        with pytest.raises(ValueError, match="ya está pagada"):
            check_payment_idempotency(
                {"id": "s1", "status": "pagada", "version": 1}, [])

    def test_duplicate_payment_same_version_raises(self):
        from app.services.offboarding_service import check_payment_idempotency
        with pytest.raises(ValueError, match="Ya existe un pago"):
            check_payment_idempotency(
                {"id": "s1", "requestId": "r1", "status": "borrador", "version": 2},
                [{"settlementId": "s1", "settlementVersion": 2}])

    def test_legacy_payment_without_settlement_id_does_not_block(self):
        # El flujo de nómina registra primero un pago de método y luego el
        # pago contra período: no debe bloquearse entre sí.
        from app.services.offboarding_service import check_payment_idempotency
        check_payment_idempotency(
            {"id": "s1", "requestId": "r1", "status": "borrador", "version": 1},
            [{"requestId": "r1", "settlementVersion": 1}])

    def test_first_payment_allowed(self):
        from app.services.offboarding_service import check_payment_idempotency
        check_payment_idempotency(
            {"id": "s1", "requestId": "r1", "status": "pendiente_pago", "version": 1},
            [])
