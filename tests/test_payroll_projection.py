"""Tests para la proyección de prestaciones laborales con salario promedio y descuentos."""

import pytest
from unittest.mock import patch

from app.services.payroll_projection_service import PayrollProjectionService


def _emp(eid, base=45000, hire="2023-01-01"):
    return {"id": eid, "fullName": f"Emp {eid}", "cedula": "00112345678",
            "baseSalary": base, "status": "activo", "hireDate": hire,
            "department": "Admin", "paymentFrequency": "mensual"}


def _tx(code, monto, period_key, affects_tss=True, type="earning", status="applied"):
    return {"conceptCode": code, "amount": monto, "periodKey": period_key,
            "type": type, "status": status, "conceptSnapshot": {"affectsTSS": affects_tss}}


class TestProjectBenefits:
    def test_salario_promedio_descuentos_y_neto(self):
        emp = _emp("E1")
        txs = {"E1": [_tx("SALARIO_BASE", 45000, "2026-01"),
                      _tx("COMISION", 5000, "2026-01")]}
        recurring = [{"id": "m1", "employeeId": "E1", "status": "active", "isLoan": True,
                      "remainingBalance": 10000, "conceptCode": "PRESTAMO", "description": "Préstamo"}]
        with patch("app.services.hr_data_service.get_payroll_transactions_for_employees", return_value=txs), \
             patch("app.services.recurring_service.get_recurring_movements", return_value=recurring):
            r = PayrollProjectionService.project_benefits([emp], "2026-12-31", company_id="C1", sandbox=True)

        row = r["rows"][0]
        assert row["salarioPromedio"] > emp["baseSalary"]
        assert row["descuentos"] == 10000.0
        assert row["netoAPagar"] == round(row["total"] - 10000.0, 2)
        assert r["totalNeto"] == row["netoAPagar"]

    def test_fallback_sin_transacciones(self):
        emp = _emp("E2")
        with patch("app.services.hr_data_service.get_payroll_transactions_for_employees", return_value={}), \
             patch("app.services.recurring_service.get_recurring_movements", return_value=[]):
            r = PayrollProjectionService.project_benefits([emp], "2026-12-31", company_id="C1", sandbox=True)

        row = r["rows"][0]
        assert row["salarioPromedio"] == emp["baseSalary"]
        assert row["descuentos"] == 0.0
        assert row["netoAPagar"] == row["total"]
