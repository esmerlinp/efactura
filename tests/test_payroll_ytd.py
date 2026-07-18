"""Tests para PayrollYTService — acumulación Year-to-Date."""

import pytest
from unittest.mock import patch, MagicMock

from app.services.payroll_ytd_service import accumulate_ytd, _empty_ytd


class TestAccumulateYTD:

    def _make_line(self, **overrides):
        line = {
            "totalIncome": 50000.00,
            "afpEmployee": 1435.00,
            "sfsEmployee": 1520.00,
            "infotepEmployee": 0.0,
            "isrRetention": 2345.67,
            "otherDeductions": 1000.00,
            "netSalary": 43699.33,
            "afpEmployer": 3550.00,
            "sfsEmployer": 3545.00,
            "srlEmployer": 600.00,
            "infotepEmployer": 500.00,
            "totalEmployerContrib": 8195.00,
            "transactionSummary": [],
        }
        line.update(overrides)
        return line

    def test_acumulacion_inicial(self):
        prev = _empty_ytd("EMP1", 2025)
        line = self._make_line()
        result = accumulate_ytd(prev, line)
        assert result["grossIncome"] == 50000.00
        assert result["afpEmployee"] == 1435.00
        assert result["sfsEmployee"] == 1520.00
        assert result["infotepEmployee"] == 0.0
        assert result["isrRetention"] == 2345.67
        assert result["otherDeductions"] == 1000.00
        assert result["netSalary"] == 43699.33
        assert result["afpEmployer"] == 3550.00
        assert result["sfsEmployer"] == 3545.00
        assert result["srlEmployer"] == 600.00
        assert result["infotepEmployer"] == 500.00
        assert result["totalEmployerContrib"] == 8195.00
        assert result["periodsCount"] == 1

    def test_acumulacion_segundo_periodo(self):
        prev = _empty_ytd("EMP1", 2025)
        prev["grossIncome"] = 50000.00
        prev["afpEmployee"] = 1435.00
        prev["netSalary"] = 43699.33
        prev["periodsCount"] = 1
        line = self._make_line()
        result = accumulate_ytd(prev, line)
        assert result["grossIncome"] == 100000.00
        assert result["afpEmployee"] == 2870.00
        assert result["netSalary"] == 87398.66
        assert result["periodsCount"] == 2

    def test_acumulacion_conceptos(self):
        prev = _empty_ytd("EMP1", 2025)
        line = self._make_line(transactionSummary=[
            {"conceptCode": "BONO", "amount": 5000.00, "type": "earning"},
        ])
        result = accumulate_ytd(prev, line)
        assert "BONO" in result["byConcept"]
        assert result["byConcept"]["BONO"]["amount"] == 5000.00
        assert result["byConcept"]["BONO"]["periods"] == 1
        assert result["byConcept"]["BONO"]["type"] == "earning"

    def test_acumulacion_mensual(self):
        prev = _empty_ytd("EMP1", 2025)
        line = self._make_line()
        result = accumulate_ytd(prev, line, period_key="2025-07-M")
        assert "2025-07" in result["monthly"]
        m = result["monthly"]["2025-07"]
        assert m["grossIncome"] == 50000.00
        assert m["netSalary"] == 43699.33
        assert m["isrRetention"] == 2345.67
        result2 = accumulate_ytd(result, line, period_key="2025-07-M")
        assert result2["monthly"]["2025-07"]["grossIncome"] == 100000.00

    def test_periods_count(self):
        prev = _empty_ytd("EMP1", 2025)
        line = self._make_line()
        result = accumulate_ytd(prev, line)
        assert result["periodsCount"] == 1
        result2 = accumulate_ytd(result, line)
        assert result2["periodsCount"] == 2
        result3 = accumulate_ytd(result2, line)
        assert result3["periodsCount"] == 3

    def test_multiples_conceptos(self):
        prev = _empty_ytd("EMP1", 2025)
        line = self._make_line(transactionSummary=[
            {"conceptCode": "BONO", "amount": 5000.00, "type": "earning"},
            {"conceptCode": "COMISION", "amount": 3000.00, "type": "earning"},
            {"conceptCode": "HORAS_EXTRA", "amount": 2000.00, "type": "earning"},
        ])
        result = accumulate_ytd(prev, line)
        assert len(result["byConcept"]) == 3
        assert result["byConcept"]["BONO"]["amount"] == 5000.00
        assert result["byConcept"]["COMISION"]["amount"] == 3000.00
        assert result["byConcept"]["HORAS_EXTRA"]["amount"] == 2000.00

    def test_sin_transaction_summary(self):
        prev = _empty_ytd("EMP1", 2025)
        line = self._make_line()
        line.pop("transactionSummary", None)
        result = accumulate_ytd(prev, line)
        assert result["byConcept"] == {}


class TestEmptyYTD:

    def test_empty_ytd_structure(self):
        result = _empty_ytd("EMP1", 2025, "CTR1")
        assert result["employeeId"] == "EMP1"
        assert result["contractId"] == "CTR1"
        assert result["year"] == 2025
        assert result["grossIncome"] == 0.0
        assert result["afpEmployee"] == 0.0
        assert result["sfsEmployee"] == 0.0
        assert result["infotepEmployee"] == 0.0
        assert result["isrRetention"] == 0.0
        assert result["otherDeductions"] == 0.0
        assert result["netSalary"] == 0.0
        assert result["afpEmployer"] == 0.0
        assert result["sfsEmployer"] == 0.0
        assert result["srlEmployer"] == 0.0
        assert result["infotepEmployer"] == 0.0
        assert result["totalEmployerContrib"] == 0.0
        assert result["periodsCount"] == 0
        assert result["byConcept"] == {}
        assert result["monthly"] == {}
