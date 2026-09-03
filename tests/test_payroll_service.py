"""Tests para PayrollService — cálculo de nómina, horas extras, prorrateo, pre-validación y anomalías."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import date, datetime, timedelta

from app.services.payroll_service import PayrollService

RD_PARAMS = {
    "afp_employee_rate": 0.0287,
    "afp_employer_rate": 0.0710,
    "sfs_employee_rate": 0.0304,
    "sfs_employer_rate": 0.0709,
    "srl_employer_rate": 0.0120,
    "srl_employer_rates": {1: 0.0110, 2: 0.0115, 3: 0.0120, 4: 0.0130},
    "srl_salary_cap": 92892.00,
    "srl_risk_category": 3,
    "infotep_employer_rate": 0.01,
    "infotep_employee_rate": 0.005,
    "infotep_rate": 0.01,
    "afp_salary_cap": 464460.00,
    "sfs_salary_cap": 232230.00,
    "min_salary": 23223.00,
    "dependents_additional_rate": 1919.78,
    "education_deduction": 50000.00,
    "isr_table": [
        {"from": 0.0, "to": 416220.00, "rate": 0.0, "deduction": 0.0},
        {"from": 416220.01, "to": 624329.00, "rate": 0.15, "deduction": 0.0},
        {"from": 624329.01, "to": 867123.00, "rate": 0.20, "deduction": 31216.00},
        {"from": 867123.01, "to": float("inf"), "rate": 0.25, "deduction": 79776.00},
    ],
    "overtime_rate": 1.35,
    "working_days_per_month": 23.83,
    "working_hours_per_day": 8.0,
    "infotep_threshold_multiplier": 5.0,
}


# ═══════════════════════════════════════════════════════════════════════
# CALCULATE PAYROLL LINE
# ═══════════════════════════════════════════════════════════════════════

class TestCalculatePayrollLine:

    def test_salario_25k_mensual_sin_isr(self):
        """Salario 25,000 mensual → ISR=0, TSS aplica"""
        r = PayrollService.calculate_payroll_line(base_salary=25000.00, tax_rates=RD_PARAMS)
        assert r["totalIncome"] == 25000.00
        assert r["isrRetention"] == 0.0
        assert r["afpEmployee"] > 0
        assert r["sfsEmployee"] > 0
        assert r["netSalary"] < 25000.00

    def test_salario_50k_mensual_con_isr(self):
        """Salario 50,000 mensual → ISR tramo 15%"""
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, tax_rates=RD_PARAMS)
        assert r["totalIncome"] == 50000.00
        assert r["isrRetention"] > 0
        assert r["netSalary"] > 0
        assert r["totalIncome"] > r["netSalary"]

    def test_salario_100k_mensual(self):
        r = PayrollService.calculate_payroll_line(base_salary=100000.00, tax_rates=RD_PARAMS)
        assert r["totalIncome"] == 100000.00
        assert r["isrRetention"] > 1000

    def test_salario_500k_mensual_topado(self):
        """Salario 500,000 → AFP y SFS topados, ISR tramo 25%"""
        r = PayrollService.calculate_payroll_line(base_salary=500000.00, tax_rates=RD_PARAMS)
        afp_max = round(464460.00 * 0.0287, 2)
        sfs_max = round(232230.00 * 0.0304, 2)
        assert r["afpEmployee"] == afp_max
        assert r["sfsEmployee"] == sfs_max

    def test_salario_quincenal(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, period_type="quincenal", tax_rates=RD_PARAMS)
        assert r["grossSalary"] == 25000.00

    def test_salario_con_overtime(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, overtime_hours=10, tax_rates=RD_PARAMS)
        assert r["overtimePay"] > 0
        assert r["overtimeHours"] == 10

    def test_salario_con_comision(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, commission=5000.00, tax_rates=RD_PARAMS)
        assert r["totalIncome"] == 55000.00
        assert r["commission"] == 5000.00

    def test_salario_con_bonus(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, bonus=10000.00, tax_rates=RD_PARAMS)
        assert r["totalIncome"] == 60000.00
        assert r["bonus"] == 10000.00

    def test_salario_con_other_income(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, other_income=5000.00, tax_rates=RD_PARAMS)
        assert r["totalIncome"] == 55000.00
        assert r["otherIncome"] == 5000.00

    def test_salario_con_other_deductions(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, other_deductions=3000.00, tax_rates=RD_PARAMS)
        assert r["otherDeductions"] == 3000.00

    def test_salario_con_prorated_salary(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, prorated_salary=30000.00, tax_rates=RD_PARAMS)
        assert r["grossSalary"] == 30000.00

    def test_salario_con_education_deduction(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, education_deduction=4166.67, tax_rates=RD_PARAMS)
        assert r["isrRetention"] >= 0

    def test_salario_custom_overtime_rate(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, overtime_hours=10, overtime_rate=2.0, tax_rates=RD_PARAMS)
        ref = PayrollService.calculate_payroll_line(base_salary=50000.00, overtime_hours=10, overtime_rate=1.35, tax_rates=RD_PARAMS)
        assert r["overtimePay"] > ref["overtimePay"]

    def test_total_employer_contributions(self):
        r = PayrollService.calculate_payroll_line(base_salary=50000.00, tax_rates=RD_PARAMS)
        expected = round(r["afpEmployer"] + r["sfsEmployer"] + r["srlEmployer"] + r["infotepEmployer"], 2)
        assert r["totalEmployerContrib"] == expected


# ═══════════════════════════════════════════════════════════════════════
# PRORATE SALARY
# ═══════════════════════════════════════════════════════════════════════

class TestProrateSalary:

    def test_periodo_completo_sin_cambios(self):
        r = PayrollService.prorate_salary(50000.00, "2026-07-01", "2026-07-31")
        assert r is None

    def test_entrada_mitad_periodo(self):
        r = PayrollService.prorate_salary(50000.00, "2026-07-01", "2026-07-31", hire_date="2026-07-15")
        assert r is not None
        assert r < 50000.00

    def test_salida_mitad_periodo(self):
        r = PayrollService.prorate_salary(50000.00, "2026-07-01", "2026-07-31", termination_date="2026-07-15")
        assert r is not None
        assert r < 50000.00

    def test_entrada_y_salida_mismo_periodo(self):
        r = PayrollService.prorate_salary(50000.00, "2026-07-01", "2026-07-31",
                                           hire_date="2026-07-10", termination_date="2026-07-20")
        assert r is not None
        assert 0 < r < 50000.00

    def test_con_salary_history(self):
        r = PayrollService.prorate_salary(50000.00, "2026-07-01", "2026-07-31",
                                           salary_history=[{"effectiveDate": "2026-07-15", "amount": 60000.00}])
        assert r is not None

    def test_empleado_no_trabajo_periodo(self):
        r = PayrollService.prorate_salary(50000.00, "2026-07-01", "2026-07-31",
                                           hire_date="2026-08-01")
        assert r == 0.0

    def test_fechas_invalidas(self):
        r = PayrollService.prorate_salary(50000.00, "fecha-invalida", "2026-07-31")
        assert r == 50000.00


# ═══════════════════════════════════════════════════════════════════════
# DESCUENTO POR LICENCIA NO PAGADA
# ═══════════════════════════════════════════════════════════════════════

class TestUnpaidLeaveDeduction:

    # 2026-08-13 (jue) .. 2026-08-17 (lun) — días hábiles: jue 13, vie 14, lun 17
    LEAVE = [{
        "id": "L1", "employeeId": "E1", "status": "aprobada",
        "paidByPayroll": False, "startDate": "2026-08-13", "endDate": "2026-08-17",
    }]

    @pytest.fixture(autouse=True)
    def _no_holidays(self):
        with patch("app.services.holiday_service.HolidayService.get_holiday_dates", return_value=set()):
            yield

    def test_quincena1_dos_dias_habiles(self):
        r = PayrollService.unpaid_leave_deduction(
            23830.00, self.LEAVE, "2026-08-01", "2026-08-15", working_days=23.83)
        assert r["days"] == 2

    def test_quincena2_un_dia_habil(self):
        r = PayrollService.unpaid_leave_deduction(
            23830.00, self.LEAVE, "2026-08-16", "2026-08-31", working_days=23.83)
        assert r["days"] == 1

    def test_excluye_fines_de_semana(self):
        # Período completo agosto: solo jue/vie/lun son hábiles (3, no 5)
        r = PayrollService.unpaid_leave_deduction(
            23830.00, self.LEAVE, "2026-08-01", "2026-08-31", working_days=23.83)
        assert r["days"] == 3

    def test_licencia_pagada_no_descuenta(self):
        paid = [dict(self.LEAVE[0], paidByPayroll=True)]
        r = PayrollService.unpaid_leave_deduction(
            23830.00, paid, "2026-08-01", "2026-08-31", working_days=23.83)
        assert r["days"] == 0
        assert r["amount"] == 0.0

    def test_sin_indicador_por_defecto_pagada(self):
        legacy = [{k: v for k, v in self.LEAVE[0].items() if k != "paidByPayroll"}]
        r = PayrollService.unpaid_leave_deduction(
            23830.00, legacy, "2026-08-01", "2026-08-31", working_days=23.83)
        assert r["days"] == 0

    def test_solo_aprobadas(self):
        pendiente = [dict(self.LEAVE[0], status="pendiente")]
        r = PayrollService.unpaid_leave_deduction(
            23830.00, pendiente, "2026-08-01", "2026-08-31", working_days=23.83)
        assert r["days"] == 0

    def test_monto_por_dia_habil(self):
        # daily_rate = 23830 / 23.83 = 1000 → 3 días = 3000
        r = PayrollService.unpaid_leave_deduction(
            23830.00, self.LEAVE, "2026-08-01", "2026-08-31", working_days=23.83)
        assert r["days"] == 3
        assert r["amount"] == round(23830.00 / 23.83 * 3, 2)

    def test_deduplica_solape_entre_licencias(self):
        overlapping = self.LEAVE + [dict(self.LEAVE[0], id="L2", startDate="2026-08-14", endDate="2026-08-17")]
        r = PayrollService.unpaid_leave_deduction(
            23830.00, overlapping, "2026-08-01", "2026-08-31", working_days=23.83)
        assert r["days"] == 3

    def test_sin_solape_con_periodo(self):
        r = PayrollService.unpaid_leave_deduction(
            23830.00, self.LEAVE, "2026-09-01", "2026-09-30", working_days=23.83)
        assert r["days"] == 0

    def test_salario_cero_no_aplica(self):
        r = PayrollService.unpaid_leave_deduction(
            0.0, self.LEAVE, "2026-08-01", "2026-08-31", working_days=23.83)
        assert r["days"] == 0


# ═══════════════════════════════════════════════════════════════════════
# HORARIO SEMANAL (workSchedule / herencia de puesto)
# ═══════════════════════════════════════════════════════════════════════

class TestWorkSchedule:

    def test_work_days_from_schedule(self):
        sched = [
            {"day": 5, "start": "08:00", "end": "17:00"},
            {"day": 6, "start": "08:00", "end": "12:00"},
            {"day": 0, "start": "08:00", "end": "08:00"},  # start == end → ignorado
        ]
        assert PayrollService.work_days_from_schedule(sched) == {5, 6}

    def test_work_days_from_schedule_vacio(self):
        assert PayrollService.work_days_from_schedule([]) == set()
        assert PayrollService.work_days_from_schedule(None) == set()

    def test_resolve_work_days_custom_wins(self):
        emp = {"workScheduleCustom": True, "workSchedule": [{"day": 5, "start": "08:00", "end": "17:00"}]}
        pos = {"workSchedule": [{"day": 0, "start": "08:00", "end": "17:00"}]}
        assert PayrollService.resolve_work_days(emp, pos) == {5}

    def test_resolve_work_days_inherit_position(self):
        emp = {"workScheduleCustom": False, "workSchedule": []}
        pos = {"workSchedule": [{"day": 5, "start": "08:00", "end": "17:00"},
                                {"day": 6, "start": "08:00", "end": "17:00"}]}
        assert PayrollService.resolve_work_days(emp, pos) == {5, 6}

    def test_resolve_work_days_default_lun_vie(self):
        assert PayrollService.resolve_work_days({}, {}) == {0, 1, 2, 3, 4}

    def test_calculate_business_days_weekend_worker(self):
        # Solo sábado y domingo: agosto 2026 tiene 5 sáb + 5 dom = 10
        r = PayrollService.calculate_business_days("2026-08-01", "2026-08-31", work_days={5, 6})
        assert r == 10

    def test_calculate_business_days_default_lun_vie(self):
        r = PayrollService.calculate_business_days("2026-08-01", "2026-08-31")
        assert r == 21  # agosto 2026: 21 días hábiles L-V

    def test_unpaid_leave_deduction_weekend_worker(self):
        leave = [{"id": "L1", "employeeId": "E1", "status": "aprobada",
                  "paidByPayroll": False, "startDate": "2026-08-15", "endDate": "2026-08-16"}]
        with patch("app.services.holiday_service.HolidayService.get_holiday_dates", return_value=set()):
            r = PayrollService.unpaid_leave_deduction(
                23830.00, leave, "2026-08-01", "2026-08-31",
                working_days=23.83, work_days={5, 6})
        assert r["days"] == 2


# ═══════════════════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ═══════════════════════════════════════════════════════════════════════

class TestAnomalyDetection:

    def test_sin_anomalias(self):
        lines = [{"employeeId": "E1", "employeeName": "Test", "netSalary": 40000, "totalIncome": 50000, "overtimeHours": 0}]
        employees = {"E1": {"afpProvider": "AFP Popular", "baseSalary": 50000}}
        r = PayrollService.detect_anomalies(lines, employees)
        assert len(r["errors"]) == 0
        assert len(r["warnings"]) == 0

    def test_sin_afp(self):
        lines = [{"employeeId": "E1", "employeeName": "Test", "netSalary": 40000, "totalIncome": 50000}]
        employees = {"E1": {"afpProvider": "", "baseSalary": 50000}}
        r = PayrollService.detect_anomalies(lines, employees)
        assert len(r["errors"]) > 0

    def test_neto_negativo(self):
        lines = [{"employeeId": "E1", "employeeName": "Test", "netSalary": -100, "totalIncome": 50000}]
        employees = {"E1": {"afpProvider": "AFP Popular", "baseSalary": 50000}}
        r = PayrollService.detect_anomalies(lines, employees)
        assert len(r["warnings"]) > 0

    def test_salario_base_cero(self):
        lines = [{"employeeId": "E1", "employeeName": "Test", "netSalary": 0, "totalIncome": 0}]
        employees = {"E1": {"afpProvider": "AFP Popular", "baseSalary": 0}}
        r = PayrollService.detect_anomalies(lines, employees)
        assert len(r["errors"]) > 0

    def test_variacion_ingreso_mayor_50(self):
        lines = [{"employeeId": "E1", "employeeName": "Test", "netSalary": 40000, "totalIncome": 100000}]
        employees = {"E1": {"afpProvider": "AFP Popular", "baseSalary": 50000}}
        r = PayrollService.detect_anomalies(lines, employees)
        assert any("50%" in w for w in r["warnings"])

    def test_variacion_neta_mayor_20(self):
        lines = [{"employeeId": "E1", "employeeName": "Test", "netSalary": 50000, "totalIncome": 60000}]
        employees = {"E1": {"afpProvider": "AFP Popular", "baseSalary": 50000}}
        prev = [{"employeeId": "E1", "netSalary": 30000}]
        r = PayrollService.detect_anomalies(lines, employees, previous_lines=prev)
        assert any("67%" in w for w in r["warnings"])

    def test_horas_extra_exceden_40(self):
        lines = [{"employeeId": "E1", "employeeName": "Test", "netSalary": 40000, "totalIncome": 50000, "overtimeHours": 50}]
        employees = {"E1": {"afpProvider": "AFP Popular", "baseSalary": 50000}}
        r = PayrollService.detect_anomalies(lines, employees)
        assert any("40" in w for w in r["warnings"])


# ═══════════════════════════════════════════════════════════════════════
# PRE-VALIDATE EMPLOYEES
# ═══════════════════════════════════════════════════════════════════════

class TestPreValidateEmployees:

    def test_empleado_valido(self):
        emps = [{"id": "E1", "firstName": "Juan", "firstLastName": "Pérez",
                 "baseSalary": 50000, "afpProvider": "AFP Popular", "cedula": "00112345678"}]
        r = PayrollService.validate_employees_before_payroll(emps)
        assert len(r["errors"]) == 0
        assert len(r["warnings"]) == 0

    def test_sin_afp(self):
        emps = [{"id": "E1", "firstName": "Juan", "baseSalary": 50000, "cedula": "00112345678"}]
        r = PayrollService.validate_employees_before_payroll(emps)
        assert len(r["errors"]) == 1

    def test_salario_cero(self):
        emps = [{"id": "E1", "firstName": "Juan", "baseSalary": 0, "afpProvider": "AFP Popular", "cedula": "00112345678"}]
        r = PayrollService.validate_employees_before_payroll(emps)
        assert len(r["errors"]) == 1

    def test_sin_cedula(self):
        emps = [{"id": "E1", "firstName": "Juan", "baseSalary": 50000, "afpProvider": "AFP Popular"}]
        r = PayrollService.validate_employees_before_payroll(emps)
        assert len(r["warnings"]) == 1

    def test_multiples_errores(self):
        emps = [
            {"id": "E1", "firstName": "Juan", "baseSalary": 50000, "afpProvider": "AFP Popular"},
            {"id": "E2", "firstName": "Ana", "baseSalary": 0, "afpProvider": "AFP Popular"},
        ]
        r = PayrollService.validate_employees_before_payroll(emps)
        assert len(r["errors"]) == 1


# ═══════════════════════════════════════════════════════════════════════
# CALCULATE OVERTIME
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateOvertime:

    def test_sin_horas(self):
        r = PayrollService._calculate_overtime(50000, 0, 1.35)
        assert r == 0.0

    def test_10_horas(self):
        r = PayrollService._calculate_overtime(50000, 10, 1.35)
        expected = round((50000 / 23.83 / 8) * 1.35 * 10, 2)
        assert r == expected

    def test_tasa_personalizada(self):
        r = PayrollService._calculate_overtime(50000, 10, 2.0)
        expected = round((50000 / 23.83 / 8) * 2.0 * 10, 2)
        assert r == expected

    def test_salario_cero(self):
        r = PayrollService._calculate_overtime(0, 10, 1.35)
        assert r == 0.0

    def test_working_days_personalizados(self):
        r = PayrollService._calculate_overtime(50000, 10, 1.35, working_days=20, working_hours=8)
        expected = round((50000 / 20 / 8) * 1.35 * 10, 2)
        assert r == expected


# ═══════════════════════════════════════════════════════════════════════
# BUSINESS DAYS
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateBusinessDays:

    def test_semana_completa(self):
        r = PayrollService.calculate_business_days("2026-07-06", "2026-07-10")
        assert r == 5

    def test_fin_de_semana(self):
        r = PayrollService.calculate_business_days("2026-07-11", "2026-07-12")
        assert r == 0

    def test_rango_inverso(self):
        r = PayrollService.calculate_business_days("2026-07-31", "2026-07-01")
        assert r == 0
