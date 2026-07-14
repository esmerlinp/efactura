"""
Batería E34 — Nota de Crédito (prioridad máxima)

Casos positivos:
  1. Devolución parcial (1 línea de 3)
  2. Devolución total (todas las líneas)
  3. Descuento posterior (ajuste comercial)

Casos negativos:
  4. Referencia inexistente (NCFModificado inválido)
  5. Monto superior al documento original
  6. ITBIS recalculado incorrectamente

Uso: python3 tests/test_cases_e34.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_cases_base import (
    BASE_COMPANY, base_invoice, load_xsd, build_and_validate, run_battery, DgiiXmlBuilder
)

TIPO = "34"


def assert_xsd_ok(result):
    assert len(result["xsd_errors"]) == 0, f"XSD errors: {result['xsd_errors']}"


def assert_has_element(result, tag, expected_text=None):
    doc = result["doc"]
    elem = doc.find(f".//{tag}")
    assert elem is not None, f"Missing element: {tag}"
    if expected_text is not None:
        assert elem.text == expected_text, f"{tag}: expected '{expected_text}', got '{elem.text}'"


def assert_nota_credito_monto_no_mayor(result):
    """El monto total de la NC no debe exceder el monto del documento original referido."""
    total_nc = float(result["doc"].findtext(".//MontoTotal", "0"))
    # Simulamos que el documento original era de RD$1,180.00 (como nuestra factura base)
    monto_original = 1180.00
    assert total_nc <= monto_original, (
        f"NC total ({total_nc}) excede el original ({monto_original})"
    )


def assert_itbis_recalculado_correcto(result):
    """El ITBIS de la NC debe ser proporcional a las líneas incluidas."""
    total_itbis = float(result["doc"].findtext(".//TotalITBIS", "0"))
    monto_gravado = float(result["doc"].findtext(".//MontoGravadoTotal", "0"))
    # Para tasa 18%: ITBIS debe ser ≈ 18% del monto gravado (con tolerancia RD$1)
    expected_itbis = round(monto_gravado * 0.18, 2)
    assert abs(total_itbis - expected_itbis) <= 1.0, (
        f"ITBIS {total_itbis} no coincide con 18% de {monto_gravado} (expected ~{expected_itbis})"
    )


def assert_indicador_nota_credito_presente(result):
    assert_has_element(result, "IndicadorNotaCredito", "1")


def assert_tipoeCF_es_34(result):
    assert_has_element(result, "TipoeCF", "34")


# ---------------------------------------------------------------------------
# Casos positivos
# ---------------------------------------------------------------------------

cases = []

cases.append({
    "name": "Devolución parcial — 1 línea de 3",
    "expected": "accept",
    "invoice_overrides": {
        "subtotal": 500.00,
        "total": 590.00,
        "totalITBIS": 90.00,
        "montoExento": 0.00,
        "codigoModificacion": "1",
        "ncfModificado": "E310000000050",
        "items": [
            {"name": "Producto devuelto", "unit": "Unidad", "quantity": 1,
             "price": 500.00, "subtotal": 500.00, "type": "producto"},
        ],
    },
    "assertions": [
        assert_xsd_ok,
        assert_tipoeCF_es_34,
        assert_indicador_nota_credito_presente,
        assert_nota_credito_monto_no_mayor,
        assert_itbis_recalculado_correcto,
    ],
})

cases.append({
    "name": "Devolución total — todas las líneas",
    "expected": "accept",
    "invoice_overrides": {
        "subtotal": 1000.00,
        "total": 1180.00,
        "totalITBIS": 180.00,
        "codigoModificacion": "2",
        "ncfModificado": "E310000000051",
        "items": [
            {"name": "Producto A", "unit": "Unidad", "quantity": 1,
             "price": 600.00, "subtotal": 600.00, "type": "producto"},
            {"name": "Producto B", "unit": "Unidad", "quantity": 1,
             "price": 400.00, "subtotal": 400.00, "type": "producto"},
        ],
    },
    "assertions": [
        assert_xsd_ok,
        assert_tipoeCF_es_34,
        assert_indicador_nota_credito_presente,
        assert_nota_credito_monto_no_mayor,
        assert_itbis_recalculado_correcto,
    ],
})

cases.append({
    "name": "Descuento posterior — ajuste comercial",
    "expected": "accept",
    "invoice_overrides": {
        "subtotal": 200.00,
        "total": 236.00,
        "totalITBIS": 36.00,
        "codigoModificacion": "3",
        "ncfModificado": "E310000000052",
        "items": [
            {"name": "Descuento comercial", "unit": "Servicio", "quantity": 1,
             "price": 200.00, "subtotal": 200.00, "type": "servicio"},
        ],
    },
    "assertions": [
        assert_xsd_ok,
        assert_tipoeCF_es_34,
        assert_indicador_nota_credito_presente,
        assert_nota_credito_monto_no_mayor,
        assert_itbis_recalculado_correcto,
    ],
})

# ---------------------------------------------------------------------------
# Casos negativos
# ---------------------------------------------------------------------------

cases.append({
    "name": "NCFModificado con formato inválido",
    "expected": "reject",
    "invoice_overrides": {
        "ncfModificado": "INVALIDO-999",
        "subtotal": 500.00,
        "total": 590.00,
    },
    "assertions": [
        lambda r: assert_has_element(r, "NCFModificado"),
        # El NCF debe tener formato E{N} + 10 dígitos
        lambda r: bool(__import__("re").match(r"^E\d{2}\d{10}$",
                         r["doc"].findtext(".//NCFModificado", ""))),
    ],
})

cases.append({
    "name": "Monto superior al original",
    "expected": "reject",
    "invoice_overrides": {
        "subtotal": 2000.00,
        "total": 2360.00,
        "totalITBIS": 360.00,
        "codigoModificacion": "1",
        "ncfModificado": "E310000000053",
        "items": [
            {"name": "Producto caro", "unit": "Unidad", "quantity": 1,
             "price": 2000.00, "subtotal": 2000.00, "type": "producto"},
        ],
    },
    "assertions": [
        assert_nota_credito_monto_no_mayor,
    ],
})

cases.append({
    "name": "ITBIS recalculado incorrectamente",
    "expected": "reject",
    "invoice_overrides": {
        "subtotal": 500.00,
        "total": 590.00,
        "totalITBIS": 50.00,  # Debería ser 90.00 (18% de 500)
        "codigoModificacion": "1",
        "ncfModificado": "E310000000054",
        "items": [
            {"name": "Producto con ITBIS malo", "unit": "Unidad", "quantity": 1,
             "price": 500.00, "subtotal": 500.00, "type": "producto"},
        ],
    },
    "assertions": [
        assert_itbis_recalculado_correcto,
    ],
})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_battery(TIPO, cases)
