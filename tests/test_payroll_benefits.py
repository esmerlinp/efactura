"""Tests para prestaciones laborales: regalía pascual, vacaciones, cesantía/preaviso, retroactivos."""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services.payroll_service import PayrollService

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
    "afp_salary_cap": 464460.00,
    "sfs_salary_cap": 232230.00,
    "min_salary": 23223.00,
}


# ═══════════════════════════════════════════════════════════════════════
# CHRISTMAS BONUS (REGALÍA PASCUAL)
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateChristmasBonus:

    def test_anio_completo(self):
        r = PayrollService.calculate_christmas_bonus(45000.0, 12)
        assert r == 45000.0

    def test_6_meses(self):
        r = PayrollService.calculate_christmas_bonus(45000.0, 6)
        expected = round((45000.0 / 12) * 6, 2)
        assert r == expected

    def test_3_meses(self):
        r = PayrollService.calculate_christmas_bonus(45000.0, 3)
        expected = round((45000.0 / 12) * 3, 2)
        assert r == expected

    def test_0_meses(self):
        r = PayrollService.calculate_christmas_bonus(45000.0, 0)
        assert r == 0.0

    def test_mas_de_12_meses(self):
        r = PayrollService.calculate_christmas_bonus(45000.0, 15)
        assert r == 45000.0


# ═══════════════════════════════════════════════════════════════════════
# VACATION DAYS
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateVacationDays:

    def test_menos_1_anio(self):
        hire = (date.today() - timedelta(days=180)).strftime("%Y-%m-%d")
        r = PayrollService.calculate_vacation_days(hire)
        assert 0 < r <= 14

    def test_3_anios(self):
        hire = (date.today() - timedelta(days=1095)).strftime("%Y-%m-%d")
        r = PayrollService.calculate_vacation_days(hire)
        assert r > 0

    def test_mas_de_5_anios(self):
        hire = (date.today() - timedelta(days=2555)).strftime("%Y-%m-%d")
        r = PayrollService.calculate_vacation_days(hire)
        assert r > 0

    def test_fecha_invalida(self):
        r = PayrollService.calculate_vacation_days("")
        assert r == 0

    def test_fecha_futura(self):
        future = (date.today() + timedelta(days=365)).strftime("%Y-%m-%d")
        r = PayrollService.calculate_vacation_days(future)
        assert r == 0


# ═══════════════════════════════════════════════════════════════════════
# SEVERANCE (PREAVISO + CESANTÍA)
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateSeverance:

    def test_menos_3_meses(self):
        hire = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")
        r = PayrollService.calculate_severance(45000, hire, date.today().strftime("%Y-%m-%d"))
        assert r["preaviso"] == 0.0
        assert r["cesantia"] == 0.0

    def test_5_meses(self):
        hire = (date.today() - timedelta(days=150)).strftime("%Y-%m-%d")
        term = date.today().strftime("%Y-%m-%d")
        r = PayrollService.calculate_severance(45000, hire, term)
        assert r["preaviso_days"] > 0
        assert r["cesantia_days"] > 0

    def test_3_anios(self):
        hire = (date.today() - timedelta(days=1095)).strftime("%Y-%m-%d")
        term = date.today().strftime("%Y-%m-%d")
        r = PayrollService.calculate_severance(45000, hire, term)
        assert r["total"] > 0

    def test_con_fecha_terminacion(self):
        hire = "2023-01-01"
        term = "2026-01-01"
        r = PayrollService.calculate_severance(45000, hire, term)
        assert r["total"] > 0

    def test_fechas_invalidas(self):
        r = PayrollService.calculate_severance(45000, "", "")
        assert r["total"] == 0.0

    def test_monto_preaviso_correcto(self):
        hire = "2020-01-01"
        term = "2026-07-01"
        r = PayrollService.calculate_severance(45000, hire, term)
        expected_preaviso = round(28 * (45000 / 23.83), 2)
        assert r["preaviso"] == pytest.approx(expected_preaviso, abs=0.02)


# ═══════════════════════════════════════════════════════════════════════
# RETROACTIVE PAY
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateRetroactivePay:

    def test_sin_retroactividad_fecha_futura(self):
        future = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
        emp = {"baseSalary": 50000}
        r = PayrollService.calculate_retroactive_pay(emp, [], 55000, future, RD_PARAMS)
        assert r["retroactiveMonths"] == 0

    def test_sin_retroactividad_mismo_salario(self):
        past = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        emp = {"baseSalary": 50000}
        r = PayrollService.calculate_retroactive_pay(emp, [], 50000, past, RD_PARAMS)
        assert r["retroactiveMonths"] == 0

    def test_retroactivo_3_meses(self):
        past = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
        emp = {"baseSalary": 50000}
        r = PayrollService.calculate_retroactive_pay(emp, [], 60000, past, RD_PARAMS)
        assert r["retroactiveMonths"] > 0
        assert r["retroactiveGross"] > 0

    def test_empleado_sin_salario(self):
        past = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        emp = {"baseSalary": 0}
        r = PayrollService.calculate_retroactive_pay(emp, [], 55000, past, RD_PARAMS)
        assert "error" in r or r["retroactivePay"] == 0

    def test_fecha_invalida(self):
        emp = {"baseSalary": 50000}
        r = PayrollService.calculate_retroactive_pay(emp, [], 55000, "fecha-invalida", RD_PARAMS)
        assert r["retroactiveMonths"] == 0

    def test_retroactivo_details(self):
        past = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
        emp = {"baseSalary": 50000}
        r = PayrollService.calculate_retroactive_pay(emp, [], 60000, past, RD_PARAMS)
        assert len(r["details"]) > 0
        assert r["details"][0]["oldSalary"] == 50000
        assert r["details"][0]["newSalary"] == 60000
