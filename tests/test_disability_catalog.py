"""Tests para el catálogo oficial de discapacidades SIRLA."""

from app.data.disability_catalog import (
    SIRLA_DISABILITIES,
    DEFAULT_DISABILITY_CODE,
    is_valid_disability_code,
    get_disability_name,
    normalize_disability,
)


class TestDisabilityCatalog:
    def test_catalogo_cargado(self):
        assert len(SIRLA_DISABILITIES) == 8

    def test_default_none(self):
        assert DEFAULT_DISABILITY_CODE == "4714"

    def test_valida_codigo(self):
        assert is_valid_disability_code("285") is True
        assert is_valid_disability_code("4714") is True
        assert is_valid_disability_code("9999") is False
        assert is_valid_disability_code("") is False

    def test_nombre(self):
        assert get_disability_name("285") == "Discapacidad Auditiva"
        assert get_disability_name("4714") == "Ninguna"
        assert get_disability_name("9999") == ""


class TestNormalizeDisability:
    def test_vacio_devuelve_default(self):
        assert normalize_disability("") == "4714"
        assert normalize_disability(None) == "4714"
        assert normalize_disability("   ") == "4714"

    def test_lista_vacia_devuelve_default(self):
        assert normalize_disability([]) == "4714"

    def test_codigos_validos(self):
        assert normalize_disability("285,289") == "285,289"

    def test_lista_de_codigos(self):
        assert normalize_disability(["285", "289"]) == "285,289"

    def test_descarta_invalidos(self):
        assert normalize_disability("285,9999,289") == "285,289"

    def test_deduplica(self):
        assert normalize_disability("285,285,289") == "285,289"

    def test_excluye_ninguna_cuando_hay_otras(self):
        assert normalize_disability("4714,285") == "285"
        assert normalize_disability(["285", "4714"]) == "285"

    def test_solo_ninguna(self):
        assert normalize_disability("4714") == "4714"


class TestBuildDgtLineFallback:
    def test_sin_discapacidad_usa_default(self):
        from app.services.dgt_service import _build_dgt_line
        emp = {
            "id": "E1",
            "cedula": "00112345678",
            "idType": "cedula",
            "firstName": "Juan",
            "firstLastName": "Perez",
            "baseSalary": 50000,
        }
        line = _build_dgt_line(emp)
        assert line["discapacidad"] == "4714"

    def test_discapacidad_real(self):
        from app.services.dgt_service import _build_dgt_line
        emp = {
            "id": "E1",
            "cedula": "00112345678",
            "idType": "cedula",
            "firstName": "Juan",
            "firstLastName": "Perez",
            "baseSalary": 50000,
            "disability": "285,289",
        }
        line = _build_dgt_line(emp)
        assert line["discapacidad"] == "285,289"
