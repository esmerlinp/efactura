# tests/test_inventory_moving_average.py
"""
Pruebas del costo promedio ponderado móvil (Fase 1 de valoración de inventario).

Cubre los escenarios obligatorios del requerimiento:
 1. Entrada con el mismo costo de referencia.
 2. Entrada con costo superior.
 3. Entrada con costo inferior.
 4. Múltiples entradas con costos diferentes.
 5. Entrada con descuentos.
 6. Entrada con ITBIS recuperable (no forma parte del costo).
 7. Entrada con costos adicionales atribuibles.
 8. Salida parcial de existencias.
 9. Devolución de mercancía (reingreso al costo de valoración).
10. Anulación / reversión de una entrada.
11. Entradas simultáneas del mismo producto.
12. Existencias iniciales en cero.
13. Existencias en diferentes almacenes (aislamiento por almacén).
14. Precisión decimal y redondeos.
15. Integridad inventario ↔ contabilidad (totalValue = qty × unitCost).

También verifica que el costo de referencia (`costPrice`) NUNCA se sobrescribe.
"""

from decimal import Decimal

import pytest
from unittest.mock import patch

from app.services.inventory_transaction_service import (
    InventoryTransactionService,
    InsufficientStockError,
)
from app.services.inventory_valuation_service import InventoryValuationService


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PRUEBAS PURAS DEL MOTOR DE VALORACIÓN (sin Firestore)
# ═══════════════════════════════════════════════════════════════════════════════

def test_moving_average_formula_required_example():
    """Ejemplo obligatorio: 10×5000 + 10×6000 → 20 u, RD$110,000, promedio RD$5,500."""
    mv = InventoryValuationService.moving_average_after_entry(10, 50000, 10, 60000)
    assert mv["quantity"] == Decimal("20")
    assert mv["totalValue"] == Decimal("110000.00")
    assert mv["unitCost"] == Decimal("5500.0000")


def test_moving_average_from_zero_initial_stock():
    """Existencias iniciales en cero: la entrada fija el promedio inicial."""
    mv = InventoryValuationService.moving_average_after_entry(0, 0, 5, 25000)
    assert mv["quantity"] == Decimal("5")
    assert mv["totalValue"] == Decimal("25000.00")
    assert mv["unitCost"] == Decimal("5000.0000")


def test_entry_line_value_with_discount():
    """Descuento comercial reduce el costo de adquisición."""
    line = InventoryValuationService.entry_line_value(100, 10, discount_amount=100)
    assert line == Decimal("900.00")
    assert InventoryValuationService.effective_unit_cost(line, 10) == Decimal("90.0000")


def test_entry_line_value_with_additional_costs():
    """Costos adicionales atribuibles se incorporan al costo."""
    line = InventoryValuationService.entry_line_value(100, 10, additional_costs=50)
    assert line == Decimal("1050.00")
    assert InventoryValuationService.effective_unit_cost(line, 10) == Decimal("105.0000")


def test_entry_line_value_excludes_recoverable_tax():
    """ITBIS recuperable NO forma parte del costo del inventario."""
    # taxAmountRecoverable se ignora; nonRecoverableTax sí se suma.
    line = InventoryValuationService.entry_line_value(100, 10, non_recoverable_tax=18)
    assert line == Decimal("1018.00")
    assert InventoryValuationService.entry_line_value(100, 10) == Decimal("1000.00")


def test_exit_valuation_uses_current_average_and_keeps_it_unchanged():
    """Salida: COGS = promedio × cantidad; el promedio no cambia."""
    ev = InventoryValuationService.exit_valuation(20, 110000, 10)
    assert ev["cogs"] == Decimal("55000.00")
    assert ev["unitCost"] == Decimal("5500.0000")
    assert ev["quantity"] == Decimal("10")
    assert ev["totalValue"] == Decimal("55000.00")


def test_precision_repeating_decimal():
    """Promedio con decimales periódicos se cuantiza a 4 decimales (sin float)."""
    # 2×100 + 1×110 = 310; promedio = 103.3333...
    mv = InventoryValuationService.moving_average_after_entry(2, 200, 1, 110)
    assert mv["unitCost"] == Decimal("103.3333")
    ev = InventoryValuationService.exit_valuation(mv["quantity"], mv["totalValue"], 1)
    assert ev["cogs"] == Decimal("103.33")
    assert ev["totalValue"] == Decimal("206.67")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PRUEBAS DE INTEGRACIÓN (motor transaccional con valoración por almacén)
# ═══════════════════════════════════════════════════════════════════════════════

class MockDocumentSnapshot:
    def __init__(self, doc_id, data=None, exists=True):
        self.id = doc_id
        self._data = data or {}
        self.exists = exists

    def to_dict(self):
        return dict(self._data)


class MockDocumentReference:
    def __init__(self, coll, doc_id):
        self.coll = coll
        self.id = doc_id

    def get(self, transaction=None):
        data = self.coll._storage.get(self.id)
        if data is not None:
            return MockDocumentSnapshot(self.id, data=data, exists=True)
        return MockDocumentSnapshot(self.id, exists=False)

    def set(self, data, merge=False):
        if merge and self.id in self.coll._storage:
            self.coll._storage[self.id].update(data)
        else:
            self.coll._storage[self.id] = dict(data)

    def update(self, data):
        if self.id in self.coll._storage:
            self.coll._storage[self.id].update(data)
        else:
            self.coll._storage[self.id] = dict(data)


class MockCollectionReference:
    def __init__(self, name):
        self.name = name
        self._storage = {}

    def document(self, doc_id):
        return MockDocumentReference(self, doc_id)

    def where(self, filter=None, **kwargs):
        return self

    def limit(self, count):
        return self

    def stream(self):
        for doc_id, data in list(self._storage.items()):
            yield MockDocumentSnapshot(doc_id, data=data, exists=True)

    def get(self, transaction=None):
        return list(self.stream())


class MockFirestoreTransaction:
    def __init__(self, db):
        self.db = db

    def get(self, ref):
        return ref.get(transaction=self)

    def set(self, ref, data, merge=False):
        ref.set(data, merge=merge)

    def update(self, ref, data):
        ref.update(data)


class MockFirestoreClient:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = MockCollectionReference(name)
        return self.collections[name]

    def transaction(self):
        txn = MockFirestoreTransaction(self)

        def runner(fn):
            return fn(txn)

        txn.__call__ = runner
        return txn


@pytest.fixture
def promedio_env():
    store = {
        "client": MockFirestoreClient(),
        "items": {},
        "warehouses": [
            {"id": "wh-a", "name": "Almacén A", "branchId": "branch-1"},
            {"id": "wh-b", "name": "Almacén B", "branchId": "branch-1"},
        ],
    }

    def mock_company_coll(company_id=None, owner_uid=None, coll_name=""):
        return store["client"].collection(f"companies/{company_id}/{coll_name}")

    def mock_get_warehouses(owner_uid, sandbox=True, company_id=None):
        return store["warehouses"]

    with patch("app.services.inventory_transaction_service._company_coll", side_effect=mock_company_coll), \
         patch("app.services.inventory_transaction_service.db_firestore", store["client"]), \
         patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses), \
         patch("app.services.inventory_valuation_service.InventoryValuationService.get_company_valuation_method", return_value=None), \
         patch("app.services.inventory_transaction_service._invalidate_items"):
        yield store


def _seed_item(store, company_id, item_id, cost_price, valuation_method="promedio", total_stock=0.0):
    item_data = {
        "id": item_id,
        "name": "Producto",
        "code": "P-01",
        "costPrice": cost_price,
        "totalStock": total_stock,
        "valuationMethod": valuation_method,
    }
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)


def _stock(store, company_id, item_id, wh):
    return store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock") \
        .document(f"{item_id}_{wh}").get().to_dict()


def _item(store, company_id, item_id):
    return store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).get().to_dict()


def _entrada(company_id, owner_uid, item_id, qty, unit_cost, wh="wh-a", **extra):
    tx = {
        "itemId": item_id,
        "type": "ENTRADA",
        "quantity": qty,
        "unitCost": unit_cost,
        "reason": "COMPRA",
        "referenceType": "GOODS_RECEIPT",
        "referenceId": extra.pop("referenceId", f"RC-{qty}-{unit_cost}"),
        "destinationWarehouseId": wh,
    }
    tx.update(extra)
    return InventoryTransactionService.execute_transaction(owner_uid, company_id, tx, sandbox=True)


def test_same_reference_cost_entry(promedio_env):
    """1. Entrada con el mismo costo de referencia."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-1"
    _seed_item(store, company_id, item_id, cost_price=5000.0)

    res = _entrada(company_id, owner_uid, item_id, 10, 5000.0)

    assert res["costMethod"] == "PROMEDIO"
    assert res["unitCost"] == 5000.0
    assert res["totalValue"] == 50000.0
    assert res["referenceCost"] == 5000.0
    assert res["previousAvgCost"] == 0.0
    assert res["resultingAvgCost"] == 5000.0
    assert res["lastPurchaseCost"] == 5000.0

    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 10.0
    assert s["totalValue"] == 50000.0
    assert s["unitCost"] == 5000.0
    assert s["lastPurchaseCost"] == 5000.0


def test_higher_cost_entry(promedio_env):
    """2. Entrada con costo superior → el promedio sube."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-2"
    _seed_item(store, company_id, item_id, cost_price=5000.0)

    _entrada(company_id, owner_uid, item_id, 10, 5000.0)
    res = _entrada(company_id, owner_uid, item_id, 10, 6000.0)

    assert res["resultingAvgCost"] == 5500.0
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 20.0
    assert s["totalValue"] == 110000.0
    assert s["unitCost"] == 5500.0
    assert s["lastPurchaseCost"] == 6000.0


def test_lower_cost_entry(promedio_env):
    """3. Entrada con costo inferior → el promedio baja."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-3"
    _seed_item(store, company_id, item_id, cost_price=5000.0)

    _entrada(company_id, owner_uid, item_id, 10, 6000.0)
    res = _entrada(company_id, owner_uid, item_id, 10, 4000.0)

    assert res["resultingAvgCost"] == 5000.0
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["totalValue"] == 100000.0
    assert s["unitCost"] == 5000.0


def test_multiple_entries_different_costs_and_reference_not_overwritten(promedio_env):
    """4. Múltiples entradas con costos diferentes; `costPrice` (referencia) intacto."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-4"
    _seed_item(store, company_id, item_id, cost_price=5000.0)

    _entrada(company_id, owner_uid, item_id, 10, 100.0, referenceId="RC-1")
    _entrada(company_id, owner_uid, item_id, 20, 200.0, referenceId="RC-2")
    res = _entrada(company_id, owner_uid, item_id, 30, 300.0, referenceId="RC-3")

    # (10×100 + 20×200 + 30×300) = 1000 + 4000 + 9000 = 14000 / 60 = 233.3333
    assert res["resultingAvgCost"] == 233.3333
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["totalValue"] == 14000.0
    assert s["quantity"] == 60.0
    assert s["lastPurchaseCost"] == 300.0

    it = _item(store, company_id, item_id)
    assert it["costPrice"] == 5000.0  # referencia NO se sobrescribe
    assert it["avgCost"] == 233.3333
    assert it["lastPurchaseCost"] == 300.0


def test_entry_with_discount(promedio_env):
    """5. Entrada con descuento reduce el costo efectivo."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-5"
    _seed_item(store, company_id, item_id, cost_price=100.0)

    res = _entrada(company_id, owner_uid, item_id, 10, 100.0, discountAmount=100.0)

    assert res["totalValue"] == 900.0
    assert res["unitCost"] == 90.0
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["unitCost"] == 90.0
    assert s["lastPurchaseCost"] == 90.0


def test_entry_with_recoverable_tax_excluded(promedio_env):
    """6. ITBIS recuperable no altera el costo del inventario."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-6"
    _seed_item(store, company_id, item_id, cost_price=100.0)

    res = _entrada(company_id, owner_uid, item_id, 10, 100.0, taxAmountRecoverable=180.0)

    assert res["totalValue"] == 1000.0
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["unitCost"] == 100.0


def test_entry_with_additional_costs(promedio_env):
    """7. Costos adicionales atribuibles se incorporan al costo."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-7"
    _seed_item(store, company_id, item_id, cost_price=100.0)

    res = _entrada(company_id, owner_uid, item_id, 10, 100.0, additionalCosts=50.0)

    assert res["totalValue"] == 1050.0
    assert res["unitCost"] == 105.0
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["unitCost"] == 105.0


def test_partial_exit_uses_average_cost(promedio_env):
    """8. Salida parcial: COGS = promedio vigente; el promedio no cambia."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-8"
    _seed_item(store, company_id, item_id, cost_price=5000.0)

    _entrada(company_id, owner_uid, item_id, 10, 5000.0)
    _entrada(company_id, owner_uid, item_id, 10, 6000.0)

    out = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 10.0,
        "reason": "VENTA", "referenceType": "INVOICE", "referenceId": "FAC-1",
        "originWarehouseId": "wh-a",
    }, sandbox=True)

    assert out["costMethod"] == "PROMEDIO"
    assert out["totalValue"] == 55000.0
    assert out["unitCost"] == 5500.0
    assert out["costLayers"] == []

    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 10.0
    assert s["totalValue"] == 55000.0
    assert s["unitCost"] == 5500.0  # promedio no cambia en salida


def test_return_reentry_at_valuation_cost(promedio_env):
    """9. Devolución: reingreso al costo de valoración vigente actualiza el promedio."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-9"
    _seed_item(store, company_id, item_id, cost_price=5000.0)

    _entrada(company_id, owner_uid, item_id, 10, 5000.0)
    _entrada(company_id, owner_uid, item_id, 10, 6000.0)

    # Venta de 5 a $5,500 → quedan 15 @ 5,500 (valor 82,500)
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 5.0,
        "reason": "VENTA", "referenceType": "INVOICE", "referenceId": "FAC-9",
        "originWarehouseId": "wh-a",
    }, sandbox=True)

    # Devolución de 5 al costo de valoración vigente (5,500)
    back = _entrada(company_id, owner_uid, item_id, 5, 5500.0, reason="DEVOLUCION_CLIENTE")
    assert back["totalValue"] == 27500.0

    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 20.0
    assert s["totalValue"] == 110000.0
    assert s["unitCost"] == 5500.0


def test_reversal_of_entry(promedio_env):
    """10. Anulación/reversión de una entrada: reingresa el costo original."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-10"
    _seed_item(store, company_id, item_id, cost_price=5000.0)

    _entrada(company_id, owner_uid, item_id, 10, 5000.0)
    _entrada(company_id, owner_uid, item_id, 10, 6000.0)

    # Reversión de la segunda entrada: salida de 10 al costo original 6,000
    rev = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 10.0, "unitCost": 6000.0,
        "reason": "DEVOLUCION_PROVEEDOR", "referenceType": "GOODS_RECEIPT_ROLLBACK",
        "referenceId": "RC-ROLLBACK", "originWarehouseId": "wh-a",
    }, sandbox=True)

    assert rev["totalValue"] == 60000.0

    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 10.0
    assert s["totalValue"] == 50000.0
    assert s["unitCost"] == 5000.0


def test_transaction_reversal_reference_type_honors_explicit_cost(promedio_env):
    """La reversión genérica (TRANSACTION_REVERSAL / REVERSION) honra el costo explícito."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-rev"
    _seed_item(store, company_id, item_id, cost_price=100.0)

    _entrada(company_id, owner_uid, item_id, 10, 100.0, referenceId="RC-1")
    _entrada(company_id, owner_uid, item_id, 10, 200.0, referenceId="RC-2")

    # Revertir la 2ª entrada (10 @ 200) con referencia TRANSACTION_REVERSAL
    rev = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 10.0, "unitCost": 200.0,
        "reason": "REVERSION", "referenceType": "TRANSACTION_REVERSAL",
        "referenceId": "tx-RC-2", "originWarehouseId": "wh-a",
    }, sandbox=True)

    assert rev["totalValue"] == 2000.0  # 10 × 200, no el promedio 150
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 10.0
    assert s["totalValue"] == 1000.0
    assert s["unitCost"] == 100.0


def test_simultaneous_entries(promedio_env):
    """11. Entradas simultáneas del mismo producto mantienen el promedio consistente."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-11"
    _seed_item(store, company_id, item_id, cost_price=100.0)

    _entrada(company_id, owner_uid, item_id, 10, 100.0, referenceId="RC-A")
    _entrada(company_id, owner_uid, item_id, 10, 200.0, referenceId="RC-B")

    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 20.0
    assert s["totalValue"] == 3000.0
    assert s["unitCost"] == 150.0


def test_multi_warehouse_isolation(promedio_env):
    """13. Existencias en diferentes almacenes: promedios independientes."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-13"
    _seed_item(store, company_id, item_id, cost_price=100.0)

    _entrada(company_id, owner_uid, item_id, 10, 100.0, wh="wh-a", referenceId="RC-A")
    _entrada(company_id, owner_uid, item_id, 10, 300.0, wh="wh-b", referenceId="RC-B")

    sa = _stock(store, company_id, item_id, "wh-a")
    sb = _stock(store, company_id, item_id, "wh-b")
    assert sa["unitCost"] == 100.0
    assert sb["unitCost"] == 300.0

    # Salida solo en wh-a no afecta el promedio de wh-b
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 5.0,
        "reason": "VENTA", "referenceType": "INVOICE", "referenceId": "FAC-13",
        "originWarehouseId": "wh-a",
    }, sandbox=True)
    sb2 = _stock(store, company_id, item_id, "wh-b")
    assert sb2["quantity"] == 10.0
    assert sb2["unitCost"] == 300.0
    assert sb2["totalValue"] == 3000.0


def test_integrity_inventory_accounting_value(promedio_env):
    """15. totalValue del movimiento coincide con qty × unitCost (base contable)."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-15"
    _seed_item(store, company_id, item_id, cost_price=5000.0)

    r1 = _entrada(company_id, owner_uid, item_id, 10, 5000.0)
    assert abs(r1["totalValue"] - r1["quantity"] * r1["unitCost"]) < 0.01

    r2 = _entrada(company_id, owner_uid, item_id, 10, 6000.0)
    assert abs(r2["totalValue"] - r2["quantity"] * r2["unitCost"]) < 0.01

    out = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 15.0,
        "reason": "VENTA", "referenceType": "INVOICE", "referenceId": "FAC-15",
        "originWarehouseId": "wh-a",
    }, sandbox=True)
    assert abs(out["totalValue"] - out["quantity"] * out["unitCost"]) < 0.01

    s = _stock(store, company_id, item_id, "wh-a")
    assert abs(s["totalValue"] - s["quantity"] * s["unitCost"]) < 0.01


def test_insufficient_stock_not_negative(promedio_env):
    """La existencia negativa no genera promedio incorrecto: se rechaza la salida."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-neg"
    _seed_item(store, company_id, item_id, cost_price=100.0)

    _entrada(company_id, owner_uid, item_id, 10, 100.0)

    with pytest.raises(InsufficientStockError):
        InventoryTransactionService.execute_transaction(owner_uid, company_id, {
            "itemId": item_id, "type": "SALIDA", "quantity": 20.0,
            "originWarehouseId": "wh-a",
        }, sandbox=True)


def test_transfer_moving_average(promedio_env):
    """Transferencia entre almacenes: sale al promedio de origen y entra al destino con ese costo."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-tr"
    _seed_item(store, company_id, item_id, cost_price=100.0)
    _entrada(company_id, owner_uid, item_id, 10, 100.0, wh="wh-a", referenceId="RC-A")
    _entrada(company_id, owner_uid, item_id, 10, 300.0, wh="wh-b", referenceId="RC-B")

    res = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "TRANSFERENCIA", "quantity": 5.0,
        "originWarehouseId": "wh-a", "destinationWarehouseId": "wh-b",
        "reason": "TRANSFERENCIA_ENTRE_ALMACENES",
    }, sandbox=True)

    assert res["costMethod"] == "PROMEDIO"
    assert res["totalValue"] == 500.0  # 5 × 100

    sa = _stock(store, company_id, item_id, "wh-a")
    sb = _stock(store, company_id, item_id, "wh-b")
    assert sa["quantity"] == 5.0
    assert sa["totalValue"] == 500.0
    assert sa["unitCost"] == 100.0
    assert sb["quantity"] == 15.0
    assert sb["totalValue"] == 3500.0  # 3000 + 500
    assert abs(sb["unitCost"] - 233.3333) < 0.0001


def test_adjustment_surplus_and_shortage(promedio_env):
    """Ajuste físico (sobrante/faltante) mantiene la valoración al promedio vigente."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-adj"
    _seed_item(store, company_id, item_id, cost_price=100.0)
    _entrada(company_id, owner_uid, item_id, 10, 100.0)

    # Sobrante +5
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "AJUSTE", "targetQuantity": 15.0,
        "destinationWarehouseId": "wh-a", "reason": "RECUENTO_FISICO",
        "referenceType": "PHYSICAL_COUNT", "referenceId": "PC-1",
    }, sandbox=True)
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 15.0
    assert s["totalValue"] == 1500.0
    assert s["unitCost"] == 100.0

    # Faltante -3
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "AJUSTE", "targetQuantity": 12.0,
        "destinationWarehouseId": "wh-a", "reason": "RECUENTO_FISICO",
        "referenceType": "PHYSICAL_COUNT", "referenceId": "PC-2",
    }, sandbox=True)
    s = _stock(store, company_id, item_id, "wh-a")
    assert s["quantity"] == 12.0
    assert s["totalValue"] == 1200.0
    assert s["unitCost"] == 100.0


def test_physical_count_shortage_uses_average_not_catalog_cost(promedio_env):
    """Conteo físico (faltante) se valora al promedio, no al costo de catálogo."""
    store = promedio_env
    company_id, owner_uid, item_id = "comp", "user", "it-pc"
    _seed_item(store, company_id, item_id, cost_price=999.0)  # costo de catálogo inflado
    _entrada(company_id, owner_uid, item_id, 10, 100.0)
    _entrada(company_id, owner_uid, item_id, 10, 200.0)  # promedio = 150

    out = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 5.0,
        "unitCost": 999.0,  # costo de catálogo: debe ignorarse en conteo físico
        "reason": "RECUENTO_FISICO", "referenceType": "PHYSICAL_COUNT",
        "referenceId": "PC-1", "originWarehouseId": "wh-a",
    }, sandbox=True)

    assert out["totalValue"] == 750.0  # 5 × 150 (promedio), no 5 × 999
    assert out["unitCost"] == 150.0


def test_resolve_method_priority():
    """Prioridad de resolución del método: tx → item → empresa → default fifo."""
    assert InventoryValuationService.resolve_method() == "fifo"
    assert InventoryValuationService.resolve_method(company_method="promedio") == "promedio"
    assert InventoryValuationService.resolve_method(item_dict={"valuationMethod": "promedio"}, company_method="fifo") == "promedio"
    assert InventoryValuationService.resolve_method(item_dict={"valuationMethod": "promedio"}, tx_override="fifo") == "fifo"


def test_goods_receipt_passes_variable_cost_breakdown():
    """La recepción de mercancía propaga costo unitario editable + descuento/adicionales/impuestos."""
    from unittest.mock import patch
    from app.services.goods_receipt_service import GoodsReceiptService
    from app.services.purchase_order_service import PurchaseOrderService

    receipt = {
        "id": "rc-var",
        "receiptNumber": "RC-2026-0001",
        "poId": "po-var",
        "poNumber": "OC-2026-0001",
        "supplierId": "sup-9",
        "warehouseId": "wh-a",
        "warehouseName": "Almacén A",
        "items": [
            {
                "poItemId": "line-1",
                "itemId": "it-1",
                "itemName": "Panel Solar",
                "receivedQuantity": 10,
                "unitCost": 6000.0,          # costo unitario editable (bruto)
                "discountAmount": 500.0,     # descuento por línea
                "additionalCosts": 200.0,    # flete/seguro atribuible
                "taxAmountRecoverable": 0.0,
                "nonRecoverableTax": 0.0,
                "referenceCost": 5000.0,
                "isInventoriable": True,
            }
        ],
    }

    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=None), \
         patch("app.services.inventory_transaction_service.InventoryTransactionService.execute_transaction") as mock_exec, \
         patch("app.services.inventory_costing_service.InventoryCostingService.recalculate_item_avg_cost"), \
         patch("app.services.inventory_accounting_service.InventoryAccountingService.post_inventory_transaction"):
        mock_exec.return_value = {"id": "tx-var", "itemId": "it-1"}
        GoodsReceiptService.register_receipt_inventory("comp", receipt, sandbox=True, owner_uid="own")

    tx = mock_exec.call_args.kwargs["tx_dict"]
    assert tx["unitCost"] == 6000.0
    assert tx["discountAmount"] == 500.0
    assert tx["additionalCosts"] == 200.0
    assert tx["referenceCost"] == 5000.0
    assert tx["supplierId"] == "sup-9"
    assert tx["taxAmountRecoverable"] == 0.0
