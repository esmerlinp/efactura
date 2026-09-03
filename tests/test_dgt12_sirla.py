"""Tests para el archivo SIRLA DGT-12 (Comunicación de Cese/Término).

Valida encabezado (20), detalle (41) y sumario (7), las posiciones exactas de
cada campo y el filtro de ceses (personal indefinido con fecha de salida en el
período).
"""

from unittest.mock import patch

from app.services.dgt_export_service import DGTExportService


def _sample_line(**overrides):
    line = {
        "docTypeSirla": "C",
        "documento": "00112345678",
        "fechaSalidaSirla": "01012020",
    }
    line.update(overrides)
    return line


class TestToSirlaTxtDgt12:
    def _render(self, lines=None, **kw):
        lines = lines if lines is not None else [_sample_line()]
        kw.setdefault("company_info", {"companyRNC": "131-88068-1", "rnlNumber": "1234"})
        kw.setdefault("year", 2026)
        kw.setdefault("month", 9)
        return DGTExportService.to_sirla_txt_dgt12(lines, **kw)

    def test_encabezado_longitud_20(self):
        txt = self._render()
        header = txt.split("\n")[0]
        assert len(header) == 20

    def test_encabezado(self):
        txt = self._render()
        header = txt.split("\n")[0]
        # RNC es AN (left+space): 131880681 -> "131880681  "
        assert header == "E" + "G2" + "131880681  " + "09" + "2026"

    def test_detalle_longitud_41(self):
        txt = self._render()
        detail = txt.split("\n")[1]
        assert len(detail) == 41

    def test_sumario(self):
        txt = self._render([_sample_line(), _sample_line(documento="002")])
        lines = [l for l in txt.split("\n") if l]
        # E + 2 D + S = 4 registros
        assert lines[-1] == "S000004"

    def test_posiciones_detalle(self):
        txt = self._render()
        d = txt.split("\n")[1]
        assert d[0] == "D"
        assert d[1] == "C"                            # tipo documento
        assert d[2:27] == "00112345678".ljust(25)     # documento
        assert d[27:33] == "001234"                   # localidad (últimos 4 RNL)
        assert d[33:41] == "01012020"                 # fecha salida

    def test_rnc_left_padded(self):
        txt = self._render()
        header = txt.split("\n")[0]
        assert header[3:14] == "131880681  "

    def test_fecha_salida_cero(self):
        txt = self._render([_sample_line(fechaSalidaSirla="")])
        d = txt.split("\n")[1]
        assert d[33:41] == "00000000"


# ═══════════════════════════════════════════════════════════════════════════
# get_dgt12_data — reutiliza bajas de DGT-4 (indefinido con fecha salida en período)
# ═══════════════════════════════════════════════════════════════════════════

class TestGetDgt12Data:
    def _emp(self, emp_id, contract="tiempo_indefinido", term="2026-09-10"):
        return {
            "id": emp_id,
            "status": "inactivo",
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
            "terminationDate": term,
        }

    def _run(self, employees, year=2026, month=9):
        with patch("app.services.dgt_service.get_employees", return_value=employees), \
             patch("app.services.db_service.DatabaseService.get_company",
                   return_value={"rnc": "131880681", "rnl_number": "1234",
                                 "company_name": "Test SRL"}):
            from app.services.dgt_service import DGTService
            return DGTService.get_dgt12_data("C1", year, month, sandbox=True)

    def test_solo_contratos_indefinidos(self):
        employees = [
            self._emp("E1", contract="tiempo_indefinido"),
            self._emp("E2", contract="temporal"),
        ]
        data = self._run(employees)
        assert data["totalCeses"] == 1

    def test_filtra_por_mes_de_salida(self):
        employees = [
            self._emp("E1", term="2026-09-10"),
            self._emp("E2", term="2026-08-15"),
        ]
        data = self._run(employees)
        assert data["totalCeses"] == 1

    def test_fecha_salida_en_linea(self):
        employees = [self._emp("E1", term="2026-09-10")]
        data = self._run(employees)
        assert data["lines"][0]["fechaSalidaSirla"] == "10092026"

    def test_expone_establecimiento(self):
        data = self._run([], year=2026, month=9)
        assert data["establishmentId"] == "001234"
