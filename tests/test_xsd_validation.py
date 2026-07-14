#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')

from app.services.xsd_validator import validate_xml
from app.services.dgii_xml_builder import DgiiXmlBuilder

company_profile = {
    "companyRNC": "131111111",
    "companyName": "EMPRESA DE PRUEBA SRL",
    "tradeName": "PRUEBA",
    "companyAddress": "AV PRUEBA 123, ENSANCHE PRUEBA",
    "municipality": "Santo Domingo de Guzmán",
    "province": "Santo Domingo",
    "companyPhone": "809-555-5555",
    "companyEmail": "test@example.com",
}

def make_invoice_data(ecf_type_label, tipo_ecf):
    return {
        "ecfType": ecf_type_label,
        "encf": f"E{tipo_ecf}0100000001",
        "currency": "DOP",
        "incomeType": "01",
        "paymentMethod": "Efectivo",
        "subtotal": "1000.00",
        "totalITBIS": "180.00",
        "total": "1180.00",
        "discountRate": "0",
        "retainedITBIS": "0",
        "retainedISR": "0",
        "clientRNC": "131111112",
        "razonSocial": "CLIENTE PRUEBA SRL",
        "clientName": "CLIENTE PRUEBA SRL",
        "clientMunicipality": "Santo Domingo de Guzmán",
        "clientProvince": "Santo Domingo",
        "items": [
            {
                "name": "Producto de prueba",
                "unit": "Unidad",
                "quantity": "1",
                "price": "1000.00",
                "subtotal": "1000.00",
                "itbisAmount": "180.00",
                "codigoImpuesto": "",
                "tasaImpuestoAdicional": "0",
            },
        ],
        "invoiceNumber": "1",
        "internalInvoiceNumber": "1",
    }

test_cases = [
    ("E31 - Factura de Crédito Fiscal", "31", "Factura de Crédito Fiscal (E31)"),
    ("E32 - Factura de Consumo", "32", "Factura de Consumo (E32)"),
    ("E33 - Nota de Débito", "33", "Nota de Débito (E33)"),
    ("E34 - Nota de Crédito", "34", "Nota de Crédito (E34)"),
    ("E41 - Comprobante de Compras", "41", "Comprobante de Compras (E41)"),
    ("E43 - Gastos Menores", "43", "Gastos Menores (E43)"),
    ("E44 - Regímenes Especiales", "44", "Regímenes Especiales (E44)"),
    ("E45 - Comprobante Gubernamental", "45", "Comprobante Gubernamental (E45)"),
    ("E46 - Comprobante de Exportación", "46", "Comprobante de Exportación (E46)"),
    ("E47 - Pagos al Exterior", "47", "Pagos al Exterior (E47)"),
]

for label, tipo_ecf, ecf_type_label in test_cases:
    inv = make_invoice_data(ecf_type_label, tipo_ecf)
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, inv)
    result = validate_xml(xml_bytes, tipo_ecf)

    print(f"\n{'='*60}")
    print(f"Testing: {label}")
    print(f"{'='*60}")
    print(f"Valid: {result['valid']}")
    if not result['valid']:
        # Show first 10 errors
        for err in result['errors'][:10]:
            print(f"  ERROR: {err}")
        if len(result['errors']) > 10:
            print(f"  ... and {len(result['errors']) - 10} more errors")
    else:
        print(f"  Validation PASSED")

# Also print the generated XML for E31 for manual inspection
print("\n\n" + "="*60)
print("Sample XML (E31 - first 3000 chars):")
print("="*60)
inv = make_invoice_data("Factura de Crédito Fiscal (E31)", "31")
xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, inv)
print(xml_bytes.decode('utf-8')[:3000])
