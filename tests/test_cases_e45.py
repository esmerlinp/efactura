"""
Batería E45 — Gubernamental

Positivos:
  1. Institución pública con RNC gubernamental

Negativos:
  2. Cliente privado usando E45
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_cases_base import base_invoice, run_battery

TIPO = "45"


def assert_xsd_ok(r):
    assert len(r["xsd_errors"]) == 0, f"XSD: {r['xsd_errors']}"

def assert_itbis_equals_18pct(r):
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    gravado = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    expected = round(gravado * 0.18, 2)
    assert abs(itbis - expected) <= 1.0

def assert_totales_consistentes(r):
    gravado = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    exento = float(r["doc"].findtext(".//MontoExento", "0"))
    total = float(r["doc"].findtext(".//MontoTotal", "0"))
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    assert abs(total - (gravado + exento + itbis)) <= 1.0


cases = []

# Positivos
cases.append({
    "name": "Institución pública RNG gubernamental",
    "expected": "accept",
    "invoice_overrides": {"clientRNC": "401000000", "razonSocial": "MINISTERIO DE HACIENDA"},
    "assertions": [assert_xsd_ok, assert_itbis_equals_18pct, assert_totales_consistentes],
})

# Negativos
cases.append({
    "name": "RNC privado en E45",
    "expected": "reject",
    "invoice_overrides": {"clientRNC": "131555555", "razonSocial": "EMPRESA PRIVADA SRL"},
    "assertions": [
        # Los RNC gubernamentales empiezan con 4
        lambda r: r["invoice"]["clientRNC"].startswith("4"),
    ],
})


if __name__ == "__main__":
    run_battery(TIPO, cases)
