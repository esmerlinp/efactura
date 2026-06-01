from app.services.dgii import DGIIService

def run_tests():
    print("\nTest 4: ISC Alcohol Ad-Valorem (No Granel)")
    item4 = {
        'price': 1063.97,
        'quantity': 1,
        'precioReferencia': 80.00,
        'codigoImpuesto': '023',
        'tasaImpuestoAdicional': 0.10,
        'montoImpuestoSelectivoEspecifico': 276.34,
        'cantidadReferencia': 16,
        'itbisRate': 0.18
    }
    result4 = DGIIService.calculate_invoice_totals([item4])
    print(f"Result: {result4['items'][0]['isc_advalorem_amount']}")
    assert result4['items'][0]['isc_advalorem_amount'] == 73.49

run_tests()
