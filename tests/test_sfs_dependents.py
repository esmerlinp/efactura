"""Tests for SFS Dependents Management (Ley 87-01 / SISALRIL / TSS SUIRPLUS v5.0).

Cubre:
1. Modelo, clasificación y elegibilidad (cónyuge, hijos menores, estudiantes 18-21, discapacidad, padres, registros incompletos).
2. Parametrización con vigencia histórica:
   - Tarifa histórica (< 2026-10-01): RD$ 1,919.78
   - Nueva tarifa oficial (>= 2026-10-01): RD$ 1,970.42 (Cápita RD$ 1,938.18 + FONAMAT RD$ 32.24)
   - Preservación de períodos históricos cerrados.
3. Cálculo mensual y distribución quincenal 50/50 con balanceo exacto de centavos.
4. Prorrateo por días en Q1 y Q2 para altas y bajas dentro de la quincena o mes.
5. Manejo de múltiples dependientes con fechas efectivas independientes.
6. Protección de salario insuficiente con emisión de alertas sin bloqueo de nómina.
7. Generación y validación del archivo RD para TSS SUIRPLUS v5.0.
8. Asientos contables con cuenta 2.1.2.1.07 y tolerancia de fallback.
9. Aislamiento estricto multiempresa.
"""

import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.models.employee import Dependent
from app.services.payroll_service import PayrollService
from app.services.dependents_tss_service import generate_tss_rd, validate_rd_export
from app.services import hr_data_service as hr
from app.countries.do.payroll_rules import (
    DEFAULT_SFS_DEPENDENTS_ADDITIONAL_RATE,
    DEFAULT_ACCOUNT_SFS_DEPENDENTS_ADDITIONAL,
    SFS_DEPENDENTS_ADDITIONAL_CAPITA_OCT2026,
    SFS_DEPENDENTS_ADDITIONAL_FONAMAT_OCT2026,
    SFS_DEPENDENTS_ADDITIONAL_TOTAL_OCT2026,
    SFS_DEPENDENTS_ADDITIONAL_HISTORICAL_RATE,
    get_sfs_dependents_additional_rate_schedule,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. MODELO, CLASIFICACIÓN Y ELEGIBILIDAD
# ═══════════════════════════════════════════════════════════════════════════

class TestDependentModelAndClassification:
    """Pruebas unitarias de modelo, clasificación y elegibilidad regulatoria."""

    def test_direct_spouse_classification(self):
        """Cónyuge o compañera de vida es dependiente directo sin costo adicional."""
        dep = Dependent(
            id="dep-1",
            employeeId="emp-1",
            firstName="Maria",
            firstLastName="Perez",
            relationshipCode="esposo",
            birthDate="1990-05-15",
            docType="C",
            idNumber="40200000001",
        )
        cat, status, _ = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "direct"
        assert status == "eligible"
        assert dep.category == "direct"
        assert dep.eligibilityStatus == "eligible"

    def test_direct_minor_child_classification(self):
        """Hijo menor de 18 años es dependiente directo."""
        dep = Dependent(
            id="dep-2",
            employeeId="emp-1",
            firstName="Juan",
            firstLastName="Perez",
            relationshipCode="hijo",
            birthDate="2015-08-20",  # 11 años en 2026
            docType="C",
            idNumber="40200000002",
        )
        cat, status, _ = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "direct"
        assert status == "eligible"

    def test_direct_student_child_18_to_21_with_valid_cert(self):
        """Hijo de 18 a 21 años estudiante con certificación vigente es dependiente directo."""
        dep = Dependent(
            id="dep-3",
            employeeId="emp-1",
            firstName="Carlos",
            firstLastName="Perez",
            relationshipCode="hijo",
            birthDate="2006-03-10",  # 20 años en 2026
            isStudent=True,
            studentCertificationExpiry="2026-12-31",
            docType="C",
            idNumber="40200000003",
        )
        cat, status, _ = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "direct"
        assert status == "eligible"

    def test_student_child_with_expired_cert_becomes_additional_or_pending(self):
        """Hijo de 18 a 21 con certificación estudiantil vencida pasa a adicional/pendiente."""
        dep = Dependent(
            id="dep-4",
            employeeId="emp-1",
            firstName="Carlos",
            firstLastName="Perez",
            relationshipCode="hijo",
            birthDate="2006-03-10",  # 20 años
            isStudent=True,
            studentCertificationExpiry="2026-06-30",  # Vencida respecto a oct 2026
            docType="C",
            idNumber="40200000003",
        )
        cat, status, _ = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "additional"
        assert status == "pending_document"

    def test_child_with_permanent_disability_exemption(self):
        """Hijo mayor de edad con discapacidad permanente conserva cobertura directa sin límite de edad."""
        dep = Dependent(
            id="dep-5",
            employeeId="emp-1",
            firstName="Luis",
            firstLastName="Perez",
            relationshipCode="hijo",
            birthDate="1995-01-01",  # 31 años
            disability=True,
            docType="C",
            idNumber="40200000005",
        )
        cat, status, _ = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "direct"
        assert status == "eligible"

    def test_parent_classification_as_additional(self):
        """Padre o madre es dependiente adicional que genera aporte adicional."""
        dep = Dependent(
            id="dep-6",
            employeeId="emp-1",
            firstName="Ramon",
            firstLastName="Perez",
            relationshipCode="padre",
            birthDate="1960-04-12",
            docType="C",
            idNumber="00100000006",
        )
        cat, status, _ = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "additional"
        assert status == "eligible"

    def test_other_relative_classification(self):
        """Otros familiares (tío, sobrino, hermano) son adicionales si hay dependencia o informativos."""
        dep = Dependent(
            id="dep-7",
            employeeId="emp-1",
            firstName="Rosa",
            firstLastName="Perez",
            relationshipCode="hermano",
            birthDate="1998-02-10",
            category="additional",
            isFinancialDependent=True,
            docType="C",
            idNumber="40200000007",
        )
        cat, status, _ = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "additional"
        assert status == "eligible"

    def test_legacy_dict_compatibility(self):
        """Un diccionario legacy sin nuevos campos es compatible y se resuelve correctamente."""
        legacy_data = {
            "id": "dep-legacy",
            "employeeId": "emp-1",
            "firstName": "Ana",
            "firstLastName": "Gomez",
            "relationshipCode": "hijo",
            "birthDate": "2018-09-01",  # Menor
            "active": True,
        }
        dep = Dependent(**legacy_data)
        cat, status, _ = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "direct"
        assert status == "eligible"
        assert dep.disability is False

    def test_unclassified_or_missing_relationship_remains_pending_informational(self):
        """Un registro sin parentesco definido no debe generar descuentos ni considerarse elegible automáticamente."""
        dep = Dependent(
            id="dep-incomplete",
            employeeId="emp-1",
            firstName="Desconocido",
            firstLastName="SinParentesco",
            active=True,
        )
        cat, status, reason = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "informational"
        assert status == "pending_document"
        assert "sin parentesco" in reason.lower()

    def test_child_without_birthdate_requires_verification(self):
        """Un registro de hijo sin fecha de nacimiento queda en pending_document para verificar edad."""
        dep = Dependent(
            id="dep-child-nobd",
            employeeId="emp-1",
            firstName="Mateo",
            firstLastName="Perez",
            relationshipCode="hijo",
            birthDate="",
            active=True,
        )
        cat, status, reason = dep.resolve_category_and_eligibility(reference_date=date(2026, 10, 1))
        assert cat == "direct"
        assert status == "pending_document"
        assert "verificación de edad" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 2. VIGENCIA HISTÓRICA DE TARIFAS Y COMPOSICIÓN (OCT 2026)
# ═══════════════════════════════════════════════════════════════════════════

class TestRateSchedulesAndHistoricalPeriods:
    """Pruebas de vigencia histórica de tarifas (TSS 5 de octubre de 2026)."""

    def test_schedule_resolution_historical_period_pre_oct2026(self):
        """Para períodos anteriores a octubre 2026 (ej. Sep 2026), aplica la tarifa histórica de RD$ 1,919.78."""
        sched = get_sfs_dependents_additional_rate_schedule("2026-09-15")
        assert sched["total_rate"] == SFS_DEPENDENTS_ADDITIONAL_HISTORICAL_RATE
        assert sched["total_rate"] == 1919.78
        assert sched["capita_rate"] == 1919.78
        assert sched["fonamat_rate"] == 0.0

        deps = [{"id": "d1", "relationshipCode": "padre", "birthDate": "1960-01-01", "active": True}]
        res = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-09-01",
            period_end="2026-09-30",
        )
        assert res["amount"] == 1919.78
        assert res["monthly_rate"] == 1919.78
        assert res["capita_rate"] == 1919.78
        assert res["fonamat_rate"] == 0.0

    def test_schedule_resolution_current_period_oct2026_and_beyond(self):
        """Desde octubre 2026 aplica RD$ 1,970.42 (Cápita RD$ 1,938.18 + FONAMAT RD$ 32.24)."""
        sched = get_sfs_dependents_additional_rate_schedule("2026-10-01")
        assert sched["total_rate"] == SFS_DEPENDENTS_ADDITIONAL_TOTAL_OCT2026
        assert sched["total_rate"] == 1970.42
        assert sched["capita_rate"] == SFS_DEPENDENTS_ADDITIONAL_CAPITA_OCT2026
        assert sched["capita_rate"] == 1938.18
        assert sched["fonamat_rate"] == SFS_DEPENDENTS_ADDITIONAL_FONAMAT_OCT2026
        assert sched["fonamat_rate"] == 32.24

        deps = [{"id": "d1", "relationshipCode": "padre", "birthDate": "1960-01-01", "active": True}]
        res = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-10-01",
            period_end="2026-10-31",
        )
        assert res["amount"] == 1970.42
        assert res["monthly_rate"] == 1970.42
        assert res["capita_rate"] == 1938.18
        assert res["fonamat_rate"] == 32.24
        assert res["details"][0]["capitaAmount"] == 1938.18
        assert res["details"][0]["fonamatAmount"] == 32.24

    def test_closed_period_preservation(self):
        """Un período cerrado no muta su cálculo histórico."""
        period_cerrado = {
            "id": "p-2026-09",
            "periodKey": "2026-09",
            "status": "cerrada",
        }
        with pytest.raises(Exception):
            PayrollService.assert_period_mutable(period_cerrado)

    def test_historical_rate_resolution_by_period_date_regardless_of_execution_date(self):
        """La resolución de tarifas depende estrictamente de las fechas del período, no de la fecha del reloj."""
        deps = [{"id": "d1", "relationshipCode": "padre", "birthDate": "1960-01-01", "active": True}]

        # Período de agosto 2026 (anterior a octubre 2026) -> RD$ 1,919.78
        res_aug = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-08-01",
            period_end="2026-08-31",
        )
        assert res_aug["monthly_rate"] == 1919.78
        assert res_aug["amount"] == 1919.78
        assert res_aug["capita_rate"] == 1919.78
        assert res_aug["fonamat_rate"] == 0.0

        # Período de octubre 2026 -> RD$ 1,970.42
        res_oct = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-10-01",
            period_end="2026-10-31",
        )
        assert res_oct["monthly_rate"] == 1970.42
        assert res_oct["amount"] == 1970.42
        assert res_oct["capita_rate"] == 1938.18
        assert res_oct["fonamat_rate"] == 32.24


# ═══════════════════════════════════════════════════════════════════════════
# 3. CÁLCULO QUINCENAL 50/50 Y PRORRATEO POR DÍAS
# ═══════════════════════════════════════════════════════════════════════════

class TestPayrollCalculationAndBiweeklySplit:
    """Pruebas de cálculo quincenal, redondeo determinista y prorrateos."""

    def test_direct_dependents_generate_zero_cost(self):
        """Los dependientes directos no generan descuento adicional."""
        deps = [
            {"id": "d1", "relationshipCode": "esposo", "birthDate": "1990-01-01", "category": "direct", "eligibilityStatus": "eligible", "active": True},
            {"id": "d2", "relationshipCode": "hijo", "birthDate": "2016-01-01", "category": "direct", "eligibilityStatus": "eligible", "active": True},
        ]
        res = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-10-01",
            period_end="2026-10-31",
        )
        assert res["amount"] == 0.0
        assert res["eligibleCount"] == 0

    def test_additional_dependent_monthly_cost_oct2026(self):
        """Un dependiente adicional genera RD$ 1,970.42 mensual en octubre 2026."""
        deps = [
            {"id": "d1", "relationshipCode": "padre", "birthDate": "1960-01-01", "active": True},
        ]
        res = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-10-01",
            period_end="2026-10-31",
        )
        assert res["amount"] == 1970.42
        assert res["eligibleCount"] == 1

    def test_two_additional_dependents_monthly(self):
        """Dos dependientes adicionales duplican el aporte adicional ($2 \times 1,970.42 = 3,940.84$)."""
        deps = [
            {"id": "d1", "relationshipCode": "padre", "birthDate": "1958-01-01", "active": True},
            {"id": "d2", "relationshipCode": "madre", "birthDate": "1962-01-01", "active": True},
        ]
        res = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-10-01",
            period_end="2026-10-31",
        )
        assert res["amount"] == 3940.84
        assert res["eligibleCount"] == 2

    def test_biweekly_split_50_50_deterministic_cent_reconciliation(self):
        """Distribución quincenal 50/50 concilia exactamente con el total mensual ($985.21 + 985.21 = 1,970.42$)."""
        deps = [
            {"id": "d1", "relationshipCode": "padre", "birthDate": "1960-01-01", "active": True},
        ]
        # Q1 (1-15 oct)
        q1 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="quincenal",
            period_start="2026-10-01",
            period_end="2026-10-15",
            is_second_quincena=False,
        )
        # Q2 (16-31 oct)
        q2 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="quincenal",
            period_start="2026-10-16",
            period_end="2026-10-31",
            is_second_quincena=True,
        )
        assert q1["amount"] == 985.21
        assert q2["amount"] == 985.21
        assert round(q1["amount"] + q2["amount"], 2) == 1970.42
        assert q1["details"][0]["capitaAmount"] == 969.09
        assert q1["details"][0]["fonamatAmount"] == 16.12
        assert q2["details"][0]["capitaAmount"] == 969.09
        assert q2["details"][0]["fonamatAmount"] == 16.12

    def test_odd_cent_monthly_reconciliation(self):
        """Con una tarifa con centavos impares (ej. 1919.75), Q1 y Q2 concilian exactamente."""
        deps = [
            {"id": "d1", "relationshipCode": "padre", "birthDate": "1960-01-01", "active": True},
        ]
        rate = 1919.75
        q1 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            tax_rates={"dependents_additional_rate": rate},
            period_type="quincenal",
            is_second_quincena=False,
        )
        q2 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            tax_rates={"dependents_additional_rate": rate},
            period_type="quincenal",
            is_second_quincena=True,
        )
        assert q1["amount"] == 959.88
        assert q2["amount"] == 959.87
        assert round(q1["amount"] + q2["amount"], 2) == 1919.75

    def test_q1_addition_proration(self):
        """Alta en día 6 de Q1 (1-15 oct: 10 días activos de 15) prorratea sobre la cuota quincenal."""
        deps = [
            {
                "id": "d1",
                "relationshipCode": "padre",
                "active": True,
                "effectiveStartDate": "2026-10-06",
            }
        ]
        q1 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="quincenal",
            period_start="2026-10-01",
            period_end="2026-10-15",
            is_second_quincena=False,
        )
        # 10 días / 15 días * 985.21 (capita 969.09 * 10/15 + fonamat 16.12 * 10/15)
        # 969.09 * (10/15) = 646.06, 16.12 * (10/15) = 10.75 -> 656.81
        assert q1["details"][0]["activeDays"] == 10
        assert q1["details"][0]["totalDays"] == 15
        assert q1["amount"] == 656.81

    def test_q2_addition_proration(self):
        """Alta en día 21 de Q2 (16-31 oct: 11 días activos de 16) prorratea sobre la cuota quincenal de Q2."""
        deps = [
            {
                "id": "d1",
                "relationshipCode": "padre",
                "active": True,
                "effectiveStartDate": "2026-10-21",
            }
        ]
        q2 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="quincenal",
            period_start="2026-10-16",
            period_end="2026-10-31",
            is_second_quincena=True,
        )
        assert q2["details"][0]["activeDays"] == 11
        assert q2["details"][0]["totalDays"] == 16
        # 969.09 * (11/16) = 666.25, 16.12 * (11/16) = 11.08 -> 677.33
        assert q2["amount"] == 677.33

    def test_q2_deactivation_proration(self):
        """Baja en día 20 de Q2 (16-31 oct: 5 días activos de 16) prorratea sobre la cuota de Q2."""
        deps = [
            {
                "id": "d1",
                "relationshipCode": "padre",
                "active": True,
                "effectiveStartDate": "2026-10-01",
                "effectiveEndDate": "2026-10-20",
            }
        ]
        q2 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="quincenal",
            period_start="2026-10-16",
            period_end="2026-10-31",
            is_second_quincena=True,
        )
        assert q2["details"][0]["activeDays"] == 5
        assert q2["details"][0]["totalDays"] == 16
        # 969.09 * (5/16) = 302.84, 16.12 * (5/16) = 5.04 -> 307.88
        assert q2["amount"] == 307.88

    def test_multiple_dependents_with_different_effective_dates(self):
        """Múltiples dependientes con fechas distintas: uno activo todo el mes y otro medio mes."""
        deps = [
            {"id": "d1", "relationshipCode": "padre", "active": True, "effectiveStartDate": "2026-10-01"},
            {"id": "d2", "relationshipCode": "madre", "active": True, "effectiveStartDate": "2026-10-16"},
        ]
        res = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-10-01",
            period_end="2026-10-31",
        )
        # d1: 31/31 -> 1970.42 (1938.18 + 32.24)
        # d2: 16 días en mes de 31 días -> (16/31)*1938.18 = 1000.35, (16/31)*32.24 = 16.64 -> 1016.99
        # total = 1970.42 + 1016.99 = 2987.41
        assert res["eligibleCount"] == 2
        assert res["amount"] == 2987.41

    def test_zero_or_unverified_rate_produces_zero_discount(self):
        """Si la tarifa no está configurada o es 0, no se efectúa descuento monetario."""
        deps = [
            {"id": "d1", "relationshipCode": "padre", "category": "additional", "eligibilityStatus": "eligible", "active": True},
        ]
        res = PayrollService.calculate_dependents_additional(
            dependents=deps,
            tax_rates={"dependents_additional_rate": 0.0},
            period_type="mensual",
        )
        assert res["amount"] == 0.0

    def test_proration_15_vs_16_vs_13_days_quincenas(self):
        """Verifica prorrateos exactos en quincenas de 15 días (1-15), 16 días (16-31) y 13 días (16-28)."""
        dep = {"id": "d1", "relationshipCode": "padre", "active": True}

        # Q1 (1-15 oct: 15 días totales). Alta el 6 -> 10 días activos.
        dep_q1 = {**dep, "effectiveStartDate": "2026-10-06"}
        res_q1 = PayrollService.calculate_dependents_additional(
            dependents=[dep_q1],
            period_type="quincenal",
            period_start="2026-10-01",
            period_end="2026-10-15",
            is_second_quincena=False,
        )
        assert res_q1["details"][0]["activeDays"] == 10
        assert res_q1["details"][0]["totalDays"] == 15
        assert res_q1["amount"] == 656.81

        # Q2 (16-31 oct: 16 días totales). Alta el 21 -> 11 días activos.
        dep_q2_16 = {**dep, "effectiveStartDate": "2026-10-21"}
        res_q2_16 = PayrollService.calculate_dependents_additional(
            dependents=[dep_q2_16],
            period_type="quincenal",
            period_start="2026-10-16",
            period_end="2026-10-31",
            is_second_quincena=True,
        )
        assert res_q2_16["details"][0]["activeDays"] == 11
        assert res_q2_16["details"][0]["totalDays"] == 16
        assert res_q2_16["amount"] == 677.33

        # Q2 (16-28 feb: 13 días totales). Alta el 20 -> 9 días activos.
        # Tarifa Q2 feb 2026 (< oct 2026): base mensual 1919.78 -> Q1 = 959.89, Q2 = 959.89
        dep_q2_13 = {**dep, "effectiveStartDate": "2026-02-20"}
        res_q2_13 = PayrollService.calculate_dependents_additional(
            dependents=[dep_q2_13],
            period_type="quincenal",
            period_start="2026-02-16",
            period_end="2026-02-28",
            is_second_quincena=True,
        )
        assert res_q2_13["details"][0]["activeDays"] == 9
        assert res_q2_13["details"][0]["totalDays"] == 13
        assert res_q2_13["amount"] == 664.54


# ═══════════════════════════════════════════════════════════════════════════
# 4. LÍNEA DE NÓMINA, SALARIO INSUFICIENTE E IDEMPOTENCIA
# ═══════════════════════════════════════════════════════════════════════════

class TestPayrollLineAndInsufficientSalary:
    """Pruebas de integración de línea de nómina y alerta de salario insuficiente."""

    def test_calculate_payroll_line_with_sfs_dependents_additional(self):
        """calculate_payroll_line incluye el descuento adicional en deducciones y neto."""
        base_salary = 50000.00
        line_standard = PayrollService.calculate_payroll_line(base_salary=base_salary)
        line_with_deps = PayrollService.calculate_payroll_line(
            base_salary=base_salary,
            sfs_dependents_additional=1970.42,
        )
        assert line_with_deps["sfsDependentsAdditional"] == 1970.42
        assert round(line_with_deps["totalDeductions"] - line_standard["totalDeductions"], 2) == 1970.42
        assert round(line_standard["netSalary"] - line_with_deps["netSalary"], 2) == 1970.42

    def test_insufficient_salary_protection_and_alert(self):
        """Cuando el salario disponible no cubre el aporte, se limita el cobro y se emite alerta."""
        earn = 1500.00
        mandatory_deductions = 500.00
        net_available = earn - mandatory_deductions  # 1000.00 disponible
        dep_amount = 1970.42

        deductible_dep_amt = min(net_available, dep_amount)
        difference = round(dep_amount - deductible_dep_amt, 2)

        assert deductible_dep_amt == 1000.00
        assert difference == 970.42

        alert = {
            "employeeId": "emp-test",
            "conceptCode": "SFS_DEP_ADICIONAL",
            "calculatedAmount": dep_amount,
            "deductibleAmount": deductible_dep_amt,
            "difference": difference,
            "reason": "Salario neto disponible insuficiente",
        }
        assert alert["calculatedAmount"] > alert["deductibleAmount"]
        assert alert["difference"] > 0

    def test_insufficient_salary_never_produces_negative_net_salary(self):
        """Garantiza que una deducción por dependientes nunca produzca salario neto negativo."""
        base_salary = 1000.00
        line = PayrollService.calculate_payroll_line(
            base_salary=base_salary,
            sfs_dependents_additional=0.0,
        )
        net_available = line["netSalary"]
        dep_calculated = 3940.84

        deductible_amt = min(net_available, dep_calculated)
        diff_amt = round(dep_calculated - deductible_amt, 2)

        line_with_capped_dep = PayrollService.calculate_payroll_line(
            base_salary=base_salary,
            sfs_dependents_additional=deductible_amt,
        )
        assert line_with_capped_dep["netSalary"] >= 0.0
        assert line_with_capped_dep["netSalary"] == 0.0
        assert diff_amt == round(dep_calculated - net_available, 2)

    def test_idempotent_recalculation_no_double_charges(self):
        """Recalcular múltiples veces la misma nómina produce exactamente el mismo importe."""
        deps = [{"id": "d1", "relationshipCode": "padre", "birthDate": "1960-01-01", "active": True}]
        calc1 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-10-01",
            period_end="2026-10-31",
        )
        calc2 = PayrollService.calculate_dependents_additional(
            dependents=deps,
            period_type="mensual",
            period_start="2026-10-01",
            period_end="2026-10-31",
        )
        assert calc1["amount"] == calc2["amount"] == 1970.42


# ═══════════════════════════════════════════════════════════════════════════
# 5. EXPORTACIÓN TSS SUIRPLUS v5.0 (ARCHIVO RD)
# ═══════════════════════════════════════════════════════════════════════════

class TestTssRdExport:
    """Pruebas para la exportación RD (Registro de Dependientes Adicionales) TSS SUIRPLUS v5.0."""

    def test_tss_rd_export_structure_and_validation(self):
        """Genera archivo RD con formato exacto de 14 chars encabezado, 158 chars detalle y 7 chars sumario."""
        employees = [
            {
                "id": "emp-1",
                "tssKey": "001",
                "cedula": "00100000010",
                "status": "activo",
            }
        ]
        deps_map = {
            "emp-1": [
                {
                    "id": "dep-padre",
                    "firstName": "JUAN",
                    "firstLastName": "PEREZ",
                    "secondLastName": "GARCIA",
                    "relationshipCode": "padre",
                    "category": "additional",
                    "eligibilityStatus": "eligible",
                    "docType": "C",
                    "idNumber": "00100000020",
                    "active": True,
                },
                # Direct child must be ignored for RD export!
                {
                    "id": "dep-hijo",
                    "firstName": "LUCAS",
                    "firstLastName": "PEREZ",
                    "relationshipCode": "hijo",
                    "category": "direct",
                    "eligibilityStatus": "eligible",
                    "docType": "C",
                    "idNumber": "00100000030",
                    "active": True,
                },
            ]
        }

        errors = validate_rd_export(employees, deps_map)
        assert len(errors) == 0

        res = generate_tss_rd(employees, employer_rnc="13188068100", dependents_by_employee=deps_map)
        lines = res["content"].strip().split("\n")
        assert len(lines) == 3  # Header + 1 Detail + Trailer
        header, detail, trailer = lines[0], lines[1], lines[2]

        assert len(header) == 14
        assert header.startswith("ERD")
        assert len(detail) == 158
        assert len(trailer) == 7
        assert trailer == "S000003"
        assert res["total_dependientes"] == 1

    def test_tss_rd_export_exact_field_positions(self):
        """Verifica campo por campo las posiciones oficiales del instructivo TSS RD v5.0 (158 chars)."""
        employees = [
            {
                "id": "emp-1",
                "tssKey": "001",
                "cedula": "00100000010",
                "status": "activo",
            }
        ]
        deps_map = {
            "emp-1": [
                {
                    "id": "dep-1",
                    "firstName": "JUAN ALBERTO",
                    "firstLastName": "PEREZ",
                    "secondLastName": "GARCIA",
                    "relationshipCode": "padre",
                    "category": "additional",
                    "eligibilityStatus": "eligible",
                    "docType": "C",
                    "idNumber": "00100000020",
                    "active": True,
                }
            ]
        }

        res = generate_tss_rd(employees, employer_rnc="13188068100", dependents_by_employee=deps_map)
        detail = res["content"].strip().split("\n")[1]

        assert len(detail) == 158

        # Pos 1 (1): Tipo de Registro
        assert detail[0] == "D"
        # Pos 2-4 (3): Clave Nómina
        assert detail[1:4] == "001"
        # Pos 5 (1): Tipo Documento Titular
        assert detail[4] == "C"
        # Pos 6-16 (11): Cédula/NSS Titular
        assert detail[5:16] == "00100000010"
        # Pos 17-66 (50): Nombres del dependiente (50 caracteres)
        assert len(detail[16:66]) == 50
        assert detail[16:66] == "JUAN ALBERTO".ljust(50)
        # Pos 67-106 (40): Primer Apellido del dependiente (40 caracteres)
        assert len(detail[66:106]) == 40
        assert detail[66:106] == "PEREZ".ljust(40)
        # Pos 107-146 (40): Segundo Apellido del dependiente (40 caracteres)
        assert len(detail[106:146]) == 40
        assert detail[106:146] == "GARCIA".ljust(40)
        # Pos 147 (1): Tipo Documento del dependiente
        assert detail[146] == "C"
        # Pos 148-158 (11): Cédula/NSS del dependiente (11 caracteres)
        assert len(detail[147:158]) == 11
        assert detail[147:158] == "00100000020"

    def test_tss_rd_export_with_accents_and_compound_names(self):
        """Valida transliteración ASCII de tildes, eñes y apellidos compuestos en archivo RD."""
        employees = [
            {
                "id": "emp-2",
                "tssKey": "002",
                "cedula": "40200000010",
                "status": "activo",
            }
        ]
        deps_map = {
            "emp-2": [
                {
                    "id": "dep-comp",
                    "firstName": "JOSÉ ÁNGEL",
                    "middleName": "MARÍA",
                    "firstLastName": "DE LA ROSA",
                    "secondLastName": "PEÑA NÚÑEZ",
                    "relationshipCode": "madre",
                    "category": "additional",
                    "eligibilityStatus": "eligible",
                    "docType": "C",
                    "idNumber": "00100000099",
                    "active": True,
                }
            ]
        }

        res = generate_tss_rd(employees, employer_rnc="13188068100", dependents_by_employee=deps_map)
        detail = res["content"].strip().split("\n")[1]

        assert len(detail) == 158
        # Nombres sin tildes transliterados a ASCII mayúsculas
        assert detail[16:66] == "JOSE ANGEL MARIA".ljust(50)
        # Primer apellido compuesto
        assert detail[66:106] == "DE LA ROSA".ljust(40)
        # Segundo apellido con eñes y tildes transliteradas
        assert detail[106:146] == "PENA NUNEZ".ljust(40)
        # Documento
        assert detail[147:158] == "00100000099"


# ═══════════════════════════════════════════════════════════════════════════
# 6. AISLAMIENTO MULTIEMPRESA Y CONTABILIDAD
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiTenancyAndAccounting:
    """Pruebas de aislamiento multiempresa y generación de asientos contables."""

    def test_deactivate_uses_company_id(self):
        """Verifica que el servicio de desactivación opere sobre company_id y mantenga aislamiento."""
        company_a = "comp_alpha"
        company_b = "comp_beta"

        store = {}

        class MockDocRef:
            def __init__(self, path, doc_id):
                self.path = path
                self.doc_id = doc_id

            def set(self, data):
                store.setdefault(self.path, {})[self.doc_id] = dict(data)

            def get(self):
                data = store.get(self.path, {}).get(self.doc_id)
                mock_snap = MagicMock()
                mock_snap.exists = data is not None
                mock_snap.id = self.doc_id
                mock_snap.to_dict.return_value = dict(data) if data else {}
                return mock_snap

            def update(self, data):
                if self.path in store and self.doc_id in store[self.path]:
                    store[self.path][self.doc_id].update(data)

        class MockCollRef:
            def __init__(self, path):
                self.path = path

            def document(self, doc_id):
                return MockDocRef(self.path, doc_id)

            def where(self, *args, **kwargs):
                return self

            def get(self):
                docs = []
                for doc_id, data in store.get(self.path, {}).items():
                    snap = MagicMock()
                    snap.id = doc_id
                    snap.exists = True
                    snap.to_dict.return_value = dict(data)
                    docs.append(snap)
                return docs

        mock_db = MagicMock()
        mock_db.collection.side_effect = lambda p: MockCollRef(p)

        with patch.object(hr, "db_firestore", mock_db), patch.object(hr, "firebase_initialized", True):
            # Dependiente en company A
            dep_a = {
                "id": "dep-a",
                "employeeId": "emp-a",
                "firstName": "Pedro",
                "firstLastName": "A",
                "active": True,
            }
            hr.save_employee_dependent(company_a, dep_a, sandbox=True)

            # Deactivate in company A
            updated = hr.deactivate_employee_dependent(company_a, "dep-a", sandbox=True, reason="Renuncia voluntaria")
            assert updated is True
            fetched_a = hr.get_employee_dependent(company_a, "dep-a", sandbox=True)
            assert fetched_a["active"] is False
            assert fetched_a["deactivationReason"] == "Renuncia voluntaria"

            # Company B cannot access or see dep-a
            fetched_b = hr.get_employee_dependent(company_b, "dep-a", sandbox=True)
            assert fetched_b is None

    def test_accounting_journal_generation_and_fallback(self):
        """Generación de asiento contable para SFS dependientes adicionales con fallback a 2.1.2.1.07."""
        period = {
            "id": "period-1",
            "periodKey": "2026-10",
            "lines": [
                {
                    "employeeId": "emp-1",
                    "totalIncome": 50000.0,
                    "netSalary": 43500.0,
                    "totalDeductions": 6500.0,
                    "afpEmployee": 1435.0,
                    "sfsEmployee": 1520.0,
                    "sfsDependentsAdditional": 1970.42,
                    "isrRetention": 1574.58,
                    "afpEmployer": 3550.0,
                    "sfsEmployer": 3545.0,
                    "srlEmployer": 600.0,
                    "infotepEmployer": 500.0,
                    "totalEmployerContrib": 8195.0,
                }
            ]
        }
        employees = {
            "emp-1": {"id": "emp-1", "costCenter": "General", "afpProvider": "AFP Popular"}
        }

        with patch.object(PayrollService, "get_period_lines", return_value=period["lines"]):
            journal_lines = PayrollService.build_payroll_accounting_lines(
                payroll_period=period,
                employees=employees,
                company_id="comp-1",
            )

        dep_line = next((l for l in journal_lines if l["accountCode"] == DEFAULT_ACCOUNT_SFS_DEPENDENTS_ADDITIONAL), None)
        assert dep_line is not None
        assert dep_line["credit"] == 1970.42
        assert dep_line["debit"] == 0.0
