"""Pruebas del script de backfill de valoración de inventario."""

import importlib.util
import os
import sys

import pytest

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "backfill_inventory_valuation.py"
)


@pytest.fixture(scope="module")
def backfill_mod():
    spec = importlib.util.spec_from_file_location("backfill_inventory_valuation", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    spec.loader.exec_module(mod)
    return mod


def test_last_purchase_cost_picks_latest_compra(backfill_mod):
    txs = [
        {"itemId": "it-1", "type": "ENTRADA", "reason": "COMPRA", "unitCost": 100.0, "date": "2026-01-01"},
        {"itemId": "it-1", "type": "ENTRADA", "reason": "COMPRA", "unitCost": 200.0, "date": "2026-02-01"},
        {"itemId": "it-1", "type": "SALIDA", "reason": "VENTA", "unitCost": 150.0, "date": "2026-03-01"},
    ]
    assert backfill_mod._last_purchase_cost(txs, "it-1") == 200.0


def test_last_purchase_cost_ignores_non_compra_and_other_items(backfill_mod):
    txs = [
        {"itemId": "it-1", "type": "ENTRADA", "reason": "DEVOLUCION_CLIENTE", "unitCost": 50.0, "date": "2026-01-01"},
        {"itemId": "it-2", "type": "ENTRADA", "reason": "COMPRA", "unitCost": 999.0, "date": "2026-02-01"},
    ]
    assert backfill_mod._last_purchase_cost(txs, "it-1") == 0.0


def test_ledger_value_by_warehouse(backfill_mod):
    ledger = [
        {"itemId": "it-1", "warehouseId": "wh-a", "balanceQty": 10.0, "unitCost": 100.0},
        {"itemId": "it-1", "warehouseId": "wh-a", "balanceQty": 5.0, "unitCost": 200.0},
        {"itemId": "it-1", "warehouseId": "wh-b", "balanceQty": 3.0, "unitCost": 50.0},
        {"itemId": "it-1", "warehouseId": "wh-a", "balanceQty": 0.0, "unitCost": 999.0},  # agotada: ignorada
    ]
    total_value, total_qty = backfill_mod._ledger_value(ledger, "it-1", "wh-a")
    assert total_value == 2000.0  # 10×100 + 5×200
    assert total_qty == 15.0
