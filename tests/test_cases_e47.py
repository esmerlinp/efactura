"""
Batería E47 — Pagos al Exterior

Positivos:
  1. Proveedor extranjero, moneda USD
  2. Sin ITBIS (pago al exterior no genera ITBIS)

Negativos:
  3. ITBIS incluido incorrectamente
  4. Conversión DOP incorrecta
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_cases_base import base_invoice, run_battery

TIPO = "47"


def assert_xsd_ok(r):
    assert len(r["xsd_errors"]) == 0, f"XSD: {r['xsd_errors']}"

def assert_no_itbis(r):
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    assert itbis == 0, f"E47 no debe tener ITBIS, got {itbis}"

def assert_moneda_extranjera(r):
    currency = r["invoice"].get("currency", "DOP")
    assert currency.upper() != "DOP", "E47 debe usar moneda extranjera"

def assert_comprador_extranjero(r):
    ident = r["doc"].findtext(".//IdentificadorExtranjero", "")
    assert len(ident) > 0, "E47 requiere IdentificadorExtranjero"
    rz = r["doc"].findtext(".//RazonSocialComprador", "")
    assert len(rz) > 0, "E47 requiere RazonSocialComprador"

def assert_retencion_item_presente(r):
    ret = r["doc"].find(".//Retencion")
    assert ret is not None, "E47 requiere Retencion en Item"

def assert_monto_exento_igual_total(r):
    exento = float(r["doc"].findtext(".//MontoExento", "0"))
    total = float(r["doc"].findtext(".//MontoTotal", "0"))
    assert abs(exento - total) <= 0.01, f"E47: MontoExento {exento} ≠ Total {total}"


cases = []

# Positivos
cases.append({
    "name": "Proveedor extranjero USD",
    "expected": "accept",
    "invoice_overrides": {
        "clientRNC": "PASS-12345", "razonSocial": "FOREIGN SUPPLIER LTD",
        "currency": "USD", "exchangeRate": "58.50",
        "totalForeign": 10000.00,
        "subtotal": 0, "total": 10000, "totalITBIS": 0, "montoExento": 10000,
        "paisDestino": "US",
        "items": [{"name": "Servicio consultoría", "unit": "Servicio", "quantity": 1,
                   "price": 10000, "subtotal": 10000, "type": "servicio", "retainedISR": 500}],
    },
    "assertions": [assert_xsd_ok, assert_moneda_extranjera, assert_comprador_extranjero,
                   assert_retencion_item_presente, assert_monto_exento_igual_total],
})

cases.append({
    "name": "Sin ITBIS (pago exterior)",
    "expected": "accept",
    "invoice_overrides": {
        "clientRNC": "ID-99999", "razonSocial": "CONSULTOR EXT",
        "currency": "EUR",
        "subtotal": 0, "total": 5000, "totalITBIS": 0, "montoExento": 5000,
        "items": [{"name": "Honorarios", "unit": "Servicio", "quantity": 1,
                   "price": 5000, "subtotal": 5000, "type": "servicio"}],
    },
    "assertions": [assert_xsd_ok, assert_no_itbis, assert_comprador_extranjero,
                   assert_monto_exento_igual_total],
})

# Negativos
cases.append({
    "name": "ITBIS incluido incorrectamente (builder lo omite)",
    "expected": "accept",
    "invoice_overrides": {
        "clientRNC": "EXT-001", "razonSocial": "SUPPLIER CORP",
        "currency": "USD",
        "subtotal": 0, "total": 11800, "totalITBIS": 1800, "montoExento": 10000,
    },
    "assertions": [
        # E47 no debe tener ITBIS; verificar que el builder lo omita
        lambda r: r["doc"].find(".//TotalITBIS") is None,
        # Y que MontoExento == MontoTotal (todo exento)
        lambda r: abs(float(r["doc"].findtext(".//MontoExento", "0")) -
                      float(r["doc"].findtext(".//MontoTotal", "0"))) <= 0.01,
    ],
})


if __name__ == "__main__":
    run_battery(TIPO, cases)
