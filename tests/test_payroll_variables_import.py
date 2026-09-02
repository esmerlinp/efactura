"""Tests para la importación CSV de variables de nómina."""

from unittest.mock import patch

from app.web.rrhh.payroll_variables_import import parse_variables_csv, parse_tab_csv
from app.services.payroll_service import PayrollService


EMPLOYEES = {
    "40212345678": {"id": "E1", "fullName": "Juan Pérez"},
    "00198765432": {"id": "E2", "fullName": "Ana Rosa"},
}


def test_csv_valido_importa_filas():
    content = "cedula,concepto,monto\n40212345678,comision,5000.00\n00198765432,horas_extra,8\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert result["errors"] == []
    assert len(result["rows"]) == 2
    assert result["rows"][0]["employeeId"] == "E1"
    assert result["rows"][0]["conceptField"] == "COMISION"
    assert result["rows"][0]["amount"] == 5000.0
    assert result["rows"][1]["conceptField"] == "HORAS_EXTRA"
    assert result["rows"][1]["amount"] == 8.0


def test_delimitador_punto_y_coma_y_bom():
    content = "\ufeffcédula;concepto;monto\n40212345678;bonificación;1,500.50\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert result["errors"] == []
    assert result["rows"][0]["conceptField"] == "BONIFICACION"
    assert result["rows"][0]["amount"] == 1500.5


def test_cedula_con_guiones():
    content = "cedula,concepto,monto\n402-1234567-8,otros_ingresos,100\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert result["errors"] == []
    assert result["rows"][0]["employeeId"] == "E1"


def test_cedula_no_encontrada():
    content = "cedula,concepto,monto\n99999999999,comision,500\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert len(result["errors"]) == 1
    assert result["errors"][0]["line"] == 2
    assert "no encontrado" in result["errors"][0]["error"]


def test_concepto_invalido():
    content = "cedula,concepto,monto\n40212345678,aguinaldo,500\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert len(result["errors"]) == 1
    assert "Concepto inválido" in result["errors"][0]["error"]


def test_monto_invalido_y_negativo():
    content = "cedula,concepto,monto\n40212345678,comision,abc\n40212345678,bonus,-10\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert len(result["errors"]) == 2
    assert "Monto inválido" in result["errors"][0]["error"]
    assert "negativo" in result["errors"][1]["error"]


def test_fila_vacia_se_ignora():
    content = "cedula,concepto,monto\n40212345678,comision,500\n,,\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert result["errors"] == []
    assert len(result["rows"]) == 1


def test_encabezado_invalido():
    content = "empleado,valor\n40212345678,500\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert len(result["errors"]) == 1
    assert "encabezado" in result["errors"][0]["error"]


def test_monto_con_separador_de_miles():
    content = "cedula,concepto,monto\n40212345678,comision,\"5,000.00\"\n"
    result = parse_variables_csv(content, EMPLOYEES)
    assert result["errors"] == []
    assert result["rows"][0]["amount"] == 5000.0


# ═══════════════════════════════════════════════════════════════════════
# CSV POR TAB (plantillas separadas)
# ═══════════════════════════════════════════════════════════════════════

TAB_COMISIONES = {"tab": "comisiones", "concept": "COMISION", "label": "Comisiones", "hours": False}


class TestParseTabCsv:

    def test_csv_tab_valido(self):
        content = "cedula,monto\n40212345678,2500.00\n00198765432,3000\n"
        result = parse_tab_csv(content, EMPLOYEES, TAB_COMISIONES)
        assert result["errors"] == []
        assert len(result["rows"]) == 2
        assert all(r["conceptField"] == "comisiones" for r in result["rows"])
        assert result["rows"][0]["employeeId"] == "E1"
        assert result["rows"][0]["amount"] == 2500.0

    def test_csv_tab_cedula_invalida(self):
        content = "cedula,monto\n99999999999,100\n"
        result = parse_tab_csv(content, EMPLOYEES, TAB_COMISIONES)
        assert len(result["errors"]) == 1
        assert result["errors"][0]["line"] == 2

    def test_csv_tab_monto_invalido(self):
        content = "cedula,monto\n40212345678,abc\n"
        result = parse_tab_csv(content, EMPLOYEES, TAB_COMISIONES)
        assert len(result["errors"]) == 1
        assert "Monto inválido" in result["errors"][0]["error"]

    def test_csv_tab_encabezado_incompleto(self):
        content = "nombre,descripcion\n40212345678,100\n"
        result = parse_tab_csv(content, EMPLOYEES, TAB_COMISIONES)
        assert len(result["errors"]) == 1
        assert "encabezado" in result["errors"][0]["error"]


# ═══════════════════════════════════════════════════════════════════════
# EXTRACCIÓN DE VARIABLES MANUALES DE UN PERÍODO
# ═══════════════════════════════════════════════════════════════════════

class TestGetPeriodManualVariables:

    def _tx(self, code, source, amount, emp="E1", **extra):
        tx = {
            "employeeId": emp,
            "conceptCode": code,
            "source": source,
            "amount": amount,
        }
        tx.update(extra)
        return tx

    @patch("app.services.hr_data_service.get_payroll_transactions")
    def test_extrae_solo_variables_manuales(self, get_tx_mock):
        get_tx_mock.return_value = [
            self._tx("HORAS_EXTRA", "overtime", 8.0),
            self._tx("COMISION", "commission", 5000.0),
            self._tx("BONIFICACION", "bonus", 2000.0),
            self._tx("OTROS_INGRESOS", "manual", 300.0),
            self._tx("OTRAS_DEDUCCIONES", "manual", 400.0),
            self._tx("SALARIO_BASE", "concept", 25000.0),
        ]
        rows = PayrollService.get_period_manual_variables("P1", "C1")
        assert len(rows) == 5
        fields = {(r["employeeId"], r["conceptField"], r["amount"]) for r in rows}
        assert ("E1", "HORAS_EXTRA", 8.0) in fields
        assert ("E1", "COMISION", 5000.0) in fields
        assert ("E1", "BONIFICACION", 2000.0) in fields
        assert ("E1", "INGRESO_VARIABLE", 300.0) in fields
        assert ("E1", "OTRAS_DEDUCCIONES", 400.0) in fields

    @patch("app.services.hr_data_service.get_payroll_transactions")
    def test_excluye_transacciones_automaticas(self, get_tx_mock):
        get_tx_mock.return_value = [
            self._tx("COMISION", "rule:R1", 500.0, isRuleGenerated=True),
            self._tx("COMISION", "recurring:M1", 500.0, isRecurring=True),
            self._tx("HORAS_EXTRA", "overtime:HE01", 500.0),
            self._tx("REGALIA_PASCUAL", "system", 1000.0),
            self._tx("COMISION", "manual", 500.0),
        ]
        rows = PayrollService.get_period_manual_variables("P1", "C1")
        assert len(rows) == 1
        assert rows[0]["conceptField"] == "REGALIA_PASCUAL"

    @patch("app.services.hr_data_service.get_payroll_transactions")
    def test_deduplica_por_empleado_y_concepto(self, get_tx_mock):
        get_tx_mock.return_value = [
            self._tx("COMISION", "commission", 5000.0),
            self._tx("COMISION", "commission", 250.0),
        ]
        rows = PayrollService.get_period_manual_variables("P1", "C1")
        assert len(rows) == 1
        assert rows[0]["amount"] == 5000.0
