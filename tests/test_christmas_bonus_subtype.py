"""Tests para la nómina tipo «Regalía Pascual» (plan A)."""

from datetime import date

from app.services.payroll_service import PayrollService
from app.web.rrhh.payroll_process import (
    _months_worked_in_year,
    _should_skip_christmas_rule,
)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

class TestMonthsWorkedInYear:

    def test_contratado_antes_del_anio(self):
        assert _months_worked_in_year("2025-03-01", today=date(2026, 12, 1)) == 12

    def test_contratado_en_enero(self):
        assert _months_worked_in_year("2026-01-15", today=date(2026, 12, 1)) == 12

    def test_contratado_en_julio(self):
        assert _months_worked_in_year("2026-07-10", today=date(2026, 12, 1)) == 6

    def test_contratado_en_diciembre(self):
        assert _months_worked_in_year("2026-12-05", today=date(2026, 12, 1)) == 1

    def test_sin_fecha(self):
        assert _months_worked_in_year("", today=date(2026, 12, 1)) == 12

    def test_fecha_invalida(self):
        assert _months_worked_in_year("garbage", today=date(2026, 12, 1)) == 12


class TestSkipChristmasRule:

    def test_skip_regla_auto_con_regalia_explicita(self):
        assert _should_skip_christmas_rule({"generatedBy": "christmas_bonus"}, True) is True

    def test_no_skip_sin_regalia_explicita(self):
        assert _should_skip_christmas_rule({"generatedBy": "christmas_bonus"}, False) is False

    def test_no_skip_otras_reglas(self):
        assert _should_skip_christmas_rule({"id": "R1"}, True) is False


# ═══════════════════════════════════════════════════════════════════════
# CONTABILIDAD — GASTO DE REGALÍA SEPARADO
# ═══════════════════════════════════════════════════════════════════════

def _line(**overrides):
    line = {
        "employeeId": "E1",
        "totalIncome": 30000.0,
        "netSalary": 25000.0,
        "totalEmployerContrib": 3000.0,
        "christmasBonus": 0.0,
        "afpEmployee": 0.0, "sfsEmployee": 0.0, "isrRetention": 0.0,
        "afpEmployer": 0.0, "sfsEmployer": 0.0, "srlEmployer": 0.0,
        "infotepEmployer": 0.0, "infotepEmployee": 0.0, "otherDeductions": 0.0,
    }
    line.update(overrides)
    return line


def _period(lines):
    return {
        "id": "",
        "periodKey": "2026-12-M",
        "periodSubType": "christmas_bonus",
        "taxRatesSnapshot": {},
        "lines": lines,
    }


class TestAccountingSplitChristmas:

    def test_regalia_separa_gasto_por_centro_de_costo(self):
        period = _period([_line(christmasBonus=15000.0)])
        lines = PayrollService.build_payroll_accounting_lines(
            period, employees={}, company_id="", sandbox=True)

        regalia = [l for l in lines if "Regalía" in l.get("description", "")]
        assert len(regalia) == 1
        assert regalia[0]["accountCode"] == "6.1.1.02"
        assert regalia[0]["debit"] == 15000.0
        assert regalia[0]["credit"] == 0.0

        sueldos = [l for l in lines if "Sueldos" in l.get("accountName", "")]
        assert len(sueldos) == 1
        assert sueldos[0]["debit"] == 30000.0 + 3000.0 - 15000.0

        neto = [l for l in lines if l.get("credit", 0) > 0]
        assert sum(l["credit"] for l in neto) == 25000.0

    def test_sin_regalia_comportamiento_actual(self):
        period = _period([_line(christmasBonus=0.0)])
        lines = PayrollService.build_payroll_accounting_lines(
            period, employees={}, company_id="", sandbox=True)

        assert not any("Regalía" in l.get("description", "") for l in lines)
        sueldos = [l for l in lines if "Sueldos" in l.get("accountName", "")]
        assert sueldos[0]["debit"] == 33000.0

    def test_regalia_mezclada_en_nomina_regular_tambien_se_separa(self):
        period = _period([_line(christmasBonus=10000.0)])
        period["periodSubType"] = "regular"
        lines = PayrollService.build_payroll_accounting_lines(
            period, employees={}, company_id="", sandbox=True)

        regalia = [l for l in lines if "Regalía" in l.get("description", "")]
        assert len(regalia) == 1
        assert regalia[0]["debit"] == 10000.0
