"""Tests para el archivo SIRLA DGT-4 (cambios en personal fijo).

Valida encabezado (20), detalle (451) y sumario (7), y las posiciones exactas
de cada campo, incluyendo los tres tipos de novedad (NI/NS/NC).
"""

from app.services.dgt_export_service import DGTExportService


def _sample_line(**overrides):
    line = {
        "novedadSirla": "NS",
        "docTypeSirla": "C",
        "documento": "00112345678",
        "primerNombre": "Juan Carlos",
        "primerApellido": "Perez",
        "segundoApellido": "Gomez",
        "fechaNacimientoSirla": "15051990",
        "sexo": "M",
        "salario": 50000,
        "fechaIngresoSirla": "01012020",
        "fechaSalidaSirla": "15082026",
        "ocupacionCodigo": "12345",
        "cargo": "Analista de Sistemas",
        "inicioVacaciones": "01082026",
        "finVacaciones": "15082026",
        "turnoSirla": 1,
        "nacionalidadSirla": "",
        "fechaCambioSirla": "20082026",
        "gradoInstruccion": 3,
        "discapacidad": "A",
    }
    line.update(overrides)
    return line


class TestToSirlaTxtDgt4:
    def _render(self, lines=None, **kw):
        lines = lines if lines is not None else [_sample_line()]
        kw.setdefault("company_info", {"companyRNC": "131-88068-1", "rnlNumber": "1234"})
        kw.setdefault("year", 2026)
        kw.setdefault("month", 9)
        return DGTExportService.to_sirla_txt_dgt4(lines, **kw)

    def test_encabezado(self):
        txt = self._render()
        header = txt.split("\n")[0]
        assert len(header) == 20
        assert header == "ET4" + "131880681  " + "092026"

    def test_detalle_longitud_451(self):
        txt = self._render()
        detail = txt.split("\n")[1]
        assert len(detail) == 451

    def test_sumario(self):
        txt = self._render([_sample_line(), _sample_line(documento="002")])
        lines = [l for l in txt.split("\n") if l]
        assert lines[-1] == "S000004"

    def test_posiciones_detalle(self):
        txt = self._render()
        d = txt.split("\n")[1]
        assert d[0] == "D"
        assert d[1:4] == "NS "                     # novedad 3 chars
        assert d[4] == "C"                          # tipo documento
        assert d[5:30] == "00112345678".ljust(25)   # documento
        assert d[30:80] == "Juan Carlos".ljust(50)  # nombres
        assert d[80:120] == "Perez".ljust(40)       # primer apellido
        assert d[120:160] == "Gomez".ljust(40)      # segundo apellido
        assert d[160:168] == "15051990"             # nacimiento
        assert d[168] == "M"                        # sexo
        assert d[169:185] == "0000000000050000"     # salario
        assert d[185:193] == "01012020"             # ingreso
        assert d[193:201] == "15082026"             # salida
        assert d[201:207] == "012345"               # ocupación
        assert d[207:357] == "Analista de Sistemas".ljust(150)  # cargo
        assert d[357:365] == "01082026"             # inicio vacaciones
        assert d[365:373] == "15082026"             # fin vacaciones
        assert d[373:379] == "000001"               # turno
        assert d[379:385] == "001234"               # localidad
        assert d[385:388] == "".ljust(3)            # nacionalidad (vacía)
        assert d[388:396] == "20082026"             # fecha cambio
        assert d[396:401] == "00003"                # educación
        assert d[401:451] == "A".ljust(50)          # discapacidad

    def test_novedad_ingreso(self):
        txt = self._render([_sample_line(novedadSirla="NI")])
        d = txt.split("\n")[1]
        assert d[1:4] == "NI "

    def test_novedad_cambio(self):
        txt = self._render([_sample_line(novedadSirla="NC")])
        d = txt.split("\n")[1]
        assert d[1:4] == "NC "

    def test_nacionalidad_extranjero(self):
        txt = self._render([_sample_line(nacionalidadSirla="2")])
        d = txt.split("\n")[1]
        assert d[385:388] == "2".ljust(3)

    def test_periodo_es_mmyyyy(self):
        txt = self._render(year=2026, month=1)
        header = txt.split("\n")[0]
        assert header[14:20] == "012026"


class TestDGTServiceGetDGT4Data:
    def test_get_dgt4_data_includes_all_change_types(self):
        from unittest.mock import patch
        from app.services.dgt_service import DGTService

        mock_emps = [
            {
                "id": "emp_1",
                "cedula": "001-1234567-8",
                "fullName": "Pedro Martinez",
                "contractType": "tiempo_indefinido",
                "status": "activo",
                "baseSalary": 50000,
                "hireDate": "2026-10-01", # Alta en octubre 2026
            },
            {
                "id": "emp_2",
                "cedula": "001-9876543-2",
                "fullName": "Maria Lopez",
                "contractType": "tiempo_indefinido",
                "status": "inactivo",
                "baseSalary": 45000,
                "terminationDate": "2026-10-15", # Baja en octubre 2026
            },
            {
                "id": "emp_3",
                "cedula": "001-5555555-5",
                "fullName": "Carlos Gomez",
                "contractType": "tiempo_indefinido",
                "status": "activo",
                "baseSalary": 60000,
                "workShift": 2, # Nocturno
                "position": "Encargado de Logística",
            },
            {
                "id": "emp_4",
                "cedula": "001-4444444-4",
                "fullName": "Ana Perez",
                "contractType": "tiempo_indefinido",
                "status": "activo",
                "baseSalary": 55000,
                "hireDate": "2025-01-10", # Empleada previa
            },
        ]

        mock_salaries = [
            # Salario inicial de emp_1 (alta del mes): NO debe generar novedad de cambio
            {
                "employeeId": "emp_1",
                "effectiveDate": "2026-10-01",
                "previousAmount": 0.0,
                "amount": 50000,
                "reason": "Salario inicial",
            },
            # Aumento de sueldo de emp_3 (empleado previo)
            {
                "employeeId": "emp_3",
                "effectiveDate": "2026-10-05",
                "previousAmount": 50000,
                "amount": 60000,
            },
        ]

        mock_vacations = [
            {
                "employeeId": "emp_4",
                "startDate": "2026-10-12",
                "endDate": "2026-10-26",
                "status": "aprobada", # Vacaciones
            }
        ]

        mock_history = [
            {
                "employeeId": "emp_3",
                "effectiveDate": "2026-10-20",
                "changes": ["Turno: Diurno → Nocturno", "Sucursal: Principal → Norte"],
            }
        ]

        with patch("app.services.dgt_service.get_employees", return_value=mock_emps), \
             patch("app.services.dgt_service.get_all_salary_history", return_value=mock_salaries), \
             patch("app.services.dgt_service.get_vacation_requests", return_value=mock_vacations), \
             patch("app.services.dgt_service.get_all_employment_history", return_value=mock_history), \
             patch("app.services.db_service.DatabaseService.get_company", return_value={"company_name": "Test SRL", "rnc": "131880681"}):

            res = DGTService.get_dgt4_data(company_id="comp_1", year=2026, month=10, sandbox=True)

            # Verificar que emp_1 solo aparece 1 vez como ALTA y NO como cambio
            emp1_lines = [c for c in res["lines"] if c["documento"] == "001-1234567-8" or "Pedro Martinez" in c["nombre"]]
            assert len(emp1_lines) == 1
            assert emp1_lines[0]["tipo"] == "alta"

            assert res["altas"] == 1
            assert res["bajas"] == 1
            assert res["modificaciones"] == 2  # emp_3 (sueldo + turno consolidado) y emp_4 (vacaciones)
            assert res["totalCambios"] == 4

            detalles = [c["detalle"] for c in res["lines"]]
            assert any("Ingresó" in d for d in detalles)
            assert any("Terminó" in d for d in detalles)
            assert any("Salario" in d for d in detalles)
            assert any("Vacaciones" in d for d in detalles)
            assert any("Turno" in d for d in detalles)

