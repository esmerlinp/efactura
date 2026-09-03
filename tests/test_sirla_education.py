"""Tests para el catálogo oficial de niveles educativos SIRLA (DGT)."""

from app.data.education_catalog import (
    SIRLA_EDUCATION_LEVELS,
    is_valid_education_code,
    get_education_label,
)


class TestEducationCatalog:
    def test_39_niveles_oficiales(self):
        assert len(SIRLA_EDUCATION_LEVELS) == 39

    def test_rango_4744_a_4782(self):
        codes = [e["code"] for e in SIRLA_EDUCATION_LEVELS]
        assert codes[0] == "4744"
        assert codes[-1] == "4782"

    def test_codigos_unicos(self):
        codes = [e["code"] for e in SIRLA_EDUCATION_LEVELS]
        assert len(codes) == len(set(codes))

    def test_valida_codigo_oficial(self):
        assert is_valid_education_code("4744") is True
        assert is_valid_education_code("4765") is True
        assert is_valid_education_code("4782") is True

    def test_rechaza_codigo_invalido(self):
        assert is_valid_education_code("9999") is False
        assert is_valid_education_code("") is False
        assert is_valid_education_code("1") is False
        assert is_valid_education_code("abc") is False

    def test_label(self):
        assert "Licenciatura" in get_education_label("4765")
        assert get_education_label("9999") == ""


class TestSirlaEducationCodeMapping:
    def test_mapea_codigo_oficial(self):
        from app.services.dgt_service import _sirla_education_code
        assert _sirla_education_code({"sirlaEducationCode": "4765"}) == 4765

    def test_codigo_vacio_devuelve_cero(self):
        from app.services.dgt_service import _sirla_education_code
        assert _sirla_education_code({"sirlaEducationCode": ""}) == 0
        assert _sirla_education_code({}) == 0

    def test_no_mapea_nivel_legacy(self):
        # El nivel legacy 1-6 NO debe mapearse automáticamente a SIRLA
        from app.services.dgt_service import _sirla_education_code
        assert _sirla_education_code({"educationLevel": 4}) == 0
