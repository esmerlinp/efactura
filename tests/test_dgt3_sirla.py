"""Tests para el archivo SIRLA DGT-3 (carga de trabajadores).

Valida que el archivo fixed-width generado coincida con el layout oficial:
encabezado (20), detalle (443) y sumario (7), con las posiciones de cada campo.
"""

from unittest.mock import patch

from app.services.dgt_export_service import DGTExportService


# ═══════════════════════════════════════════════════════════════════════════
# Generación completa del archivo
# ═══════════════════════════════════════════════════════════════════════════

def _sample_line(**overrides):
    line = {
        "docTypeSirla": "C",
        "documento": "00112345678",
        "primerNombre": "Juan Carlos",
        "primerApellido": "Perez",
        "segundoApellido": "Gomez",
        "fechaNacimientoSirla": "15051990",
        "sexo": "M",
        "salario": 50000,
        "fechaIngresoSirla": "01012020",
        "ocupacionCodigo": "12345",
        "cargo": "Analista de Sistemas",
        "inicioVacaciones": "01082026",
        "finVacaciones": "15082026",
        "turnoSirla": 1,
        "gradoInstruccion": 3,
        "discapacidad": "A",
    }
    line.update(overrides)
    return line


class TestToTxtDgt3:
    def _render(self, lines=None, **kw):
        lines = lines if lines is not None else [_sample_line()]
        kw.setdefault("company_info", {"companyRNC": "131-88068-1", "rnlNumber": "1234"})
        kw.setdefault("year", 2026)
        kw.setdefault("month", 9)
        return DGTExportService.to_txt(lines, **kw)

    def test_encabezado(self):
        txt = self._render()
        header = txt.split("\n")[0]
        assert len(header) == 20
        assert header == "ET3" + "00131880681" + "092026"

    def test_detalle_longitud_443(self):
        txt = self._render()
        detail = txt.split("\n")[1]
        assert len(detail) == 443

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
        assert d[5:30] == "00112345678".ljust(25)   # número documento
        assert d[30:80] == "Juan Carlos".ljust(50)  # nombres
        assert d[80:120] == "Perez".ljust(40)       # primer apellido
        assert d[120:160] == "Gomez".ljust(40)      # segundo apellido
        assert d[160:168] == "15051990"             # fecha nacimiento
        assert d[168] == "M"                        # sexo
        assert d[169:185] == "0000000000050000"     # salario 16
        assert d[185:193] == "01012020"             # fecha ingreso
        assert d[193:199] == "012345"               # ocupación 6
        assert d[199:349] == "Analista de Sistemas".ljust(150)  # cargo
        assert d[349:357] == "01082026"             # inicio vacaciones
        assert d[357:365] == "15082026"             # fin vacaciones
        assert d[365:371] == "000001"               # turno
        assert d[371:377] == "001234"               # localidad
        assert d[377:388] == " " * 11               # reservado
        assert d[388:393] == "00003"                # nivel educación
        assert d[393:443] == "A".ljust(50)          # discapacidad

    def test_salario_relleno_ceros(self):
        txt = self._render([_sample_line(salario=12500.0)])
        d = txt.split("\n")[1]
        assert d[169:185] == "0000000000012500"

    def test_periodo_es_mmyyyy(self):
        txt = self._render(year=2026, month=1)
        header = txt.split("\n")[0]
        assert header[14:20] == "012026"


# ═══════════════════════════════════════════════════════════════════════════
# get_dgt3_data — período mensual y filtro activo-equivalente
# ═══════════════════════════════════════════════════════════════════════════

class TestGetDgt3Data:
    def _emp(self, emp_id, status="activo", contract="tiempo_indefinido", salary=50000.0):
        return {
            "id": emp_id,
            "status": status,
            "contractType": contract,
            "cedula": "001-1234567-8",
            "idType": "cedula",
            "baseSalary": salary,
            "weeklyHours": 44,
            "firstName": "Juan",
            "middleName": "Carlos",
            "firstLastName": "Perez",
            "secondLastName": "Gomez",
            "gender": "masculino",
            "birthDate": "1990-05-15",
            "hireDate": "2020-01-01",
            "occupationCode": "",
            "position": "Analista",
        }

    def _run(self, employees, year=2026, month=9):
        with patch("app.services.dgt_service.get_employees", return_value=employees), \
             patch("app.services.db_service.DatabaseService.get_company",
                   return_value={"rnc": "131880681", "rnl_number": "1234",
                                 "company_name": "Test SRL"}):
            from app.services.dgt_service import DGTService
            return DGTService.get_dgt3_data("C1", year, month, sandbox=True)

    def test_filtra_activo_equivalente(self):
        employees = [
            self._emp("E1", status="activo"),
            self._emp("E2", status="vacaciones"),
            self._emp("E3", status="licencia"),
            self._emp("E4", status="inactivo"),
            self._emp("E5", status="suspendido"),
        ]
        data = self._run(employees)
        assert data["totalEmployees"] == 3

    def test_solo_contrato_indefinido(self):
        employees = [
            self._emp("E1", status="activo"),
            self._emp("E2", status="activo", contract="tiempo_definido"),
        ]
        data = self._run(employees)
        assert data["totalEmployees"] == 1

    def test_nombres_completos(self):
        employees = [self._emp("E1")]
        data = self._run(employees)
        line = data["lines"][0]
        assert line["primerNombre"] == "Juan Carlos"

    def test_expone_mes(self):
        data = self._run([], year=2026, month=9)
        assert data["month"] == 9
