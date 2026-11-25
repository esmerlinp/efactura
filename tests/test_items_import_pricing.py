"""Pruebas de importación de precios (modalidad monto / porcentaje sobre costo).

Cubre la resolución de precio de una fila de importación, validación por
columna y compatibilidad con plantillas antiguas (monto por defecto).
"""

import pytest

from app.web.items_import import (
    _resolve_import_price,
    _sanitize_float_import,
    ITEM_CSV_FIELDS,
    ITEM_CSV_HEADERS,
)


def test_import_markup_computes_price():
    price, col, reason = _resolve_import_price(100.0, "PORCENTAJE", "10", "")
    assert price == 110.0
    assert col is None
    assert reason is None


def test_import_markup_accepts_synonym_mode():
    price, col, reason = _resolve_import_price(200.0, "porcentaje", "10", "")
    assert price == 220.0
    assert col is None


def test_import_markup_missing_cost():
    price, col, reason = _resolve_import_price(0.0, "PORCENTAJE", "10", "")
    assert price is None
    assert col == "costPrice"
    assert reason


def test_import_markup_missing_percentage():
    price, col, reason = _resolve_import_price(100.0, "PORCENTAJE", "", "")
    assert price is None
    assert col == "markupPercentage"


def test_import_markup_invalid_percentage_text():
    price, col, reason = _resolve_import_price(100.0, "PORCENTAJE", "abc", "")
    assert price is None
    assert col == "markupPercentage"


def test_import_markup_negative_percentage():
    price, col, reason = _resolve_import_price(100.0, "PORCENTAJE", "-5", "")
    assert price is None
    assert col == "markupPercentage"


def test_import_amount_explicit_price():
    price, col, reason = _resolve_import_price(0.0, "MONTO", "", "250.00")
    assert price == 250.0
    assert col is None


def test_import_amount_negative_price():
    price, col, reason = _resolve_import_price(0.0, "MONTO", "", "-5")
    assert price is None
    assert col == "price"


def test_import_amount_default_when_no_mode():
    # Plantilla antigua sin columna de modalidad -> monto.
    price, col, reason = _resolve_import_price(0.0, "", "", "3500.00")
    assert price == 3500.0
    assert col is None


def test_import_sanitize_float_handles_rd():
    assert _sanitize_float_import("RD$1,234.56") == 1234.56


def test_template_includes_pricing_fields():
    assert "pricingMode" in ITEM_CSV_HEADERS
    assert "markupPercentage" in ITEM_CSV_HEADERS
    field_ids = [f[0].lstrip("*") for f in ITEM_CSV_FIELDS]
    assert "pricingMode" in field_ids
    assert "markupPercentage" in field_ids
    # price y name siguen siendo obligatorios para compatibilidad.
    required = [f[0].lstrip("*") for f in ITEM_CSV_FIELDS if f[2]]
    assert "name" in required
    assert "price" in required
