"""
Batería E32 — Factura de Consumo

Positivos:
  1. Consumidor final (sin identificación)
  2. Con cédula
  3. Venta menor al límite DGII (< RD$250,000)
  4. Con RNC opcional (monto menor)

Negativos:
  5. Monto > RD$250,000 sin RNC
  6. ITBIS inconsistente
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_cases_base import base_invoice, run_battery

TIPO = "32"


def assert_xsd_ok(r):
    assert len(r["xsd_errors"]) == 0, f"XSD: {r['xsd_errors']}"

def assert_no_rnc(r):
    rnc_elem = r["doc"].find(".//RNCComprador")
    assert rnc_elem is None or rnc_elem.text == "", f"RNC presente en consumidor final"

def assert_itbis_equals_18pct(r):
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    gravado = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    expected = round(gravado * 0.18, 2)
    assert abs(itbis - expected) <= 1.0, f"ITBIS {itbis} ≠ 18% de {gravado}"

def assert_monto_menor_250k(r):
    total = float(r["invoice"].get("total", 0))
    assert total < 250000, f"Monto {total} excede límite RD$250,000 sin RNC"

def assert_totales_consistentes(r):
    gravado = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    total = float(r["doc"].findtext(".//MontoTotal", "0"))
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    assert abs(total - (gravado + itbis)) <= 1.0, f"Total {total} ≠ gravado {gravado} + ITBIS {itbis}"


cases = []

# Positivos
cases.append({
    "name": "Consumidor final sin identificación",
    "expected": "accept",
    "invoice_overrides": {"clientRNC": "", "razonSocial": "", "total": 500, "subtotal": 500, "totalITBIS": 0, "montoExento": 500},
    "assertions": [assert_xsd_ok, assert_no_rnc, assert_monto_menor_250k],
})

cases.append({
    "name": "Con cédula (consumidor identificado)",
    "expected": "accept",
    "invoice_overrides": {"clientRNC": "00112345678", "razonSocial": "JUAN PÉREZ", "total": 25000},
    "assertions": [assert_xsd_ok, assert_monto_menor_250k],
})

cases.append({
    "name": "Venta menor al límite DGII",
    "expected": "accept",
    "invoice_overrides": {"total": 1000, "razonSocial": "Consumidor Final", "clientRNC": ""},
    "assertions": [assert_xsd_ok, assert_monto_menor_250k, assert_no_rnc],
})

# Negativos
cases.append({
    "name": "Monto > RD$250,000 sin RNC",
    "expected": "reject",
    "invoice_overrides": {"total": 300000, "subtotal": 300000, "totalITBIS": 0, "montoExento": 300000, "clientRNC": "", "razonSocial": ""},
    "assertions": [assert_monto_menor_250k],
})

cases.append({
    "name": "ITBIS inconsistente con monto",
    "expected": "reject",
    "invoice_overrides": {"total": 1180, "subtotal": 1000, "totalITBIS": 50, "montoExento": 0},
    "assertions": [assert_itbis_equals_18pct],
})


if __name__ == "__main__":
    run_battery(TIPO, cases)
