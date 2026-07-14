"""
Batería E33 — Nota de Débito

Positivos:
  1. Incremento parcial sobre factura existente
  2. Incremento total

Negativos:
  3. Factura original inexistente (NCFModificado inválido)
  4. Monto negativo
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_cases_base import base_invoice, run_battery

TIPO = "33"


def assert_xsd_ok(r):
    assert len(r["xsd_errors"]) == 0, f"XSD: {r['xsd_errors']}"

def assert_itbis_equals_18pct(r):
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    gravado = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    expected = round(gravado * 0.18, 2)
    assert abs(itbis - expected) <= 1.0, f"ITBIS {itbis} ≠ 18% de {gravado}"

def assert_totales_consistentes(r):
    gravado = float(r["doc"].findtext(".//MontoGravadoTotal", "0"))
    total = float(r["doc"].findtext(".//MontoTotal", "0"))
    itbis = float(r["doc"].findtext(".//TotalITBIS", "0"))
    assert abs(total - (gravado + itbis)) <= 1.0, f"Total {total} ≠ {gravado}+{itbis}"

def assert_monto_positivo(r):
    total = float(r["doc"].findtext(".//MontoTotal", "0"))
    assert total >= 0, f"Monto negativo: {total}"

def assert_ncf_referencia_valido(r):
    ncf = r["doc"].findtext(".//NCFModificado", "")
    assert bool(re.match(r"^E\d{2}\d{10}$", ncf)), f"NCF referencia inválido: {ncf}"


cases = []

# Positivos
cases.append({
    "name": "Incremento parcial",
    "expected": "accept",
    "invoice_overrides": {"subtotal": 500, "total": 590, "totalITBIS": 90, "montoExento": 0},
    "assertions": [assert_xsd_ok, assert_itbis_equals_18pct, assert_totales_consistentes, assert_monto_positivo, assert_ncf_referencia_valido],
})

cases.append({
    "name": "Incremento total (duplicar monto)",
    "expected": "accept",
    "invoice_overrides": {"subtotal": 2000, "total": 2360, "totalITBIS": 360, "montoExento": 0},
    "assertions": [assert_xsd_ok, assert_itbis_equals_18pct, assert_totales_consistentes, assert_monto_positivo],
})

# Negativos
cases.append({
    "name": "NCFModificado con formato inválido",
    "expected": "reject",
    "invoice_overrides": {"ncfModificado": "BAD-REF"},
    "assertions": [assert_ncf_referencia_valido],
})

cases.append({
    "name": "Monto negativo en total",
    "expected": "reject",
    "invoice_overrides": {"subtotal": -500, "total": -590, "totalITBIS": -90, "montoExento": 0},
    "assertions": [assert_monto_positivo],
})


if __name__ == "__main__":
    run_battery(TIPO, cases)
