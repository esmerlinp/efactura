"""
Batería E46 — Exportación

Positivos:
  1. Cliente extranjero, moneda USD
  2. Transporte internacional (incoterm FOB, puerto)
  3. Cliente extranjero sin ITBIS

Negativos:
  4. Cliente local (RNC dominicano) en E46
  5. ITBIS aplicado incorrectamente (exportación no paga ITBIS)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_cases_base import base_invoice, run_battery

TIPO = "46"


def assert_xsd_ok(r):
    assert len(r["xsd_errors"]) == 0, f"XSD: {r['xsd_errors']}"

def assert_no_itbis(r):
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    assert itbis == 0, f"Exportación no debe tener ITBIS, got {itbis}"

def assert_moneda_extranjera(r):
    currency = r["invoice"].get("currency", "DOP")
    assert currency.upper() != "DOP", "E46 debe usar moneda extranjera"

def assert_transporte_presente(r):
    tr = r["doc"].find(".//Transporte")
    assert tr is not None, "E46 debe tener Transporte"
    pais_dest = r["doc"].findtext(".//PaisDestino", "")
    assert len(pais_dest) > 0, "PaisDestino requerido en E46"

def assert_info_adicional_presente(r):
    info = r["doc"].find(".//InformacionesAdicionales")
    assert info is not None, "E46 debe tener InformacionesAdicionales"


cases = []

# Positivos
cases.append({
    "name": "Cliente extranjero USD",
    "expected": "accept",
    "invoice_overrides": {
        "clientRNC": "", "razonSocial": "FOREIGN BUYER INC",
        "currency": "USD", "exchangeRate": "58.50",
        "totalForeign": 1000.00,
        "clientCountry": "US",
        "subtotal": 1000, "total": 1000, "totalITBIS": 0, "montoExento": 1000,
        "puertoEmbarque": "Puerto de Haina",
        "condicionesEntrega": "FOB",
        "viaTransporte": "01", "paisOrigen": "DO",
        "direccionDestino": "Miami, FL, USA",
        "paisDestino": "US",
        "items": [{"name": "Producto exportación", "unit": "Unidad", "quantity": 10,
                   "price": 100, "subtotal": 1000, "type": "producto"}],
    },
    "assertions": [assert_xsd_ok, assert_moneda_extranjera, assert_transporte_presente, assert_info_adicional_presente],
})

cases.append({
    "name": "Transporte FOB con puerto especificado",
    "expected": "accept",
    "invoice_overrides": {
        "clientRNC": "", "razonSocial": "BUYER EU LTD",
        "currency": "EUR", "exchangeRate": "62.00",
        "totalForeign": 1000.00,
        "clientCountry": "ES",
        "subtotal": 1000, "total": 1000, "totalITBIS": 0, "montoExento": 1000,
        "puertoEmbarque": "Puerto de Caucedo",
        "condicionesEntrega": "CIF",
        "viaTransporte": "02", "paisOrigen": "DO",
        "direccionDestino": "Barcelona, España",
        "paisDestino": "ES",
    },
    "assertions": [assert_xsd_ok, assert_transporte_presente],
})

cases.append({
    "name": "Sin ITBIS en exportación",
    "expected": "accept",
    "invoice_overrides": {
        "clientRNC": "", "razonSocial": "CANADA BUYER CORP",
        "currency": "USD",
        "clientCountry": "CA",
        "subtotal": 1000, "total": 1000, "totalITBIS": 0, "montoExento": 1000,
        "paisDestino": "CA",
    },
    "assertions": [assert_xsd_ok, assert_no_itbis],
})

# Negativos
cases.append({
    "name": "Cliente local con RNC dominicano",
    "expected": "reject",
    "invoice_overrides": {
        "clientRNC": "131222222", "razonSocial": "CLIENTE LOCAL SRL",
        "clientCountry": "DO",
    },
    "assertions": [
        lambda r: r["invoice"]["clientCountry"].upper() != "DO",
    ],
})

cases.append({
    "name": "ITBIS incorrectamente incluido",
    "expected": "reject",
    "invoice_overrides": {
        "totalITBIS": 180, "montoExento": 0,
        "clientRNC": "", "razonSocial": "FOREIGN CO",
        "currency": "USD",
    },
    "assertions": [assert_no_itbis],
})


if __name__ == "__main__":
    run_battery(TIPO, cases)
