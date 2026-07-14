"""
Batería E31 — Factura de Crédito Fiscal

Positivos:
  1. Cliente RNC válido, venta gravada
  2. Venta exenta (ITBIS=0)
  3. Venta mixta (gravada + exenta)
  4. Descuento global
  5. Múltiples líneas (5+)

Negativos:
  6. ITBIS incorrecto (tasa 18% en producto exento)
  7. Totales inconsistentes (subtotal+ITBIS≠total)
  8. RNC inválido (formato incorrecto)
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_cases_base import base_invoice, run_battery

TIPO = "31"


# Shared assertions
def assert_xsd_ok(r):
    assert len(r["xsd_errors"]) == 0, f"XSD: {r['xsd_errors']}"

def assert_itbis_equals_18pct(r):
    total_itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    gravado = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    expected = round(gravado * 0.18, 2)
    assert abs(total_itbis - expected) <= 1.0, f"ITBIS {total_itbis} ≠ 18% de {gravado} (~{expected})"

def assert_itbis_es_cero(r):
    total_itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    assert total_itbis == 0.0, f"ITBIS debe ser 0 para venta exenta, got {total_itbis}"

def assert_totales_consistentes(r):
    subtotal = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    exento = float(r["doc"].findtext(".//MontoExento", "0"))
    total = float(r["doc"].findtext(".//MontoTotal", "0"))
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    assert abs(total - (subtotal + exento + itbis)) <= 1.0, f"Total {total} ≠ {subtotal}+{exento}+{itbis}"

def assert_rnc_valido(r):
    rnc = r["invoice"].get("clientRNC", "")
    assert re.match(r"^\d{9}$", rnc) or re.match(r"^\d{11}$", rnc), f"RNC inválido: {rnc}"


cases = []

# Positivos
cases.append({
    "name": "Cliente RNC válido, venta gravada",
    "expected": "accept",
    "invoice_overrides": {"montoExento": 0.00},
    "assertions": [assert_xsd_ok, assert_itbis_equals_18pct, assert_totales_consistentes, assert_rnc_valido],
})

cases.append({
    "name": "Venta exenta (ITBIS=0)",
    "expected": "accept",
    "invoice_overrides": {"subtotal": 1000, "total": 1000, "totalITBIS": 0, "montoExento": 1000},
    "assertions": [assert_xsd_ok, assert_itbis_es_cero, assert_totales_consistentes],
})

cases.append({
    "name": "Venta mixta (gravada + exenta)",
    "expected": "accept",
    "invoice_overrides": {
        "subtotal": 2000, "total": 2180, "totalITBIS": 180, "montoExento": 1000,
        "items": [
            {"name": "Producto gravado", "unit": "Unidad", "quantity": 1, "price": 1000, "subtotal": 1000, "type": "producto"},
            {"name": "Producto exento", "unit": "Unidad", "quantity": 1, "price": 1000, "subtotal": 1000, "type": "producto"},
        ],
    },
    "assertions": [assert_xsd_ok, assert_totales_consistentes],
})

cases.append({
    "name": "Descuento global antes de ITBIS",
    "expected": "accept",
    "invoice_overrides": {"subtotal": 800, "total": 944, "totalITBIS": 144, "montoExento": 0},
    "assertions": [assert_xsd_ok, assert_itbis_equals_18pct, assert_totales_consistentes],
})

cases.append({
    "name": "Múltiples líneas (5)",
    "expected": "accept",
    "invoice_overrides": {
        "items": [
            {"name": "Item 1", "unit": "Unidad", "quantity": 1, "price": 200, "subtotal": 200, "type": "producto"},
            {"name": "Item 2", "unit": "Unidad", "quantity": 2, "price": 150, "subtotal": 300, "type": "producto"},
            {"name": "Item 3", "unit": "Unidad", "quantity": 3, "price": 100, "subtotal": 300, "type": "producto"},
            {"name": "Item 4", "unit": "Unidad", "quantity": 1, "price": 100, "subtotal": 100, "type": "producto"},
            {"name": "Item 5", "unit": "Unidad", "quantity": 1, "price": 100, "subtotal": 100, "type": "producto"},
        ],
        "subtotal": 1000, "total": 1180, "totalITBIS": 180, "montoExento": 0,
    },
    "assertions": [assert_xsd_ok, assert_itbis_equals_18pct, assert_totales_consistentes],
})

# Negativos
cases.append({
    "name": "ITBIS incorrecto en producto exento",
    "expected": "reject",
    "invoice_overrides": {"totalITBIS": 180, "montoExento": 1000},
    "assertions": [
        lambda r: float(r["doc"].findtext(".//TotalITBIS", "0")) == 0,
    ],
})

cases.append({
    "name": "Totales inconsistentes",
    "expected": "reject",
    "invoice_overrides": {"subtotal": 1000, "total": 9999, "totalITBIS": 180, "montoExento": 0},
    "assertions": [assert_totales_consistentes],
})

cases.append({
    "name": "RNC con formato inválido",
    "expected": "reject",
    "invoice_overrides": {"clientRNC": "ABC-123"},
    "assertions": [assert_rnc_valido],
})


if __name__ == "__main__":
    run_battery(TIPO, cases)
