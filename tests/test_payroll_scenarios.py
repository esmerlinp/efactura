"""Tests para what-if analysis y escenarios combinados de nómina."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date, datetime

from app.services.payroll_service import PayrollService


def _make_emp(**overrides):
    emp = {
        "id": "E1",
        "fullName": "Juan Pérez",
        "baseSalary": 50000.00,
        "status": "activo",
        "department": "Ventas",
    }
    emp.update(overrides)
    return emp


# ═══════════════════════════════════════════════════════════════════════
# WHAT-IF ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

class TestWhatIfAnalysis:

    def test_pct_increase(self):
        emps = [_make_emp()]
        scenario = {"type": "pct_increase", "value": 10}
        r = PayrollService.what_if_analysis(emps, scenario)
        assert r["affectedEmployees"] == 1
        pe = r["perEmployee"][0]
        assert pe["newBase"] == 55000.00

    def test_fixed_increase(self):
        emps = [_make_emp()]
        scenario = {"type": "fixed_increase", "value": 5000}
        r = PayrollService.what_if_analysis(emps, scenario)
        pe = r["perEmployee"][0]
        assert pe["newBase"] == 55000.00

    def test_filtro_departamento(self):
        emps = [_make_emp(department="Ventas"), _make_emp(id="E2", department="Admin", baseSalary=40000)]
        scenario = {"type": "pct_increase", "value": 10, "filter_department": "Ventas"}
        r = PayrollService.what_if_analysis(emps, scenario)
        assert r["affectedEmployees"] == 1
        assert r["perEmployee"][0]["employeeId"] == "E1"

    def test_empleado_inactivo(self):
        emps = [_make_emp(status="inactivo")]
        scenario = {"type": "pct_increase", "value": 10}
        r = PayrollService.what_if_analysis(emps, scenario)
        assert r["affectedEmployees"] == 0

    def test_empleado_sin_salario(self):
        emps = [_make_emp(baseSalary=0)]
        scenario = {"type": "pct_increase", "value": 10}
        r = PayrollService.what_if_analysis(emps, scenario)
        assert r["affectedEmployees"] == 0

    def test_sin_empleados(self):
        r = PayrollService.what_if_analysis([], {"type": "pct_increase", "value": 10})
        assert r["affectedEmployees"] == 0
        assert r["currentMonthly"]["gross"] == 0.0

    def test_impacto_neto(self):
        emps = [_make_emp()]
        scenario = {"type": "pct_increase", "value": 10}
        r = PayrollService.what_if_analysis(emps, scenario)
        assert r["impact"]["net"] > 0

    def test_impacto_empleador(self):
        emps = [_make_emp()]
        scenario = {"type": "pct_increase", "value": 10, "include_employer_contrib": True}
        r = PayrollService.what_if_analysis(emps, scenario)
        assert r["impact"]["employer"] >= 0

    def test_executive_bonus(self):
        emps = [_make_emp()]
        scenario = {"type": "executive_bonus", "value": 10000}
        r = PayrollService.what_if_analysis(emps, scenario)
        assert r["affectedEmployees"] > 0

    def test_multiples_empleados(self):
        emps = [_make_emp(), _make_emp(id="E2", baseSalary=30000)]
        scenario = {"type": "pct_increase", "value": 10}
        r = PayrollService.what_if_analysis(emps, scenario)
        assert r["affectedEmployees"] == 2
        assert len(r["perEmployee"]) == 2


# ═══════════════════════════════════════════════════════════════════════
# BUSINESS DAYS
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateBusinessDays:

    def test_semana_laboral_completa(self):
        r = PayrollService.calculate_business_days("2026-07-06", "2026-07-10")
        assert r == 5

    def test_fin_semana(self):
        r = PayrollService.calculate_business_days("2026-07-11", "2026-07-12")
        assert r == 0

    def test_rango_inverso(self):
        r = PayrollService.calculate_business_days("2026-07-31", "2026-07-01")
        assert r == 0

    def test_fechas_invalidas(self):
        r = PayrollService.calculate_business_days("", "")
        assert r == 0
