"""
Batería E41 — Compras

Positivos:
  1. Proveedor informal (sin RNC)
  2. Compra local con RNC
  3. Compra con retención ISR
  4. Compra con retención ITBIS

Negativos:
  5. Retención ITBIS superior al impuesto
  6. Datos incompletos del proveedor
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_cases_base import base_invoice, run_battery

TIPO = "41"


def assert_xsd_ok(r):
    assert len(r["xsd_errors"]) == 0, f"XSD: {r['xsd_errors']}"

def assert_itbis_equals_18pct(r):
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    gravado = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    expected = round(gravado * 0.18, 2)
    assert abs(itbis - expected) <= 1.0

def assert_retencion_itbis_no_mayor(r):
    ret_itbis = float(r["doc"].findtext(".//TotalITBISRetenido", "0"))
    total_itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    assert ret_itbis <= total_itbis + 1.0, f"Retención ITBIS {ret_itbis} > ITBIS {total_itbis}"

def assert_comprador_es_misma_empresa(r):
    rnc_emisor = r["doc"].findtext(".//RNCEmisor", "")
    rnc_comp = r["doc"].findtext(".//RNCComprador", "")
    assert rnc_emisor == rnc_comp, f"E41 Comprador RNC {rnc_comp} ≠ Emisor RNC {rnc_emisor}"

def assert_has_totales_retencion(r):
    has_isr = r["doc"].find(".//TotalISRRetencion") is not None
    has_itbis = r["doc"].find(".//TotalITBISRetenido") is not None
    return has_isr or has_itbis


cases = []

# Positivos
cases.append({
    "name": "Proveedor informal (sin RNC)",
    "expected": "accept",
    "invoice_overrides": {"clientRNC": "", "razonSocial": "VENDEDOR INFORMAL"},
    "assertions": [assert_xsd_ok, assert_comprador_es_misma_empresa],
})

cases.append({
    "name": "Compra local con RNC",
    "expected": "accept",
    "invoice_overrides": {"clientRNC": "131111111", "razonSocial": "PROVEEDOR LOCAL SRL"},
    "assertions": [assert_xsd_ok, assert_comprador_es_misma_empresa],
})

cases.append({
    "name": "Compra con retención ISR",
    "expected": "accept",
    "invoice_overrides": {
        "subtotal": 2000, "total": 2000, "totalITBIS": 0, "montoExento": 2000,
        "retainedISR": 200,
        "items": [{"name": "Servicio profesional", "unit": "Servicio", "quantity": 1,
                   "price": 2000, "subtotal": 2000, "type": "servicio"}],
    },
    "assertions": [assert_xsd_ok, assert_has_totales_retencion],
})

cases.append({
    "name": "Compra con retención ITBIS",
    "expected": "accept",
    "invoice_overrides": {"retainedITBIS": 90},
    "assertions": [assert_xsd_ok, assert_has_totales_retencion, assert_retencion_itbis_no_mayor],
})

# Negativos
cases.append({
    "name": "Retención ITBIS superior al ITBIS",
    "expected": "reject",
    "invoice_overrides": {"totalITBIS": 180, "retainedITBIS": 999},
    "assertions": [assert_retencion_itbis_no_mayor],
})

cases.append({
    "name": "Sin ítems (DetallesItems vacío)",
    "expected": "reject",
    "invoice_overrides": {"items": []},
    "assertions": [
        lambda r: len(r["doc"].findall(".//Item")) > 0,
    ],
})


if __name__ == "__main__":
    run_battery(TIPO, cases)
