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
