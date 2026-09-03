"""Tests para el archivo SIRLA DGT-5 (personal temporero).

Valida encabezado (20), detalle (287) y sumario (7), y las posiciones exactas
de cada campo.
"""

from unittest.mock import patch

from app.services.dgt_export_service import DGTExportService


def _sample_line(**overrides):
    line = {
        "docTypeSirla": "C",
        "documento": "00112345678",
        "monthlySalary": 20000.0,
        "fechaIngresoSirla": "01012020",
        "ocupacionCodigo": "12345",
        "cargo": "Jornalero",
        "turnoSirla": 1,
        "daysWorked": 20,
        "dailySalary": 1000.0,
        "gradoInstruccion": 3,
        "discapacidad": "A",
    }
    line.update(overrides)
    return line


class TestToSirlaTxtDgt5:
    def _render(self, lines=None, **kw):
        lines = lines if lines is not None else [_sample_line()]
        kw.setdefault("company_info", {"companyRNC": "131-88068-1", "rnlNumber": "1234"})
        kw.setdefault("year", 2026)
        kw.setdefault("month", 9)
        return DGTExportService.to_sirla_txt_dgt5(lines, **kw)

    def test_encabezado(self):
        txt = self._render()
        header = txt.split("\n")[0]
        assert len(header) == 20
        assert header == "ET5" + "131880681  " + "092026"

    def test_detalle_longitud_287(self):
        txt = self._render()
        detail = txt.split("\n")[1]
        assert len(detail) == 287

    def test_sumario(self):
        txt = self._render([_sample_line(), _sample_line(documento="002")])
        lines = [l for l in txt.split("\n") if l]
        assert lines[-1] == "S000004"

    def test_posiciones_detalle(self):
        txt = self._render()
        d = txt.split("\n")[1]
        assert d[0] == "D"
        assert d[1:4] == "NI "                     # novedad 3 chars
        assert d[4] == "C"                          # tipo documento
        assert d[5:30] == "00112345678".ljust(25)   # documento
        assert d[30:46] == "0000000020000.00"       # salario mensual 16
        assert d[46:54] == "01012020"               # fecha ingreso
        assert d[54:60] == "012345"                 # ocupación 6
        assert d[60:210] == "Jornalero".ljust(150)  # cargo
        assert d[210:216] == "000001"               # turno
        assert d[216:222] == "001234"               # localidad
        assert d[222:224] == "20"                   # días trabajados
        assert d[224:232] == "01000.00"             # salario por día 8
        assert d[232:237] == "00003"                # nivel educación
        assert d[237:287] == "A".ljust(50)          # discapacidad

    def test_salario_dia_100(self):
        txt = self._render([_sample_line(dailySalary=100.0, monthlySalary=2000.0)])
        d = txt.split("\n")[1]
        assert d[224:232] == "00100.00"

    def test_salario_mensual_decimal(self):
        txt = self._render([_sample_line(monthlySalary=20000.0)])
        d = txt.split("\n")[1]
        assert d[30:46] == "0000000020000.00"

    def test_periodo_es_mmyyyy(self):
        txt = self._render(year=2026, month=1)
        header = txt.split("\n")[0]
        assert header[14:20] == "012026"


# ═══════════════════════════════════════════════════════════════════════════
# get_dgt5_data — período mensual y filtro activo-equivalente
# ═══════════════════════════════════════════════════════════════════════════

class TestGetDgt5Data:
    def _emp(self, emp_id, status="activo", contract="temporal"):
        return {
            "id": emp_id,
            "status": status,
            "contractType": contract,
            "cedula": "001-1234567-8",
            "idType": "cedula",
            "baseSalary": 20000.0,
            "weeklyHours": 44,
            "firstName": "Juan",
            "middleName": "",
            "firstLastName": "Perez",
            "secondLastName": "Gomez",
            "gender": "masculino",
            "birthDate": "1990-05-15",
            "hireDate": "2020-01-01",
            "daysWorked": 20,
            "dailySalary": 1000.0,
        }

    def _run(self, employees, year=2026, month=9):
        with patch("app.services.dgt_service.get_employees", return_value=employees), \
             patch("app.services.db_service.DatabaseService.get_company",
                   return_value={"rnc": "131880681", "rnl_number": "1234",
                                 "company_name": "Test SRL"}):
            from app.services.dgt_service import DGTService
            return DGTService.get_dgt5_data("C1", year, month, sandbox=True)

    def test_filtra_activo_equivalente(self):
        employees = [
            self._emp("E1", status="activo"),
            self._emp("E2", status="vacaciones"),
            self._emp("E3", status="inactivo"),
        ]
        data = self._run(employees)
        assert data["totalEmployees"] == 2

    def test_solo_contratos_temporales(self):
        employees = [
            self._emp("E1", status="activo", contract="temporal"),
            self._emp("E2", status="activo", contract="tiempo_indefinido"),
        ]
        data = self._run(employees)
        assert data["totalEmployees"] == 1

    def test_calcula_salario_mensual(self):
        employees = [self._emp("E1")]
        data = self._run(employees)
        assert data["lines"][0]["monthlySalary"] == 20000.0

    def test_expone_mes(self):
        data = self._run([], year=2026, month=9)
        assert data["month"] == 9
