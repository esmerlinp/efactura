"""Tests para el archivo SIRLA DGT-11 (Comunicación de Ingreso).

Valida encabezado (30), detalle (278) y sumario (7), las posiciones exactas de
cada campo, el hueco reservado en la posición 223 y el filtro de ingresos
(personal indefinido contratado en el período).
"""

from unittest.mock import patch

from app.services.dgt_export_service import DGTExportService


def _sample_line(**overrides):
    line = {
        "docTypeSirla": "C",
        "documento": "00112345678",
        "salario": 20000.0,
        "fechaIngresoSirla": "01012020",
        "ocupacionCodigo": "12345",
        "cargo": "Jornalero",
        "turnoSirla": 1,
        "gradoInstruccion": 3,
        "discapacidad": "A",
    }
    line.update(overrides)
    return line


class TestToSirlaTxtDgt11:
    def _render(self, lines=None, **kw):
        lines = lines if lines is not None else [_sample_line()]
        kw.setdefault("company_info", {"companyRNC": "131-88068-1", "rnlNumber": "1234"})
        kw.setdefault("year", 2026)
        kw.setdefault("month", 9)
        kw.setdefault("fecha_inicio_estacion", "01012026")
        kw.setdefault("duracion_estacion", 1)
        return DGTExportService.to_sirla_txt_dgt11(lines, **kw)

    def test_encabezado_longitud_30(self):
        txt = self._render()
        header = txt.split("\n")[0]
        assert len(header) == 30

    def test_encabezado(self):
        txt = self._render()
        header = txt.split("\n")[0]
        # RNC es N (right-zero): 131880681 -> 00131880681
        assert header == "E" + "G1" + "00131880681" + "092026" + "01012026" + "01"

    def test_detalle_longitud_278(self):
        txt = self._render()
        detail = txt.split("\n")[1]
        assert len(detail) == 278

    def test_sumario(self):
        txt = self._render([_sample_line(), _sample_line(documento="002")])
        lines = [l for l in txt.split("\n") if l]
        # E + 2 D + S = 4 registros
        assert lines[-1] == "S000004"

    def test_posiciones_detalle(self):
        txt = self._render()
        d = txt.split("\n")[1]
        assert d[0] == "D"
        assert d[1:4] == "NI "                       # novedad 3 chars
        assert d[4] == "C"                            # tipo documento
        assert d[5:30] == "00112345678".ljust(25)     # documento
        assert d[30:46] == "0000000000020000"         # salario 16 (N right-zero)
        assert d[46:54] == "01012020"                 # fecha ingreso
        assert d[54:60] == "012345"                   # ocupación 6
        assert d[60:210] == "Jornalero".ljust(150)    # cargo
        assert d[210:216] == "000001"                 # turno
        assert d[216:222] == "001234"                 # localidad (últimos 4 RNL)
        assert d[222] == " "                          # reservado (hueco 223)
        assert d[223:228] == "00003"                  # nivel educación 5
        assert d[228:278] == "A".ljust(50)            # discapacidad 50

    def test_salario_padding(self):
        txt = self._render([_sample_line(salario=0.0)])
        d = txt.split("\n")[1]
        assert d[30:46] == "0000000000000000"

    def test_duracion_padding(self):
        txt = self._render(duracion_estacion=3)
        header = txt.split("\n")[0]
        assert header[28:30] == "03"

    def test_rnc_numeric_zero_padded(self):
        txt = self._render()
        header = txt.split("\n")[0]
        assert header[3:14] == "00131880681"


# ═══════════════════════════════════════════════════════════════════════════
# get_dgt11_data — reutiliza altas de DGT-4 (indefinido contratado en período)
# ═══════════════════════════════════════════════════════════════════════════

class TestGetDgt11Data:
    def _emp(self, emp_id, contract="tiempo_indefinido", hire="2026-09-10"):
        return {
            "id": emp_id,
            "status": "activo",
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
            "hireDate": hire,
        }

    def _run(self, employees, year=2026, month=9):
        with patch("app.services.dgt_service.get_employees", return_value=employees), \
             patch("app.services.db_service.DatabaseService.get_company",
                   return_value={"rnc": "131880681", "rnl_number": "1234",
                                 "company_name": "Test SRL"}):
            from app.services.dgt_service import DGTService
            return DGTService.get_dgt11_data("C1", year, month, sandbox=True)

    def test_solo_contratos_indefinidos(self):
        employees = [
            self._emp("E1", contract="tiempo_indefinido"),
            self._emp("E2", contract="temporal"),
        ]
        data = self._run(employees)
        assert data["totalIngresos"] == 1

    def test_filtra_por_mes_de_ingreso(self):
        employees = [
            self._emp("E1", hire="2026-09-10"),
            self._emp("E2", hire="2026-08-15"),
        ]
        data = self._run(employees)
        assert data["totalIngresos"] == 1

    def test_expone_establecimiento(self):
        data = self._run([], year=2026, month=9)
        assert data["establishmentId"] == "001234"
