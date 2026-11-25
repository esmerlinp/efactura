"""Pruebas de existencias iniciales (movimiento SALDO_INICIAL y previsualización)."""

import pytest

from app.services.inventory_transaction_service import InventoryTransactionService
from app.services.initial_stock_service import InitialStockService
from app.services.product_import_preview import build_preview


def test_saldo_inicial_reason_constant_exists():
    assert InventoryTransactionService.REASON_SALDO_INICIAL == "SALDO_INICIAL"


def test_build_tx_fields():
    tx = InitialStockService.build_tx(
        "company-1", "item-1", "wh-1", 150, 100.0, "batch-1", 2,
        performed_by="user@x.com", effective_date="2026-01-01T00:00:00",
    )
    assert tx["type"] == "ENTRADA"
    assert tx["reason"] == "SALDO_INICIAL"
    assert tx["referenceType"] == "PRODUCT_IMPORT"
    assert tx["referenceId"] == "batch-1:2"
    assert tx["destinationWarehouseId"] == "wh-1"
    assert tx["quantity"] == 150.0
    assert tx["unitCost"] == 100.0
    assert tx["performedBy"] == "user@x.com"
    assert tx["date"] == "2026-01-01T00:00:00"


def test_build_tx_idempotency_key_deterministic():
    k1 = InitialStockService.build_idempotency_key("c1", "b1", 2)
    k2 = InitialStockService.build_idempotency_key("c1", "b1", 2)
    assert k1 == k2
    assert k1 == "c1|PRODUCT_IMPORT|b1:2|ENTRADA"


def test_build_tx_includes_lot():
    tx = InitialStockService.build_tx(
        "c1", "i1", "w1", 5, 10.0, "b1", 1, lot_number="L-1", expiration_date="2027-01-01")
    assert tx["lotNumber"] == "L-1"
    assert tx["expirationDate"] == "2027-01-01"


def test_resolve_warehouse_by_id():
    warehouses = [{"id": "w1", "name": "Principal"}]
    assert InitialStockService.resolve_warehouse_id("w1", warehouses) == "w1"


def test_resolve_warehouse_by_name():
    warehouses = [{"id": "w1", "name": "Principal"}]
    assert InitialStockService.resolve_warehouse_id("Principal", warehouses) == "w1"


def test_resolve_warehouse_missing_returns_none():
    assert InitialStockService.resolve_warehouse_id("nope", [{"id": "w1", "name": "Principal"}]) is None


def test_preview_counts_initial_stock():
    rows = [{
        "row": 2, "name": "A", "code": "P1", "costPrice": "100",
        "pricingMode": "MONTO", "price": "120",
        "initialStock": "150", "warehouseId": "w1", "initialUnitCost": "90",
    }]
    result = build_preview(rows)
    assert result["summary"]["inventoryMovements"] == 1
    assert result["summary"]["totalUnits"] == 150.0
    assert result["summary"]["totalInventoryValue"] == 13500.0


def test_preview_initial_stock_uses_cost_price_as_fallback():
    rows = [{
        "row": 2, "name": "A", "code": "P1", "costPrice": "100",
        "pricingMode": "MONTO", "price": "120",
        "initialStock": "10", "warehouseId": "w1",
    }]
    result = build_preview(rows)
    assert result["summary"]["totalInventoryValue"] == 1000.0


def test_preview_initial_stock_requires_warehouse():
    rows = [{
        "row": 2, "name": "A", "code": "P1", "costPrice": "100",
        "pricingMode": "MONTO", "price": "120", "initialStock": "10",
    }]
    result = build_preview(rows)
    assert result["rows"][0]["action"] == "error"
    assert any(e["column"] == "warehouseId" for e in result["rows"][0]["errors"])


def test_preview_zero_initial_stock_no_movement():
    rows = [{
        "row": 2, "name": "A", "code": "P1", "costPrice": "100",
        "pricingMode": "MONTO", "price": "120", "initialStock": "0",
    }]
    result = build_preview(rows)
    assert result["summary"]["inventoryMovements"] == 0
