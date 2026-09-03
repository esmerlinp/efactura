"""Tests para el catálogo oficial de ocupaciones SIRLA."""

from app.data.occupations_catalog import (
    OCCUPATIONS,
    get_occupation,
    get_occupation_name,
)


class TestOccupationsCatalog:
    def test_catalogo_cargado(self):
        assert len(OCCUPATIONS) > 2000

    def test_codigos_unicos(self):
        codes = [oc["code"] for oc in OCCUPATIONS]
        assert len(codes) == len(set(codes))

    def test_get_occupation(self):
        oc = get_occupation("6086")
        assert oc is not None
        assert "ABOGADO" in oc["name"]

    def test_get_occupation_name(self):
        assert get_occupation_name("6054") == "DESARROLLADORES DE SOFTWARE / DESARROLLADOR DE SOFTWARE"

    def test_codigo_inexistente(self):
        assert get_occupation("999999") is None
        assert get_occupation_name("999999") == ""
