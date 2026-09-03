"""Tests para el catálogo oficial de nacionalidades SIRLA."""

from app.data.nationality_catalog import (
    SIRLA_NATIONALITIES,
    is_valid_nationality_code,
    get_nationality_name,
    nationality_to_sirla,
    LEGACY_NATIONALITY_CODE_MAP,
)


class TestNationalityCatalog:
    def test_catalogo_cargado(self):
        assert len(SIRLA_NATIONALITIES) == 152

    def test_preserva_saltos_oficiales(self):
        codes = {n["code"] for n in SIRLA_NATIONALITIES}
        assert "47" not in codes
        assert "78" not in codes
        assert "105" not in codes
        assert "1" in codes
        assert "155" in codes

    def test_codigos_unicos(self):
        codes = [n["code"] for n in SIRLA_NATIONALITIES]
        assert len(codes) == len(set(codes))

    def test_valida_codigo(self):
        assert is_valid_nationality_code("1") is True
        assert is_valid_nationality_code("29") is True
        assert is_valid_nationality_code("155") is True
        assert is_valid_nationality_code("47") is False
        assert is_valid_nationality_code("") is False
        assert is_valid_nationality_code("999") is False

    def test_nombre(self):
        assert get_nationality_name("1") == "DOMINICANA"
        assert get_nationality_name("18") == "VENEZOLANA"
        assert get_nationality_name("999") == ""


class TestNationalityToSirla:
    def test_dominicana_omite(self):
        assert nationality_to_sirla(1) == ""
        assert nationality_to_sirla("1") == ""

    def test_extranjero_dos_digitos(self):
        assert nationality_to_sirla(29) == "29"

    def test_extranjero_un_digito(self):
        assert nationality_to_sirla(2) == "2"

    def test_extranjero_tres_digitos(self):
        assert nationality_to_sirla(155) == "155"

    def test_vacio(self):
        assert nationality_to_sirla(None) == ""
        assert nationality_to_sirla("") == ""


class TestLegacyMap:
    def test_mapa_legacy(self):
        assert LEGACY_NATIONALITY_CODE_MAP["VEN"] == "18"
        assert LEGACY_NATIONALITY_CODE_MAP["USA"] == "2"
        assert LEGACY_NATIONALITY_CODE_MAP["ESP"] == "29"
