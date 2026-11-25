"""Pruebas de previsualización y validación de importación (sin escritura).

Cubre la acción por fila (new/update/duplicate/error), detección de duplicados
dentro del archivo, resumen de conteos y compatibilidad con plantillas antiguas.
"""

import pytest

from app.services.product_import_preview import (
    build_preview,
    sanitize_float,
    resolve_import_price,
)


def _row(row_num, **fields):
    row = {"row": row_num}
    row.update(fields)
    return row


def test_preview_new_product():
    rows = [_row(2, name="Producto A", code="P1", costPrice="100", pricingMode="MONTO", price="120")]
    result = build_preview(rows)
    assert result["summary"]["totalRows"] == 1
    assert result["summary"]["newProducts"] == 1
    assert result["rows"][0]["action"] == "new"
    assert result["rows"][0]["price"] == 120.0


def test_preview_update_existing():
    rows = [_row(2, name="Producto A", code="P1", costPrice="100", pricingMode="MONTO", price="120")]
    result = build_preview(rows, existing_codes={"p1"})
    assert result["summary"]["updatedProducts"] == 1
    assert result["rows"][0]["action"] == "update"


def test_preview_duplicate_within_file():
    rows = [
        _row(2, name="A", code="P1", price="10"),
        _row(3, name="B", code="P1", price="20"),
    ]
    result = build_preview(rows)
    assert result["summary"]["newProducts"] == 1
    assert result["summary"]["duplicateRows"] == 1
    assert result["rows"][1]["action"] == "duplicate"


def test_preview_error_on_missing_name():
    rows = [_row(2, name="", code="P1", price="10")]
    result = build_preview(rows)
    assert result["summary"]["errorRows"] == 1
    assert result["rows"][0]["action"] == "error"
    assert any(e["column"] == "name" for e in result["rows"][0]["errors"])


def test_preview_error_on_invalid_price_column():
    rows = [_row(2, name="A", code="P1", pricingMode="PORCENTAJE", costPrice="0", markupPercentage="10")]
    result = build_preview(rows)
    assert result["rows"][0]["action"] == "error"
    assert any(e["column"] == "costPrice" for e in result["rows"][0]["errors"])


def test_preview_markup_computes_price():
    rows = [_row(2, name="A", code="P1", costPrice="100", pricingMode="PORCENTAJE", markupPercentage="10")]
    result = build_preview(rows)
    assert result["rows"][0]["price"] == 110.0
    assert result["rows"][0]["action"] == "new"


def test_preview_valid_rows_summary():
    rows = [
        _row(2, name="A", code="P1", price="10"),
        _row(3, name="B", code="P2", price="20"),
    ]
    result = build_preview(rows)
    assert result["summary"]["validRows"] == 2
    assert result["summary"]["errorRows"] == 0


def test_preview_barcode_duplicate_warning():
    rows = [
        _row(2, name="A", code="P1", barcode="111", price="10"),
        _row(3, name="B", code="P2", barcode="111", price="20"),
    ]
    result = build_preview(rows)
    assert result["summary"]["warningRows"] == 1


def test_sanitize_float_handles_formats():
    assert sanitize_float("RD$1,234.56") == 1234.56
    assert sanitize_float("$ 10,5") == 10.5
    assert sanitize_float("") == 0.0
    assert sanitize_float("", None) is None


def test_resolve_import_price_amount_negative():
    price, col, reason = resolve_import_price(0.0, "MONTO", "", "-3")
    assert price is None
    assert col == "price"
