"""Tests unitarios para LiquidacionService — Cálculo de Prestaciones Laborales RD."""

import pytest
from datetime import date, timedelta
from app.services.liquidacion_service import LiquidacionService


def _d(days_ago: int) -> str:
    """Helper: fecha como string YYYY-MM-DD desde hoy menos N días."""
    d = date.today() - timedelta(days=days_ago)
    return d.strftime("%Y-%m-%d")


def _today() -> str:
    return date.today().strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════════════════
# SALARIO DIARIO PROMEDIO (SDP)
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcularSDP:
    def test_sdp_mensual_fijo(self):
        sdp = LiquidacionService.calcular_sdp([45000.0], "mensual")
        assert round(sdp, 2) == round(45000.0 / 23.83, 2)

    def test_sdp_mensual_promedio_12_meses(self):
        salaries = [45000.0] * 12
        sdp = LiquidacionService.calcular_sdp(salaries, "mensual")
        assert round(sdp, 2) == round(45000.0 / 23.83, 2)

    def test_sdp_mensual_con_variables(self):
        salaries = [45000.0, 45000.0, 48000.0, 45000.0, 45000.0,
                    45000.0, 50000.0, 45000.0, 45000.0, 45000.0,
                    45000.0, 45000.0]
        sdp = LiquidacionService.calcular_sdp(salaries, "mensual")
        expected_prom = sum(salaries) / 12 / 23.83
        assert round(sdp, 4) == round(expected_prom, 4)

    def test_sdp_quincenal(self):
        sdp = LiquidacionService.calcular_sdp([22500.0], "quincenal")
        assert round(sdp, 2) == round(22500.0 / 11.91, 2)

    def test_sdp_semanal(self):
        sdp = LiquidacionService.calcular_sdp([10500.0], "semanal")
        assert round(sdp, 2) == round(10500.0 / 5.5, 2)

    def test_sdp_diario(self):
        sdp = LiquidacionService.calcular_sdp([1500.0], "diario")
        assert sdp == 1500.0

    def test_sdp_lista_vacia(self):
        sdp = LiquidacionService.calcular_sdp([], "mensual")
        assert sdp == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# ANTIGÜEDAD
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcularAntiguedad:
    def test_3_anios_exactos(self):
        hire = "2023-03-15"
        term = "2026-03-15"
        a = LiquidacionService.calcular_antiguedad(hire, term)
        assert a["years"] == 3
        assert a["months"] == 0
        assert a["total_months"] == 36

    def test_3_anios_4_meses(self):
        hire = "2023-03-15"
        term = "2026-07-15"
        a = LiquidacionService.calcular_antiguedad(hire, term)
        assert a["years"] == 3
        assert a["months"] == 4
        assert a["total_months"] == 40

    def test_menos_de_3_meses(self):
        hire = "2026-05-01"
        term = "2026-07-01"
        a = LiquidacionService.calcular_antiguedad(hire, term)
        assert a["total_months"] == 2

    def test_5_meses(self):
        hire = "2026-02-01"
        term = "2026-07-01"
        a = LiquidacionService.calcular_antiguedad(hire, term)
        assert a["total_months"] == 5

    def test_11_meses(self):
        hire = "2025-08-01"
        term = "2026-07-01"
        a = LiquidacionService.calcular_antiguedad(hire, term)
        assert a["total_months"] == 11

    def test_7_anios(self):
        hire = "2019-07-01"
        term = "2026-07-01"
        a = LiquidacionService.calcular_antiguedad(hire, term)
        assert a["years"] == 7


# ═══════════════════════════════════════════════════════════════════════════
# PREAVISO (Art. 76)
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcularPreaviso:
    SDP = 1888.38  # 45000 / 23.83

    def test_menos_de_3_meses_no_aplica(self):
        ant = {"years": 0, "months": 2, "days": 0, "total_months": 2}
        r = LiquidacionService.calcular_preaviso(ant, self.SDP)
        assert r["dias"] == 0
        assert r["monto"] == 0.0

    def test_3_a_6_meses(self):
        ant = {"years": 0, "months": 5, "days": 0, "total_months": 5}
        r = LiquidacionService.calcular_preaviso(ant, self.SDP)
        assert r["dias"] == 7
        assert r["monto"] == round(7 * self.SDP, 2)

    def test_6_a_12_meses(self):
        ant = {"years": 0, "months": 8, "days": 0, "total_months": 8}
        r = LiquidacionService.calcular_preaviso(ant, self.SDP)
        assert r["dias"] == 14
        assert r["monto"] == round(14 * self.SDP, 2)

    def test_mas_de_1_anio(self):
        ant = {"years": 3, "months": 0, "days": 0, "total_months": 36}
        r = LiquidacionService.calcular_preaviso(ant, self.SDP)
        assert r["dias"] == 28
        assert r["monto"] == round(28 * self.SDP, 2)

    def test_preaviso_trabajado_monto_cero(self):
        ant = {"years": 3, "months": 0, "days": 0, "total_months": 36}
        r = LiquidacionService.calcular_preaviso(ant, self.SDP, preaviso_trabajado=True)
        assert r["dias"] == 0
        assert r["monto"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# CESANTÍA (Art. 80)
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcularCesantia:
    SDP = 1888.38

    def test_menos_de_3_meses(self):
        ant = {"years": 0, "months": 2, "days": 0, "total_months": 2}
        r = LiquidacionService.calcular_cesantia(ant, self.SDP)
        assert r["dias"] == 0
        assert r["monto"] == 0.0

    def test_3_a_6_meses(self):
        ant = {"years": 0, "months": 5, "days": 0, "total_months": 5}
        r = LiquidacionService.calcular_cesantia(ant, self.SDP)
        assert r["dias"] == 6
        assert r["monto"] == round(6 * self.SDP, 2)

    def test_6_a_12_meses(self):
        ant = {"years": 0, "months": 8, "days": 0, "total_months": 8}
        r = LiquidacionService.calcular_cesantia(ant, self.SDP)
        assert r["dias"] == 13
        assert r["monto"] == round(13 * self.SDP, 2)

    def test_3_anios_exactos(self):
        ant = {"years": 3, "months": 0, "days": 0, "total_months": 36}
        r = LiquidacionService.calcular_cesantia(ant, self.SDP)
        assert r["dias"] == 3 * 21  # 63
        assert r["monto"] == round(63 * self.SDP, 2)

    def test_3_anios_4_meses(self):
        ant = {"years": 3, "months": 4, "days": 0, "total_months": 40}
        r = LiquidacionService.calcular_cesantia(ant, self.SDP)
        assert r["dias"] == 3 * 21 + 6  # 69
        assert r["monto"] == round(69 * self.SDP, 2)

    def test_3_anios_7_meses(self):
        ant = {"years": 3, "months": 7, "days": 0, "total_months": 43}
        r = LiquidacionService.calcular_cesantia(ant, self.SDP)
        assert r["dias"] == 3 * 21 + 13  # 76
        assert r["monto"] == round(76 * self.SDP, 2)

    def test_7_anios(self):
        ant = {"years": 7, "months": 0, "days": 0, "total_months": 84}
        r = LiquidacionService.calcular_cesantia(ant, self.SDP)
        expected = 5 * 21 + 2 * 23  # 105 + 46 = 151
        assert r["dias"] == expected
        assert r["monto"] == round(expected * self.SDP, 2)

    def test_7_anios_5_meses(self):
        ant = {"years": 7, "months": 5, "days": 0, "total_months": 89}
        r = LiquidacionService.calcular_cesantia(ant, self.SDP)
        expected = 5 * 21 + 2 * 23 + 6  # 105 + 46 + 6 = 157
        assert r["dias"] == expected


# ═══════════════════════════════════════════════════════════════════════════
# VACACIONES (Art. 177/182)
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcularVacaciones:
    SDP = 1888.38

    def test_sin_vacaciones_pendientes_menos_5_meses(self):
        ant = {"years": 0, "months": 4, "days": 0, "total_months": 4}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, 0, 0)
        assert r["dias"] == 0
        assert r["monto"] == 0.0

    def test_6_meses_proporcional(self):
        ant = {"years": 0, "months": 6, "days": 0, "total_months": 6}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, 0, 0)
        assert r["dias"] == 7
        assert r["monto"] == round(7 * self.SDP, 2)

    def test_11_meses_proporcional(self):
        ant = {"years": 0, "months": 11, "days": 0, "total_months": 11}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, 0, 0)
        assert r["dias"] == 12
        assert r["monto"] == round(12 * self.SDP, 2)

    def test_3_anios_14_dias_base(self):
        ant = {"years": 3, "months": 0, "days": 0, "total_months": 36}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, 0, 0)
        assert r["dias"] == 14  # período completo, 1-5 años
        assert r["monto"] == round(14 * self.SDP, 2)

    def test_7_anios_18_dias_base(self):
        ant = {"years": 7, "months": 0, "days": 0, "total_months": 84}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, 0, 0)
        assert r["dias"] == 18  # período completo, >5 años
        assert r["monto"] == round(18 * self.SDP, 2)

    def test_con_pendientes_anteriores(self):
        ant = {"years": 3, "months": 0, "days": 0, "total_months": 36}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, pending_days=14, days_taken_this_period=0)
        assert r["dias"] == 14 + 14  # 14 del año actual + 14 pendientes = 28
        assert r["monto"] == round(28 * self.SDP, 2)

    def test_restando_dias_tomados(self):
        ant = {"years": 3, "months": 0, "days": 0, "total_months": 36}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, pending_days=0, days_taken_this_period=7)
        assert r["dias"] == 14 - 7  # 7 restantes
        assert r["monto"] == round(7 * self.SDP, 2)

    def test_3_meses_proporcional_en_segundo_anio(self):
        ant = {"years": 2, "months": 3, "days": 0, "total_months": 27}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, 0, 0)
        assert r["dias"] == 0  # menos de 5 meses del período actual

    def test_7_meses_proporcional_en_segundo_anio(self):
        ant = {"years": 2, "months": 7, "days": 0, "total_months": 31}
        r = LiquidacionService.calcular_vacaciones(ant, self.SDP, 0, 0)
        assert r["dias"] == 8  # tabla: 7 meses = 8 días


# ═══════════════════════════════════════════════════════════════════════════
# SALARIO DE NAVIDAD (Art. 219)
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcularSalarioNavidad:
    def test_anio_completo_12_meses(self):
        salaries = [45000.0] * 12
        r = LiquidacionService.calcular_salario_navidad(salaries)
        assert r["monto"] == round(45000.0 * 12 / 12, 2)  # 45000
        assert r["exentoTSS"] is True
        assert r["exentoISR"] is True

    def test_medio_anio(self):
        salaries = [45000.0] * 6
        r = LiquidacionService.calcular_salario_navidad(salaries)
        assert r["monto"] == round(45000.0 * 6 / 12, 2)  # 22500

    def test_sin_salarios(self):
        r = LiquidacionService.calcular_salario_navidad([])
        assert r["monto"] == 0.0
        assert r["aplica"] is False


# ═══════════════════════════════════════════════════════════════════════════
# CÁLCULO COMPLETO DE LIQUIDACIÓN
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcularLiquidacion:
    def test_desahucio_empleador_3_anios(self):
        """Empleado con 3 años, salario fijo 45000, desahucio por empleador."""
        hire = _d(1095)  # ~3 años atrás
        term = _d(0)      # hoy
        salaries_12 = [45000.0] * 12
        salaries_ytd = [45000.0] * 7  # enero a julio

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-001",
            employee_name="Juan Pérez",
            cedula="00112345678",
            hire_date=hire,
            termination_date=term,
            termination_type="desahucio_empleador",
            last_base_salary=45000.0,
            salary_frequency="mensual",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            preaviso_trabajado=False,
            vacation_pending_days=0,
            vacation_days_taken_this_period=0,
            created_by="test@example.com",
        )

        # Assert estructura
        assert "conceptos" in r
        assert "preaviso" in r["conceptos"]
        assert "cesantia" in r["conceptos"]
        assert "vacaciones" in r["conceptos"]
        assert "salarioNavidad" in r["conceptos"]

        # Aplica prestaciones
        assert r["aplicaPrestaciones"] is True
        assert r["conceptos"]["preaviso"]["aplica"] is True
        assert r["conceptos"]["cesantia"]["aplica"] is True

        # Preaviso: 3 años = 28 días
        assert r["conceptos"]["preaviso"]["dias"] == 28
        # Cesantía: 3 años x 21 = 63
        assert r["conceptos"]["cesantia"]["dias"] == 63

        # Exenciones fiscales
        assert r["conceptos"]["preaviso"]["exentoTSS"] is True
        assert r["conceptos"]["preaviso"]["exentoISR"] is True
        assert r["conceptos"]["cesantia"]["exentoTSS"] is True
        assert r["conceptos"]["cesantia"]["exentoISR"] is True
        assert r["conceptos"]["vacaciones"]["exentoTSS"] is False
        assert r["conceptos"]["vacaciones"]["exentoISR"] is False
        assert r["conceptos"]["salarioNavidad"]["exentoTSS"] is True
        assert r["conceptos"]["salarioNavidad"]["exentoISR"] is True

        # Totales
        assert r["totales"]["montoTotal"] > 0
        assert r["totales"]["montoPrestaciones"] > 0
        assert r["totales"]["montoDerechosAdquiridos"] > 0
        assert r["totales"]["montoGravableTSS"] > 0  # vacaciones son gravables
        assert r["totales"]["montoExento"] > 0  # preaviso + cesantía + navidad

    def test_renuncia_no_aplica_prestaciones(self):
        """Renuncia: no aplica preaviso ni cesantía."""
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [45000.0] * 12
        salaries_ytd = [45000.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-002",
            employee_name="Ana Martínez",
            cedula="00187654321",
            hire_date=hire,
            termination_date=term,
            termination_type="renuncia",
            last_base_salary=45000.0,
            salary_frequency="mensual",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            created_by="test@example.com",
        )

        assert r["aplicaPrestaciones"] is False
        assert r["conceptos"]["preaviso"]["monto"] == 0.0
        assert r["conceptos"]["cesantia"]["monto"] == 0.0
        assert r["conceptos"]["preaviso"]["aplica"] is False
        assert r["conceptos"]["cesantia"]["aplica"] is False
        # Derechos adquiridos SÍ aplican
        assert r["conceptos"]["vacaciones"]["aplica"] is True
        assert r["conceptos"]["salarioNavidad"]["aplica"] is True
        assert r["totales"]["montoPrestaciones"] == 0.0
        assert r["totales"]["montoDerechosAdquiridos"] > 0.0

    def test_despido_justificado_no_aplica_prestaciones(self):
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [45000.0] * 12
        salaries_ytd = [45000.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-003",
            employee_name="Carlos Ruiz",
            hire_date=hire,
            termination_date=term,
            termination_type="despido_justificado",
            last_base_salary=45000.0,
            salary_frequency="mensual",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            created_by="test@example.com",
        )

        assert r["aplicaPrestaciones"] is False
        assert r["conceptos"]["preaviso"]["monto"] == 0.0
        assert r["conceptos"]["cesantia"]["monto"] == 0.0

    def test_dimision_justificada_aplica_prestaciones(self):
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [45000.0] * 12
        salaries_ytd = [45000.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-004",
            employee_name="María López",
            hire_date=hire,
            termination_date=term,
            termination_type="dimision_justificada",
            last_base_salary=45000.0,
            salary_frequency="mensual",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            created_by="test@example.com",
        )

        assert r["aplicaPrestaciones"] is True
        assert r["conceptos"]["preaviso"]["aplica"] is True
        assert r["conceptos"]["cesantia"]["aplica"] is True

    def test_preaviso_trabajado_cero(self):
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [45000.0] * 12
        salaries_ytd = [45000.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-005",
            employee_name="Pedro Gómez",
            hire_date=hire,
            termination_date=term,
            termination_type="desahucio_empleador",
            last_base_salary=45000.0,
            salary_frequency="mensual",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            preaviso_trabajado=True,
            created_by="test@example.com",
        )

        assert r["conceptos"]["preaviso"]["dias"] == 0
        assert r["conceptos"]["preaviso"]["monto"] == 0.0

    def test_empleado_reciente_menos_3_meses(self):
        """Empleado con menos de 3 meses no tiene derecho a prestaciones."""
        hire = _d(60)   # 2 meses atrás
        term = _d(0)
        salaries_12 = [45000.0]
        salaries_ytd = [45000.0]

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-006",
            employee_name="Nuevo Empleado",
            hire_date=hire,
            termination_date=term,
            termination_type="desahucio_empleador",
            last_base_salary=45000.0,
            salary_frequency="mensual",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            created_by="test@example.com",
        )

        assert r["conceptos"]["preaviso"]["dias"] == 0
        assert r["conceptos"]["cesantia"]["dias"] == 0

    def test_vacaciones_con_pendientes_y_tomados(self):
        """Empleado con 3 años, 14 días pendientes de período anterior,
        7 días ya tomados del actual."""
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [45000.0] * 12
        salaries_ytd = [45000.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-007",
            employee_name="Test Vacaciones",
            hire_date=hire,
            termination_date=term,
            termination_type="renuncia",
            last_base_salary=45000.0,
            salary_frequency="mensual",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            vacation_pending_days=14,
            vacation_days_taken_this_period=7,
            created_by="test@example.com",
        )

        assert r["conceptos"]["vacaciones"]["dias"] == 14 - 7 + 14  # 21
        assert r["conceptos"]["vacaciones"]["monto"] > 0

    def test_output_contiene_info_completa(self):
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [45000.0] * 12
        salaries_ytd = [45000.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-008",
            employee_name="Test Completo",
            cedula="40212345678",
            hire_date=hire,
            termination_date=term,
            termination_type="desahucio_empleador",
            last_base_salary=45000.0,
            salary_frequency="mensual",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            notes="Liquidación por reestructuración",
            created_by="admin@example.com",
        )

        assert r["id"] != ""
        assert r["employeeId"] == "emp-008"
        assert r["employeeName"] == "Test Completo"
        assert r["cedula"] == "40212345678"
        assert r["terminationType"] == "desahucio_empleador"
        assert r["salarioDiarioPromedio"] > 0
        assert r["antiguedad"]["years"] >= 2
        assert r["conceptos"]["preaviso"]["baseLegal"] == "Art. 76 Código de Trabajo"
        assert r["conceptos"]["cesantia"]["baseLegal"] == "Art. 80 Código de Trabajo"
        assert r["conceptos"]["vacaciones"]["baseLegal"] == "Art. 177 y 182 Código de Trabajo"
        assert r["conceptos"]["salarioNavidad"]["baseLegal"] == "Art. 219 Código de Trabajo"
        assert r["notas"] == "Liquidación por reestructuración"
        assert r["createdBy"] == "admin@example.com"
        assert r["status"] == "calculada"
        assert r["createdAt"] != ""

    def test_salario_quincenal(self):
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [45000.0] * 12
        salaries_ytd = [45000.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-009",
            hire_date=hire,
            termination_date=term,
            termination_type="desahucio_empleador",
            last_base_salary=45000.0,
            salary_frequency="quincenal",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            created_by="test@example.com",
        )

        expected_sdp = round(sum(salaries_12) / 12 / 11.91, 4)
        assert r["salarioDiarioPromedio"] == expected_sdp

    def test_salario_semanal(self):
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [10500.0] * 12
        salaries_ytd = [10500.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-010",
            hire_date=hire,
            termination_date=term,
            termination_type="desahucio_empleador",
            last_base_salary=10500.0,
            salary_frequency="semanal",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            created_by="test@example.com",
        )

        expected_sdp = round(10500.0 / 5.5, 4)
        assert r["salarioDiarioPromedio"] == expected_sdp

    def test_salario_diario(self):
        hire = _d(1095)
        term = _d(0)
        salaries_12 = [1500.0] * 12
        salaries_ytd = [1500.0] * 7

        r = LiquidacionService.calcular_liquidacion(
            employee_id="emp-011",
            hire_date=hire,
            termination_date=term,
            termination_type="desahucio_empleador",
            last_base_salary=1500.0,
            salary_frequency="diario",
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            created_by="test@example.com",
        )

        assert r["salarioDiarioPromedio"] == 1500.0
