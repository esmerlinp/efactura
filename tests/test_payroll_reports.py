"""Tests para exportaciones TSS: CSV y autodeterminación SUIRPLUS."""

import pytest
from unittest.mock import patch, MagicMock

from app.services.payroll_service import PayrollService


class TestGenerateTSSCSV:

    def _make_line(self, emp_id, name, cedula, income=50000.00):
        return {
            "employeeId": emp_id,
            "employeeName": name,
            "cedula": cedula,
            "totalIncome": income,
            "afpEmployee": round(income * 0.0287, 2),
            "sfsEmployee": round(income * 0.0304, 2),
            "afpEmployer": round(income * 0.0710, 2),
            "sfsEmployer": round(income * 0.0709, 2),
            "srlEmployer": round(income * 0.0120, 2),
            "infotepEmployer": round(income * 0.01, 2),
            "netSalary": round(income * 0.8, 2),
        }

    def test_csv_con_empleados(self):
        period = {"periodKey": "2025-07-M"}
        employees = [
            {"id": "E1", "cedula": "00100000001", "fullName": "Juan Perez"},
            {"id": "E2", "cedula": "00100000002", "fullName": "Maria Gomez"},
        ]
        lines = [
            self._make_line("E1", "Juan Perez", "00100000001", 50000),
            self._make_line("E2", "Maria Gomez", "00100000002", 45000),
        ]
        with patch.object(PayrollService, 'get_period_lines', return_value=lines):
            result = PayrollService.generate_tss_csv(period, employees)
        assert "Cedula" in result
        assert "00100000001" in result
        assert "00100000002" in result
        assert "Juan Perez" in result
        assert "Maria Gomez" in result
        rows = [r for r in result.strip().split("\n") if r.strip()]
        assert len(rows) == 3  # header + 2 employees

    def test_csv_sin_empleados(self):
        period = {"periodKey": "2025-07-M"}
        with patch.object(PayrollService, 'get_period_lines', return_value=[]):
            result = PayrollService.generate_tss_csv(period, [])
        rows = [r for r in result.strip().split("\n") if r.strip()]
        assert len(rows) == 1
        assert "Cedula" in rows[0]

    def test_csv_empleado_sin_cedula(self):
        period = {"periodKey": "2025-07-M"}
        employees = [{"id": "E1", "fullName": "Juan Perez"}]
        lines = [self._make_line("E1", "Juan Perez", "", 50000)]
        with patch.object(PayrollService, 'get_period_lines', return_value=lines):
            result = PayrollService.generate_tss_csv(period, employees)
        assert "Juan Perez" in result
        assert ",," in result or result.count(",") >= 9


class TestGenerateTSSAutodeterminacion:

    def _make_emp(self, **overrides):
        emp = {
            "id": "E1", "cedula": "00100000001",
            "firstName": "Juan", "middleName": "Carlos",
            "firstLastName": "Perez", "secondLastName": "Garcia",
            "gender": "masculino", "birthDate": "1990-01-15",
        }
        emp.update(overrides)
        return emp

    def _make_line(self, emp_id="E1", income=50000.00):
        return {
            "employeeId": emp_id,
            "totalIncome": income,
            "afpEmployee": round(income * 0.0287, 2),
            "sfsEmployee": round(income * 0.0304, 2),
            "afpEmployer": round(income * 0.0710, 2),
            "sfsEmployer": round(income * 0.0709, 2),
            "srlEmployer": round(income * 0.0120, 2),
            "infotepEmployer": round(income * 0.01, 2),
        }

    def test_formato_header(self):
        period = {"periodKey": "2025-07-M", "year": 2025, "month": 7}
        with patch.object(PayrollService, 'get_period_lines', return_value=[]):
            result = PayrollService.generate_tss_autodeterminacion(
                period, [], employer_rnc="12345678901"
            )
        lines = result["content"].strip().split("\n")
        header = lines[0]
        assert len(header) == 20
        assert header[0] == "E"
        assert header[1:3] == "AM"

    def test_formato_detail(self):
        period = {"periodKey": "2025-07-M", "year": 2025, "month": 7}
        employees = [self._make_emp()]
        lines = [self._make_line()]
        with patch.object(PayrollService, 'get_period_lines', return_value=lines):
            result = PayrollService.generate_tss_autodeterminacion(
                period, employees, employer_rnc="12345678901"
            )
        detail = result["content"].strip().split("\n")[1]
        assert len(detail) == 366
        assert detail[0] == "D"

    def test_formato_trailer(self):
        period = {"periodKey": "2025-07-M", "year": 2025, "month": 7}
        employees = [self._make_emp()]
        lines = [self._make_line()]
        with patch.object(PayrollService, 'get_period_lines', return_value=lines):
            result = PayrollService.generate_tss_autodeterminacion(
                period, employees, employer_rnc="12345678901"
            )
        trailer = result["content"].strip().split("\n")[-1]
        assert trailer[0] == "S"
        assert len(trailer) == 7

    def test_topes_respetados(self):
        period = {"periodKey": "2025-07-M", "year": 2025, "month": 7}
        employees = [self._make_emp(afpSalaryCap=464460.00)]
        lines = [self._make_line(income=500000.00)]
        with patch.object(PayrollService, 'get_period_lines', return_value=lines):
            result = PayrollService.generate_tss_autodeterminacion(
                period, employees, employer_rnc="12345678901"
            )
        detail = result["content"].strip().split("\n")[1]
        salario_ss_str = detail[169:185]
        assert float(salario_ss_str) == pytest.approx(464460.00, abs=0.01)

    def test_sin_empleados(self):
        period = {"periodKey": "2025-07-M", "year": 2025, "month": 7}
        with patch.object(PayrollService, 'get_period_lines', return_value=[]):
            result = PayrollService.generate_tss_autodeterminacion(
                period, [], employer_rnc="12345678901"
            )
        lines = result["content"].strip().split("\n")
        assert len(lines) == 2  # header + trailer
        assert lines[0][0] == "E"
        assert lines[-1][0] == "S"
