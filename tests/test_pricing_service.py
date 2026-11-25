"""Pruebas unitarias para PricingService (precio por monto o markup sobre costo).

Cubre:
- Markup cero, positivo y redondeo monetario.
- Costo cero y costo decimal.
- Rechazo de porcentaje negativo y por encima del máximo.
- Modo monto (precio explícito) y rechazo de precios negativos.
- Normalización de modalidad con sinónimos.
- Persistencia/normalización de campos en DatabaseService.save_item.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.services.pricing_service import (
    PricingService,
    PricingError,
    PRICING_MODE_AMOUNT,
    PRICING_MODE_MARKUP,
)
from app.services import db_service
from app.services.db_service import DatabaseService


# ---------------------------------------------------------------------------
# Cálculo por markup
# ---------------------------------------------------------------------------

def test_markup_ten_percent():
    assert PricingService.compute_price(100, PRICING_MODE_MARKUP, markup_percentage=10) == Decimal("110.00")


def test_markup_zero():
    assert PricingService.compute_price(100, PRICING_MODE_MARKUP, markup_percentage=0) == Decimal("100.00")


def test_markup_zero_cost():
    assert PricingService.compute_price(0, PRICING_MODE_MARKUP, markup_percentage=25) == Decimal("0.00")


def test_markup_decimal_cost():
    assert PricingService.compute_price("99.99", PRICING_MODE_MARKUP, markup_percentage=10) == Decimal("109.99")


def test_markup_multiple_decimals_rounding():
    # 100 × 1.075 = 107.50
    assert PricingService.compute_price(100, PRICING_MODE_MARKUP, markup_percentage=7.5) == Decimal("107.50")


def test_markup_rounds_half_up():
    # 33.33 × 1.10 = 36.663 -> 36.66
    assert PricingService.compute_price("33.33", PRICING_MODE_MARKUP, markup_percentage=10) == Decimal("36.66")


def test_markup_accepts_string_percentage():
    assert PricingService.compute_price(200, PRICING_MODE_MARKUP, markup_percentage="10") == Decimal("220.00")


def test_markup_negative_percentage_rejected():
    with pytest.raises(PricingError):
        PricingService.compute_price(100, PRICING_MODE_MARKUP, markup_percentage=-5)


def test_markup_above_max_rejected():
    with pytest.raises(PricingError):
        PricingService.compute_price(100, PRICING_MODE_MARKUP, markup_percentage=1001)


def test_markup_negative_cost_rejected():
    with pytest.raises(PricingError):
        PricingService.compute_price(-10, PRICING_MODE_MARKUP, markup_percentage=10)


# ---------------------------------------------------------------------------
# Modo monto (precio explícito)
# ---------------------------------------------------------------------------

def test_amount_returns_explicit_price():
    assert PricingService.compute_price(0, PRICING_MODE_AMOUNT, explicit_price=250.00) == Decimal("250.00")


def test_amount_rounds_to_two_decimals():
    assert PricingService.compute_price(0, PRICING_MODE_AMOUNT, explicit_price="99.999") == Decimal("100.00")


def test_amount_negative_rejected():
    with pytest.raises(PricingError):
        PricingService.compute_price(0, PRICING_MODE_AMOUNT, explicit_price=-1)


# ---------------------------------------------------------------------------
# Normalización de modalidad
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "", "amount", "monto", "fijo", "desconocido"])
def test_normalize_mode_defaults_to_amount(value):
    assert PricingService.normalize_mode(value) == PRICING_MODE_AMOUNT


@pytest.mark.parametrize("value", ["markup", "porcentaje", "porciento", "percentage", "percent", "%"])
def test_normalize_mode_markup_synonyms(value):
    assert PricingService.normalize_mode(value) == PRICING_MODE_MARKUP


def test_resolve_returns_detail():
    result = PricingService.resolve(100, "porcentaje", markup_percentage=10)
    assert result["pricingMode"] == PRICING_MODE_MARKUP
    assert result["markupPercentage"] == 10.0
    assert result["price"] == 110.0


# ---------------------------------------------------------------------------
# Persistencia / normalización en save_item
# ---------------------------------------------------------------------------

def test_save_item_normalizes_pricing_fields():
    with patch("app.services.db_service.firebase_initialized", False):
        saved = DatabaseService.save_item(
            "owner-uid", "item-1",
            {"name": "A", "price": 110.0, "costPrice": 100.0,
             "pricingMode": "markup", "markupPercentage": "10"},
            company_id="", sandbox=True,
        )
    assert saved["pricingMode"] == "markup"
    assert saved["markupPercentage"] == 10.0
    assert saved["priceSource"] == ""
    assert saved["priceCalculationBase"] == ""


def test_save_item_defaults_pricing_mode_to_amount():
    with patch("app.services.db_service.firebase_initialized", False):
        saved = DatabaseService.save_item(
            "owner-uid", "item-2",
            {"name": "B", "price": 50.0},
            company_id="", sandbox=True,
        )
    assert saved["pricingMode"] == "amount"
    assert saved["markupPercentage"] is None


# ---------------------------------------------------------------------------
# Lectura del catálogo: los campos de precio no deben perderse en la proyección
# ---------------------------------------------------------------------------

class _FakeItemDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeItemColl:
    def __init__(self, docs):
        self._docs = docs

    def limit(self, _n):
        return self

    def get(self):
        return self._docs


def _fake_company_coll(**kwargs):
    return _FakeItemColl([
        _FakeItemDoc("item-markup", {
            "name": "A", "price": 110.0, "costPrice": 100.0,
            "pricingMode": "markup", "markupPercentage": 10.0,
            "priceSource": "markup", "priceCalculationBase": "costPrice",
        }),
        _FakeItemDoc("item-amount", {
            "name": "B", "price": 250.0, "costPrice": 150.0,
            "pricingMode": "amount", "markupPercentage": None,
            "priceSource": "manual", "priceCalculationBase": "",
        }),
    ])


def test_get_items_preserves_pricing_fields():
    with patch.object(db_service, "firebase_initialized", True), \
         patch.object(db_service, "_company_coll", side_effect=_fake_company_coll):
        items = db_service._cached_items.uncached("owner-uid", True, company_id="c1")

    by_id = {i["id"]: i for i in items}
    assert by_id["item-markup"]["pricingMode"] == "markup"
    assert by_id["item-markup"]["markupPercentage"] == 10.0
    assert by_id["item-markup"]["priceSource"] == "markup"
    assert by_id["item-markup"]["priceCalculationBase"] == "costPrice"

    assert by_id["item-amount"]["pricingMode"] == "amount"
    assert by_id["item-amount"]["markupPercentage"] is None
    assert by_id["item-amount"]["priceSource"] == "manual"
