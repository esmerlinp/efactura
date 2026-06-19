import pytest
from app.utils.ecf_utils import get_ecf_type_short_code, get_ecf_type_number_code


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
