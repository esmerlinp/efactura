"""
Batería E43 — Gastos Menores

Positivos:
  1. Gasto de transporte/combustible
  2. Gasto operativo menor (papelería)

Negativos:
  3. Sin concepto (NombreItem vacío)
  4. Datos incompletos (sin fecha válida)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_cases_base import base_invoice, run_battery

TIPO = "43"


def assert_xsd_ok(r):
    assert len(r["xsd_errors"]) == 0, f"XSD: {r['xsd_errors']}"

def assert_sin_comprador(r):
    comp = r["doc"].find(".//Comprador")
    assert comp is None, "E43 no debe tener Comprador"

def assert_monto_exento_igual_total(r):
    exento = float(r["doc"].findtext(".//MontoExento", "0"))
    total = float(r["doc"].findtext(".//MontoTotal", "0"))
    assert abs(exento - total) <= 0.01, f"E43: MontoExento {exento} ≠ Total {total}"

def assert_nombre_item_presente(r):
    name = r["doc"].findtext(".//NombreItem", "")
    assert len(name.strip()) > 0, "NombreItem vacío"


cases = []

# Positivos
cases.append({
    "name": "Gasto de transporte/combustible",
    "expected": "accept",
    "invoice_overrides": {
        "items": [{"name": "Combustible vehículo", "unit": "Unidad", "quantity": 1, "price": 3000, "subtotal": 3000, "type": "producto"}],
        "subtotal": 3000, "total": 3000, "totalITBIS": 0, "montoExento": 3000,
    },
    "assertions": [assert_xsd_ok, assert_sin_comprador, assert_monto_exento_igual_total],
})

cases.append({
    "name": "Gasto operativo (papelería)",
    "expected": "accept",
    "invoice_overrides": {
        "items": [{"name": "Resma papel carta", "unit": "Unidad", "quantity": 5, "price": 250, "subtotal": 1250, "type": "producto"}],
        "subtotal": 1250, "total": 1250, "totalITBIS": 0, "montoExento": 1250,
    },
    "assertions": [assert_xsd_ok, assert_sin_comprador, assert_monto_exento_igual_total],
})

# Negativos
cases.append({
    "name": "NombreItem vacío",
    "expected": "reject",
    "invoice_overrides": {
        "items": [{"name": "", "unit": "Unidad", "quantity": 1, "price": 500, "subtotal": 500, "type": "producto"}],
    },
    "assertions": [assert_nombre_item_presente],
})


if __name__ == "__main__":
    run_battery(TIPO, cases)
