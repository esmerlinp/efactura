"""Tests para asientos contables de nómina, validación cierre fiscal e IR-18."""

import pytest
from unittest.mock import MagicMock, patch

import app.services.hr_data_service as hr_data_service
from app.services.payroll_service import PayrollService

RATES = {
    "afpEmployeeRate": 0.0287,
    "afpEmployerRate": 0.0710,
    "sfsEmployeeRate": 0.0304,
    "sfsEmployerRate": 0.0709,
    "srlEmployerRate": 0.0120,
    "infotepRate": 0.01,
    "afpSalaryCap": 464460.00,
    "sfsSalaryCap": 232230.00,
    "minSalary": 23223.00,
    "educationDeduction": 50000.00,
    "isrAnnualTable": [
        [0.0, 416220.00, 0.0, 0.0],
        [416220.01, 624329.00, 0.15, 0.0],
        [624329.01, 867123.00, 0.20, 31216.00],
        [867123.01, float("inf"), 0.25, 79775.00],
    ],
    "overtimeRate": 1.35,
    "workingDaysPerMonth": 23.83,
    "workingHoursPerDay": 8.0,
    "infotepThresholdMultiplier": 5.0,
    "accountSalariesPayable": "2.1.1.01",
    "accountAfpEmployee": "2.1.1.02",
    "accountSfsEmployee": "2.1.1.03",
    "accountIsrEmployee": "2.1.1.04",
    "accountAfpEmployer": "2.1.2.01",
    "accountSfsEmployer": "2.1.2.02",
    "accountSrlEmployer": "2.1.2.03",
    "accountInfotepEmployer": "2.1.2.04",
    "accountInfotepEmployee": "2.1.2.05",
    "accountOtherDeductions": "2.1.1.99",
    "cost_center_accounts": {"General": "6.2.1.01", "Ventas": "6.2.1.01.01"},
    "account_salaries_payable": "2.1.1.01",
    "account_afp_employee": "2.1.1.02",
    "account_sfs_employee": "2.1.1.03",
    "account_isr_employee": "2.1.1.04",
    "account_afp_employer": "2.1.2.01",
    "account_sfs_employer": "2.1.2.02",
    "account_srl_employer": "2.1.2.03",
    "account_infotep_employer": "2.1.2.04",
    "account_infotep_employee": "2.1.2.05",
    "account_other_deductions": "2.1.1.99",
}

TAX_RATES_SNAPSHOT = {
    "afpEmployeeRate": 0.0287,
    "afpEmployerRate": 0.0710,
    "sfsEmployeeRate": 0.0304,
    "sfsEmployerRate": 0.0709,
    "srlEmployerRate": 0.0120,
    "infotepRate": 0.01,
    "afpSalaryCap": 464460.00,
    "sfsSalaryCap": 232230.00,
    "minSalary": 23223.00,
    "educationDeduction": 50000.00,
    "isrAnnualTable": [
        [0.0, 416220.00, 0.0, 0.0],
        [416220.01, 624329.00, 0.15, 0.0],
        [624329.01, 867123.00, 0.20, 31216.00],
        [867123.01, float("inf"), 0.25, 79775.00],
    ],
    "overtimeRate": 1.35,
    "workingDaysPerMonth": 23.83,
    "workingHoursPerDay": 8.0,
    "infotepThresholdMultiplier": 5.0,
    "accountSalariesPayable": "2.1.1.01",
    "accountAfpEmployee": "2.1.1.02",
    "accountSfsEmployee": "2.1.1.03",
    "accountIsrEmployee": "2.1.1.04",
    "accountAfpEmployer": "2.1.2.01",
    "accountSfsEmployer": "2.1.2.02",
    "accountSrlEmployer": "2.1.2.03",
    "accountInfotepEmployer": "2.1.2.04",
    "accountInfotepEmployee": "2.1.2.05",
    "accountOtherDeductions": "2.1.1.99",
    "cost_center_accounts": {"General": "6.2.1.01", "Ventas": "6.2.1.01.01"},
}


def _make_payroll_line(**overrides):
    line = {
        "employeeId": "emp-001",
        "employeeName": "Juan Pérez",
        "totalIncome": 50000.00,
        "netSalary": 43699.33,
        "afpEmployee": 1435.00,
        "sfsEmployee": 1520.00,
        "infotepEmployee": 0.0,
        "isrRetention": 2345.67,
        "afpEmployer": 3550.00,
        "sfsEmployer": 3545.00,
        "srlEmployer": 600.00,
        "infotepEmployer": 500.00,
        "totalEmployerContrib": 8195.00,
        "otherDeductions": 1000.00,
    }
    line.update(overrides)
    return line


# ═══════════════════════════════════════════════════════════════════════
# BUILD ACCOUNTING LINES
# ═══════════════════════════════════════════════════════════════════════

class TestBuildPayrollAccountingLines:

    def _make_period(self, lines):
        return {
            "periodKey": "2026-07",
            "status": "aprobada",
            "payrollLines": lines,
        }

    def test_lineas_basicas(self):
        payroll_period = self._make_period([_make_payroll_line()])
        line = _make_payroll_line()
        with patch.object(PayrollService, 'get_period_lines', return_value=[line]):
            with patch.object(hr_data_service, 'get_tax_rates_snapshot', return_value=TAX_RATES_SNAPSHOT):
                result = PayrollService.build_payroll_accounting_lines(
                    payroll_period, employees={"emp-001": {"costCenter": "General"}}
                )
        assert len(result) > 0
        total_debit = sum(r["debit"] for r in result)
        total_credit = sum(r["credit"] for r in result)
        assert pytest.approx(total_debit, abs=0.02) == total_credit
        assert any("Sueldos y salarios" in r["accountName"] for r in result)

    def test_sin_empleados(self):
        payroll_period = self._make_period([])
        with patch.object(PayrollService, 'get_period_lines', return_value=[]):
            with patch.object(hr_data_service, 'get_tax_rates_snapshot', return_value=TAX_RATES_SNAPSHOT):
                result = PayrollService.build_payroll_accounting_lines(
                    payroll_period, employees={}
                )
        assert result == []

    def test_multiples_centros_costo(self):
        line1 = _make_payroll_line(employeeId="emp-001")
        line2 = _make_payroll_line(employeeId="emp-002", totalIncome=30000.00, netSalary=26000.00)
        employees = {"emp-001": {"costCenter": "Ventas"}, "emp-002": {"costCenter": "General"}}
        payroll_period = self._make_period([line1, line2])
        with patch.object(PayrollService, 'get_period_lines', return_value=[line1, line2]):
            with patch.object(hr_data_service, 'get_tax_rates_snapshot', return_value=TAX_RATES_SNAPSHOT):
                result = PayrollService.build_payroll_accounting_lines(
                    payroll_period, employees=employees
                )
        cuentas_gasto = [r for r in result if r["debit"] > 0]
        cc_names = [r["accountName"] for r in cuentas_gasto]
        assert any("Ventas" in n for n in cc_names)
        assert any("General" in n for n in cc_names)

    def test_todas_las_cuentas(self):
        line = _make_payroll_line()
        payroll_period = self._make_period([line])
        with patch.object(PayrollService, 'get_period_lines', return_value=[line]):
            with patch.object(hr_data_service, 'get_tax_rates_snapshot', return_value=TAX_RATES_SNAPSHOT):
                result = PayrollService.build_payroll_accounting_lines(
                    payroll_period, employees={"emp-001": {}}
                )
        account_codes = [r["accountCode"] for r in result]
        assert "2.1.1.01" in account_codes  # Salaries payable
        assert "2.1.1.02" in account_codes  # AFP employee
        assert "2.1.1.03" in account_codes  # SFS employee

    def test_neto_cero_no_genera_linea_salarios(self):
        line = _make_payroll_line(netSalary=0.0, totalIncome=50000.00)
        payroll_period = self._make_period([line])
        with patch.object(PayrollService, 'get_period_lines', return_value=[line]):
            with patch.object(hr_data_service, 'get_tax_rates_snapshot', return_value=TAX_RATES_SNAPSHOT):
                result = PayrollService.build_payroll_accounting_lines(
                    payroll_period, employees={"emp-001": {}}
                )
        salarios_por_pagar = [r for r in result if r["accountCode"] == "2.1.1.01"]
        assert len(salarios_por_pagar) == 0


# ═══════════════════════════════════════════════════════════════════════
# FISCAL CLOSING VALIDATION
# ═══════════════════════════════════════════════════════════════════════

class TestValidatePayrollForFiscalClosing:

    def _period(self, status="cerrada", key="2026-07", year=2026):
        return {"status": status, "periodKey": key, "year": year, "periodRange": "Julio 2026"}

    def test_todos_cerrados(self):
        periods = [self._period("cerrada", "2026-01"), self._period("cerrada", "2026-02")]
        with patch.object(hr_data_service, 'get_payroll_periods', return_value=periods):
            with patch.object(hr_data_service, 'get_employees', return_value=[]):
                with patch.object(PayrollService, 'get_period_lines', return_value=[]):
                    result = PayrollService.validate_payroll_for_fiscal_closing(
                        "owner-uid", year=2026, sandbox=True
                    )
        assert result["isValid"] is True

    def test_periodo_abierto(self):
        periods = [self._period("calculada", "2026-01")]
        with patch.object(hr_data_service, 'get_payroll_periods', return_value=periods):
            with patch.object(hr_data_service, 'get_employees', return_value=[]):
                with patch.object(PayrollService, 'get_period_lines', return_value=[]):
                    result = PayrollService.validate_payroll_for_fiscal_closing(
                        "owner-uid", year=2026, sandbox=True
                    )
        assert result["isValid"] is False
        assert len(result["errors"]) > 0

    def test_sin_periodos(self):
        with patch.object(hr_data_service, 'get_payroll_periods', return_value=[]):
            with patch.object(hr_data_service, 'get_employees', return_value=[]):
                result = PayrollService.validate_payroll_for_fiscal_closing(
                    "owner-uid", year=2026, sandbox=True
                )
        assert result["isValid"] is False
        assert len(result["warnings"]) > 0

    def test_acumulados_correctos(self):
        line = _make_payroll_line(totalIncome=50000.00, netSalary=43699.33, isrRetention=2345.67)
        periods = [self._period("cerrada", "2026-07")]
        with patch.object(hr_data_service, 'get_payroll_periods', return_value=periods):
            with patch.object(hr_data_service, 'get_employees', return_value=[{"id": "emp-001", "afpProvider": "AFP Popular"}]):
                with patch.object(PayrollService, 'get_period_lines', return_value=[line]):
                    result = PayrollService.validate_payroll_for_fiscal_closing(
                        "owner-uid", year=2026, sandbox=True
                    )
        d = result["details"]
        assert d["totalGross"] == 50000.00
        assert d["totalNet"] == 43699.33
        assert d["totalIsr"] == 2345.67

    def test_empleados_sin_afp(self):
        line = _make_payroll_line(employeeId="emp-001")
        periods = [self._period("cerrada", "2026-07")]
        with patch.object(hr_data_service, 'get_payroll_periods', return_value=periods):
            with patch.object(hr_data_service, 'get_employees', return_value=[{"id": "emp-001"}]):
                with patch.object(PayrollService, 'get_period_lines', return_value=[line]):
                    result = PayrollService.validate_payroll_for_fiscal_closing(
                        "owner-uid", year=2026, sandbox=True
                    )
        assert len(result["warnings"]) > 0


# ═══════════════════════════════════════════════════════════════════════
# IR-18 READINESS
# ═══════════════════════════════════════════════════════════════════════

class TestValidateIR18Readiness:

    def test_listo(self):
        employees = [{
            "id": "emp-001", "cedula": "00112345678", "nationality": "dominicano",
            "occupationCode": "1234", "baseSalary": 50000,
            "afpProvider": "AFP Popular", "status": "activo",
        }]
        with patch.object(hr_data_service, 'get_employees', return_value=employees):
            with patch.object(hr_data_service, 'get_payroll_periods', return_value=[{"year": 2026}]):
                with patch.object(hr_data_service, 'get_payroll_lines_unified', return_value=[]):
                    with patch("app.services.payroll_ytd_service.get_ytd", return_value={"totalIsr": 1500}):
                        result = PayrollService.validate_ir18_readiness("owner-uid", year=2026, sandbox=True)
        assert result["isReady"] is True

    def test_faltan_datos(self):
        employees = [{
            "id": "emp-001", "baseSalary": 50000, "status": "activo",
        }]
        with patch.object(hr_data_service, 'get_employees', return_value=employees):
            with patch.object(hr_data_service, 'get_payroll_periods', return_value=[{"year": 2026}]):
                with patch.object(hr_data_service, 'get_payroll_lines_unified', return_value=[]):
                    with patch("app.services.payroll_ytd_service.get_ytd", return_value={}):
                        result = PayrollService.validate_ir18_readiness("owner-uid", year=2026, sandbox=True)
        assert len(result["warnings"]) > 0
