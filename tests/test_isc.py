import pytest
from app.services.dgii import DGIIService


def test_isc_alcohol_specific_and_advalorem():
    item = {
        'price': 500.00,
        'quantity': 1,
        'precioReferencia': 600.00,
        'codigoImpuesto': '012',
        'tasaImpuestoAdicional': 158.50,
        'gradosAlcohol': 40.0,
        'cantidadReferencia': 0.75,
        'subcantidad': 1.0,
        'itbisRate': 0.18,
    }
    result = DGIIService.calculate_invoice_totals([item])
    item_result = result['items'][0]
    assert item_result['isc_especifico_amount'] > 0
    assert item_result['isc_advalorem_amount'] >= 0


def test_isc_tobacco():
    item = {
        'price': 500.00,
        'quantity': 1,
        'precioReferencia': 300.00,
        'codigoImpuesto': '019',
        'tasaImpuestoAdicional': 2.50,
        'cantidadReferencia': 20,
        'itbisRate': 0.18,
        'subcantidad': 1.0,
    }
    result = DGIIService.calculate_invoice_totals([item])
    assert result['items'][0]['isc_especifico_amount'] == pytest.approx(50.00, abs=0.01)


def test_no_isc_for_regular_items():
    item = {
        'price': 1000.00,
        'quantity': 1,
        'itbisRate': 0.18,
        'codigoImpuesto': '',
    }
    result = DGIIService.calculate_invoice_totals([item])
    assert result['items'][0]['isc_especifico_amount'] == 0.0
    assert result['items'][0]['isc_advalorem_amount'] == 0.0


def test_isc_propina_legal():
    item = {
        'price': 2000.00,
        'quantity': 1,
        'itbisRate': 0.18,
        'codigoImpuesto': '001',
        'tasaImpuestoAdicional': 0.10,
    }
    result = DGIIService.calculate_invoice_totals([item])
    assert result['items'][0]['otros_impuestos_amount'] == pytest.approx(200.00, abs=0.01)
