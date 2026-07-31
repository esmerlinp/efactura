import pytest
from app.utils.ecf_utils import (
    get_ecf_type_short_code, get_ecf_type_number_code,
    get_modification_reason_dgii, DGII_MODIFICATION_REASONS,
)


@pytest.mark.parametrize("ecf_type,expected_short,expected_num", [
    ("Factura de Credito Fiscal (E31)", "E31", "31"),
    ("Factura de Consumo (E32)", "E32", "32"),
    ("Nota de Debito (E33)", "E33", "33"),
    ("Nota de Credito (E34)", "E34", "34"),
    ("Comprobante de Compras (E41)", "E41", "41"),
    ("Gastos Menores (E43)", "E43", "43"),
    ("Regimenes Especiales (E44)", "E44", "44"),
    ("Gubernamental (E45)", "E45", "45"),
    ("Exportacion (E46)", "E46", "46"),
    ("Pagos al Exterior (E47)", "E47", "47"),
    ("Unknown Type", "E32", "32"),
    ("", "E32", "32"),
])
def test_ecf_type_codes(ecf_type, expected_short, expected_num):
    assert get_ecf_type_short_code(ecf_type) == expected_short
    assert get_ecf_type_number_code(ecf_type) == expected_num


class TestModificationReasonDgii:

    def test_catalog_complete(self):
        assert DGII_MODIFICATION_REASONS == {
            1: "Devolución",
            2: "Corrección de texto",
            3: "Corrige Montos del NCF Modificado",
            4: "Descuento por volumen",
            5: "Otros",
        }

    def test_code_3_always_official_text(self):
        assert get_modification_reason_dgii(3, "Corrección de importes") == "Corrige Montos del NCF Modificado"
        assert get_modification_reason_dgii(3, "Descuento") == "Corrige Montos del NCF Modificado"
        assert get_modification_reason_dgii(3) == "Corrige Montos del NCF Modificado"
        assert get_modification_reason_dgii("3", "Descuento: promoción") == "Corrige Montos del NCF Modificado"

    def test_code_3_ecf_uses_e_ncf(self):
        assert get_modification_reason_dgii(3, "Corrección de importes", "E34") == "Corrige Montos del e-NCF Modificado"
        assert get_modification_reason_dgii(3, "", "Nota de Crédito (E34)") == "Corrige Montos del e-NCF Modificado"
        assert get_modification_reason_dgii(3, "", "E33") == "Corrige Montos del e-NCF Modificado"

    def test_code_3_traditional_uses_ncf(self):
        assert get_modification_reason_dgii(3, "", "B04") == "Corrige Montos del NCF Modificado"
        assert get_modification_reason_dgii(3, "", "Nota de Crédito (B04)") == "Corrige Montos del NCF Modificado"
        assert get_modification_reason_dgii(3, "", "B03") == "Corrige Montos del NCF Modificado"

    def test_other_codes_prefer_stored_reason(self):
        assert get_modification_reason_dgii(1, "Devolución: mercancía defectuosa") == "Devolución: mercancía defectuosa"
        assert get_modification_reason_dgii(9, "Motivo personalizado") == "Motivo personalizado"

    def test_other_codes_fallback_to_catalog(self):
        assert get_modification_reason_dgii(1, "") == "Devolución"
        assert get_modification_reason_dgii(2) == "Corrección de texto"
        assert get_modification_reason_dgii(4) == "Descuento por volumen"
        assert get_modification_reason_dgii(5) == "Otros"

    def test_unknown_code_without_stored_returns_empty(self):
        assert get_modification_reason_dgii(99, "") == ""

    def test_no_code_uses_stored_reason(self):
        assert get_modification_reason_dgii(None, "Motivo libre") == "Motivo libre"
        assert get_modification_reason_dgii(None, "") == ""
