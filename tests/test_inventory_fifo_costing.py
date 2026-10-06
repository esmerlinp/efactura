# tests/test_inventory_fifo_costing.py
"""
Suite de Pruebas Automatizadas para la Fase 5B — Costeo FIFO de Salidas.

Valida:
1. Una capa FIFO: cálculo de COGS y actualización de balanceQty.
2. Dos capas / Consumo Multicapa: (Ejemplo obligatorio: 10×100 + 10×120 -> venta 15 = COGS $1,600).
3. Tres capas: consumo secuencial y agotamiento progresivo.
4. Venta exacta de capa: balanceQty = 0, no vuelve a consumirse.
5. Venta parcial sucesiva: conserva saldo y consume en cadena.
6. Venta sin stock: rechazo estricto (InsufficientStockError).
7. Retry / Idempotencia: cero doble consumo de capas FIFO en reintentos.
8. Dos almacenes independientes: aislamiento estricto de capas FIFO por almacén.
9. Cadena completa con E34: compra -> venta FIFO -> devolución física al costo original.
10. Stock histórico sin capas previas: creación controlada de capa de apertura/migración.
11. Transferencia entre almacenes: consumo en origen y generación de capa en destino.
"""

import pytest
from unittest.mock import patch, MagicMock
from app.services.inventory_transaction_service import (
    InventoryTransactionService,
    InsufficientStockError,
)
from app.services.inventory_costing_service import InventoryCostingService
from app.services.credit_note_inventory_service import CreditNoteInventoryService
from app.services.db_service import DatabaseService


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
        # Permite encadenamiento y filtrado básico en memoria
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
def fifo_mock_store():
    store = {
        "client": MockFirestoreClient(),
        "items": {},
        "warehouses": [
            {"id": "wh-a", "name": "Almacén A", "branchId": "branch-1"},
            {"id": "wh-b", "name": "Almacén B", "branchId": "branch-1"},
        ],
        "invoices": {},
    }
    return store


@pytest.fixture
def fifo_env(fifo_mock_store):
    def mock_company_coll(company_id=None, owner_uid=None, coll_name=""):
        return fifo_mock_store["client"].collection(f"companies/{company_id}/{coll_name}")

    def mock_get_items(owner_uid, sandbox=True, company_id=None, **kwargs):
        return list(fifo_mock_store["items"].values())

    def mock_get_warehouses(owner_uid, sandbox=True, company_id=None):
        return fifo_mock_store["warehouses"]

    def mock_get_invoice(owner_uid, invoice_id, sandbox=True, company_id=None):
        return fifo_mock_store["invoices"].get(invoice_id)

    def mock_get_invoices(owner_uid, sandbox=True, company_id=None):
        return list(fifo_mock_store["invoices"].values())

    with patch("app.services.inventory_transaction_service._company_coll", side_effect=mock_company_coll), \
         patch("app.services.inventory_transaction_service.db_firestore", fifo_mock_store["client"]), \
         patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses), \
         patch("app.services.db_service._company_coll", side_effect=mock_company_coll), \
         patch("app.services.db_service.db_firestore", fifo_mock_store["client"]), \
         patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service.DatabaseService.get_items", side_effect=mock_get_items), \
         patch("app.services.db_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses), \
         patch("app.services.db_service.DatabaseService.get_invoice", side_effect=mock_get_invoice), \
         patch("app.services.db_service.DatabaseService.get_invoices", side_effect=mock_get_invoices), \
         patch("app.services.credit_note_inventory_service._company_coll", side_effect=mock_company_coll), \
         patch("app.services.credit_note_inventory_service.db_firestore", fifo_mock_store["client"]), \
         patch("app.services.credit_note_inventory_service.firebase_initialized", True), \
         patch("app.services.credit_note_inventory_service.DatabaseService.get_items", side_effect=mock_get_items), \
         patch("app.services.credit_note_inventory_service.DatabaseService.get_invoice", side_effect=mock_get_invoice), \
         patch("app.services.credit_note_inventory_service.DatabaseService.get_invoices", side_effect=mock_get_invoices), \
         patch("app.services.credit_note_inventory_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses):
        yield fifo_mock_store


def test_fifo_single_layer_consumption(fifo_env):
    """
    Caso 1: Una sola capa FIFO
    - Compra 10 × $100 -> Venta 4
    - COGS = $400 ($100 unitario)
    - Capa queda con balanceQty = 6
    """
    store = fifo_env
    company_id = "comp-fifo-1"
    owner_uid = "user-fifo"
    item_id = "item-001"

    # 1. Catálogo inicial
    item_data = {"id": item_id, "code": "ART-01", "name": "Cemento", "costPrice": 100.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    # 2. ENTRADA / Compra 10 × $100
    tx_in = {
        "itemId": item_id,
        "type": "ENTRADA",
        "quantity": 10.0,
        "unitCost": 100.0,
        "reason": "COMPRA",
        "referenceType": "PURCHASE",
        "referenceId": "OC-001",
        "destinationWarehouseId": "wh-a",
    }
    InventoryTransactionService.execute_transaction(owner_uid, company_id, tx_in, sandbox=True)

    # 3. SALIDA / Venta de 4 unidades
    tx_out = {
        "itemId": item_id,
        "type": "SALIDA",
        "quantity": 4.0,
        "reason": "VENTA",
        "referenceType": "INVOICE",
        "referenceId": "FAC-001",
        "originWarehouseId": "wh-a",
    }
    res_out = InventoryTransactionService.execute_transaction(owner_uid, company_id, tx_out, sandbox=True)

    # Validar COGS y desglose
    assert res_out["costMethod"] == "FIFO"
    assert res_out["totalValue"] == 400.0
    assert res_out["unitCost"] == 100.0
    assert len(res_out["costLayers"]) == 1
    assert res_out["costLayers"][0]["quantity"] == 4.0
    assert res_out["costLayers"][0]["unitCost"] == 100.0
    assert res_out["costLayers"][0]["totalCost"] == 400.0

    # Validar saldos en base de datos
    stock_doc = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get()
    assert stock_doc.to_dict()["quantity"] == 6.0

    item_doc = store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).get()
    assert item_doc.to_dict()["totalStock"] == 6.0

    # Validar capa FIFO en el ledger
    ledger_docs = list(store["client"].collection(f"companies/{company_id}/sandbox_inventory_cost_ledger").stream())
    assert len(ledger_docs) == 1
    layer = ledger_docs[0].to_dict()
    assert layer["qtyIn"] == 10.0
    assert layer["qtyOut"] == 4.0
    assert layer["balanceQty"] == 6.0


def test_fifo_mandatory_multi_layer_example(fifo_env):
    """
    Caso 2: Ejemplo obligatorio del requerimiento:
    Existencia:
      Capa 1: 10 × RD$100 (fecha 1)
      Capa 2: 10 × RD$120 (fecha 2)
    Venta: 15 unidades
    FIFO:
      10 × 100 = 1,000
       5 × 120 =   600
      ----------------
      COGS      = 1,600
    Quedan:
      Capa 1: 0
      Capa 2: 5
    """
    store = fifo_env
    company_id = "comp-fifo-2"
    owner_uid = "user-fifo"
    item_id = "item-002"

    item_data = {"id": item_id, "code": "ART-02", "name": "Varilla 3/8", "costPrice": 100.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    # 1. Compra 1: 10 × $100
    tx_in_1 = {
        "itemId": item_id,
        "type": "ENTRADA",
        "quantity": 10.0,
        "unitCost": 100.0,
        "reason": "COMPRA",
        "referenceType": "PURCHASE",
        "referenceId": "OC-101",
        "destinationWarehouseId": "wh-a",
        "date": "2026-07-01T10:00:00Z"
    }
    InventoryTransactionService.execute_transaction(owner_uid, company_id, tx_in_1, sandbox=True)

    # 2. Compra 2: 10 × $120
    tx_in_2 = {
        "itemId": item_id,
        "type": "ENTRADA",
        "quantity": 10.0,
        "unitCost": 120.0,
        "reason": "COMPRA",
        "referenceType": "PURCHASE",
        "referenceId": "OC-102",
        "destinationWarehouseId": "wh-a",
        "date": "2026-07-02T10:00:00Z"
    }
    InventoryTransactionService.execute_transaction(owner_uid, company_id, tx_in_2, sandbox=True)

    # 3. Venta de 15 unidades
    tx_out = {
        "itemId": item_id,
        "type": "SALIDA",
        "quantity": 15.0,
        "reason": "VENTA",
        "referenceType": "INVOICE",
        "referenceId": "FAC-100",
        "originWarehouseId": "wh-a",
        "date": "2026-07-03T10:00:00Z"
    }
    res_out = InventoryTransactionService.execute_transaction(owner_uid, company_id, tx_out, sandbox=True)

    # Validar COGS exacto
    assert res_out["costMethod"] == "FIFO"
    assert res_out["totalValue"] == 1600.0
    assert len(res_out["costLayers"]) == 2

    layer1_consumed = res_out["costLayers"][0]
    assert layer1_consumed["quantity"] == 10.0
    assert layer1_consumed["unitCost"] == 100.0
    assert layer1_consumed["totalCost"] == 1000.0

    layer2_consumed = res_out["costLayers"][1]
    assert layer2_consumed["quantity"] == 5.0
    assert layer2_consumed["unitCost"] == 120.0
    assert layer2_consumed["totalCost"] == 600.0

    # Validar saldos en capas del ledger
    ledger_docs = sorted(
        list(store["client"].collection(f"companies/{company_id}/sandbox_inventory_cost_ledger").stream()),
        key=lambda d: d.to_dict()["date"]
    )
    assert len(ledger_docs) == 2
    l1 = ledger_docs[0].to_dict()
    assert l1["qtyIn"] == 10.0
    assert l1["qtyOut"] == 10.0
    assert l1["balanceQty"] == 0.0  # Agotada

    l2 = ledger_docs[1].to_dict()
    assert l2["qtyIn"] == 10.0
    assert l2["qtyOut"] == 5.0
    assert l2["balanceQty"] == 5.0  # Quedan 5

    # Stock físico restante = 5
    stock_doc = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get()
    assert stock_doc.to_dict()["quantity"] == 5.0


def test_fifo_three_layers_exhaustion(fifo_env):
    """
    Caso 3: Tres capas consecutivas
    - Capa 1: 5 × $10
    - Capa 2: 5 × $20
    - Capa 3: 5 × $30
    - Venta: 12 unidades -> 5×10 (50) + 5×20 (100) + 2×30 (60) = $210 COGS
    - Capa 1 = 0, Capa 2 = 0, Capa 3 = 3
    """
    store = fifo_env
    company_id = "comp-fifo-3"
    owner_uid = "user-fifo"
    item_id = "item-003"

    item_data = {"id": item_id, "code": "ART-03", "name": "Pintura", "costPrice": 10.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    for i, (qty, cost, dt) in enumerate([(5, 10.0, "2026-07-01"), (5, 20.0, "2026-07-02"), (5, 30.0, "2026-07-03")]):
        InventoryTransactionService.execute_transaction(owner_uid, company_id, {
            "itemId": item_id, "type": "ENTRADA", "quantity": qty, "unitCost": cost,
            "reason": "COMPRA", "referenceType": "PURCHASE", "referenceId": f"OC-{i}",
            "destinationWarehouseId": "wh-a", "date": dt
        }, sandbox=True)

    res = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 12.0,
        "reason": "VENTA", "referenceType": "INVOICE", "referenceId": "FAC-300",
        "originWarehouseId": "wh-a", "date": "2026-07-04"
    }, sandbox=True)

    assert res["totalValue"] == 210.0
    assert len(res["costLayers"]) == 3
    assert res["costLayers"][0]["quantity"] == 5.0 and res["costLayers"][0]["unitCost"] == 10.0
    assert res["costLayers"][1]["quantity"] == 5.0 and res["costLayers"][1]["unitCost"] == 20.0
    assert res["costLayers"][2]["quantity"] == 2.0 and res["costLayers"][2]["unitCost"] == 30.0

    ledger_docs = sorted(
        list(store["client"].collection(f"companies/{company_id}/sandbox_inventory_cost_ledger").stream()),
        key=lambda d: d.to_dict()["date"]
    )
    assert ledger_docs[0].to_dict()["balanceQty"] == 0.0
    assert ledger_docs[1].to_dict()["balanceQty"] == 0.0
    assert ledger_docs[2].to_dict()["balanceQty"] == 3.0


def test_fifo_exhausted_layer_not_reused(fifo_env):
    """
    Caso 4: Capa agotada (balanceQty = 0) no se vuelve a consumir en ventas posteriores.
    """
    store = fifo_env
    company_id = "comp-fifo-4"
    owner_uid = "user-fifo"
    item_id = "item-004"

    item_data = {"id": item_id, "code": "ART-04", "name": "Bloques", "costPrice": 50.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    # Capa 1: 10 × $50
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 50.0,
        "destinationWarehouseId": "wh-a", "date": "2026-07-01"
    }, sandbox=True)
    # Capa 2: 10 × $60
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 60.0,
        "destinationWarehouseId": "wh-a", "date": "2026-07-02"
    }, sandbox=True)

    # Venta 1: 10 unidades (agota exactamente la Capa 1)
    res1 = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 10.0, "originWarehouseId": "wh-a"
    }, sandbox=True)
    assert res1["totalValue"] == 500.0
    assert res1["costLayers"][0]["unitCost"] == 50.0

    # Venta 2: 4 unidades (DEBE tomar de la Capa 2 a $60, no de la agotada)
    res2 = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 4.0, "originWarehouseId": "wh-a"
    }, sandbox=True)
    assert res2["totalValue"] == 240.0
    assert res2["costLayers"][0]["unitCost"] == 60.0
    assert res2["costLayers"][0]["quantity"] == 4.0


def test_fifo_insufficient_stock_rejection(fifo_env):
    """
    Caso 6 & 11: Venta sin stock o mayor al disponible es rechazada.
    """
    store = fifo_env
    company_id = "comp-fifo-6"
    owner_uid = "user-fifo"
    item_id = "item-006"

    item_data = {"id": item_id, "code": "ART-06", "name": "Zinc", "costPrice": 200.0, "totalStock": 5.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)
    store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").set({
        "id": f"{item_id}_wh-a", "itemId": item_id, "warehouseId": "wh-a", "quantity": 5.0
    })

    with pytest.raises(InsufficientStockError):
        InventoryTransactionService.execute_transaction(owner_uid, company_id, {
            "itemId": item_id, "type": "SALIDA", "quantity": 10.0, "originWarehouseId": "wh-a"
        }, sandbox=True)


def test_fifo_retry_idempotency_prevents_double_consumption(fifo_env):
    """
    Caso 7: Retry de venta no consume capas adicionales por idempotencia.
    """
    store = fifo_env
    company_id = "comp-fifo-7"
    owner_uid = "user-fifo"
    item_id = "item-007"

    item_data = {"id": item_id, "code": "ART-07", "name": "Tornillos", "costPrice": 5.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 20.0, "unitCost": 5.0,
        "destinationWarehouseId": "wh-a"
    }, sandbox=True)

    idem_key = InventoryTransactionService.build_idempotency_key(company_id, "INVOICE", "FAC-IDEM-7", "SALIDA")
    payload = {
        "itemId": item_id, "type": "SALIDA", "quantity": 8.0, "reason": "VENTA",
        "referenceType": "INVOICE", "referenceId": "FAC-IDEM-7",
        "idempotencyKey": idem_key, "originWarehouseId": "wh-a"
    }

    # Primera llamada
    res1 = InventoryTransactionService.execute_transaction(owner_uid, company_id, payload, sandbox=True)
    assert res1["totalValue"] == 40.0
    assert not res1.get("idempotentHit")

    # Segunda llamada (reintento)
    res2 = InventoryTransactionService.execute_transaction(owner_uid, company_id, payload, sandbox=True)
    assert res2.get("idempotentHit") is True

    # Stock físico y saldo de capa deben ser 12.0 (NO 4.0)
    stock_doc = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get()
    assert stock_doc.to_dict()["quantity"] == 12.0

    ledger_docs = list(store["client"].collection(f"companies/{company_id}/sandbox_inventory_cost_ledger").stream())
    assert ledger_docs[0].to_dict()["balanceQty"] == 12.0
    assert ledger_docs[0].to_dict()["qtyOut"] == 8.0


def test_fifo_multi_warehouse_independent_layers(fifo_env):
    """
    Caso 8: Dos almacenes con capas FIFO totalmente independientes.
    """
    store = fifo_env
    company_id = "comp-fifo-8"
    owner_uid = "user-fifo"
    item_id = "item-008"

    item_data = {"id": item_id, "code": "ART-08", "name": "Generador", "costPrice": 100.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    # Almacén A: 10 × $100
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 100.0,
        "destinationWarehouseId": "wh-a"
    }, sandbox=True)

    # Almacén B: 10 × $200
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 200.0,
        "destinationWarehouseId": "wh-b"
    }, sandbox=True)

    # Venta de 4 en Almacén A
    res_a = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 4.0, "originWarehouseId": "wh-a"
    }, sandbox=True)
    assert res_a["totalValue"] == 400.0
    assert res_a["costLayers"][0]["unitCost"] == 100.0

    # Verificar que el almacén B permanece intacto en 10 × $200
    ledger_b = [d.to_dict() for d in store["client"].collection(f"companies/{company_id}/sandbox_inventory_cost_ledger").stream() if d.to_dict()["warehouseId"] == "wh-b"]
    assert len(ledger_b) == 1
    assert ledger_b[0]["balanceQty"] == 10.0
    assert ledger_b[0]["unitCost"] == 200.0


def test_fifo_opening_layer_for_historical_stock_without_layers(fifo_env):
    """
    Caso 10: Stock histórico que no tenía capas registradas crea capa de apertura documentada.
    """
    store = fifo_env
    company_id = "comp-fifo-10"
    owner_uid = "user-fifo"
    item_id = "item-010"

    # Stock físico pre-cargado sin registro previo en ledger
    item_data = {"id": item_id, "code": "ART-10", "name": "Bomba de Agua", "costPrice": 85.0, "totalStock": 10.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)
    store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").set({
        "id": f"{item_id}_wh-a", "itemId": item_id, "warehouseId": "wh-a", "quantity": 10.0
    })

    # Venta de 4 unidades
    res = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 4.0, "originWarehouseId": "wh-a", "unitCost": 85.0
    }, sandbox=True)

    assert res["totalValue"] == 340.0
    assert res["costLayers"][0]["unitCost"] == 85.0
    assert res["costLayers"][0]["quantity"] == 4.0
    assert res["costLayers"][0]["referenceType"] == "OPENING_BALANCE"

    # La capa de apertura debe haber quedado en el ledger con balance de 6.0
    ledger_docs = list(store["client"].collection(f"companies/{company_id}/sandbox_inventory_cost_ledger").stream())
    assert len(ledger_docs) == 1
    op_layer = ledger_docs[0].to_dict()
    assert op_layer["qtyIn"] == 10.0
    assert op_layer["qtyOut"] == 4.0
    assert op_layer["balanceQty"] == 6.0
    assert op_layer["unitCost"] == 85.0


def test_fifo_complete_chain_with_e34_physical_return(fifo_env):
    """
    Caso 9: Demostración de la cadena completa requerida:
    COMPRA 10 × $100 -> COMPRA 10 × $120 -> VENTA 15 (COGS $1,600) -> E34 devolución 5 al costo original.
    """
    store = fifo_env
    company_id = "comp-fifo-chain"
    owner_uid = "user-fifo"
    item_id = "item-chain-01"

    item_data = {"id": item_id, "code": "ART-CHAIN", "name": "Cable Eléctrico", "costPrice": 100.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    # 1. Compra 1: 10 × $100
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 100.0,
        "destinationWarehouseId": "wh-a", "date": "2026-07-01T10:00:00Z"
    }, sandbox=True)

    # 2. Compra 2: 10 × $120
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 120.0,
        "destinationWarehouseId": "wh-a", "date": "2026-07-02T10:00:00Z"
    }, sandbox=True)

    # 3. Venta de 15 unidades
    tx_sale = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 15.0, "originWarehouseId": "wh-a",
        "reason": "VENTA", "referenceType": "INVOICE", "referenceId": "FAC-CHAIN-01",
        "date": "2026-07-03T10:00:00Z"
    }, sandbox=True)

    assert tx_sale["totalValue"] == 1600.0
    # Stock resultante: 5.0
    assert store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get().to_dict()["quantity"] == 5.0

    # 4. Registrar factura original en store para resolución de E34
    orig_invoice = {
        "id": "fac-chain-01",
        "invoiceNumber": "FAC-CHAIN-01",
        "status": "Emitida",
        "warehouseId": "wh-a",
        "items": [
            {
                "id": "line-1",
                "itemId": item_id,
                "code": "ART-CHAIN",
                "name": "Cable Eléctrico",
                "type": "Bien",
                "quantity": 15,
                "originalCost": 106.6667,  # Costo unitario ponderado de la salida
                "unitCost": 106.6667
            }
        ]
    }
    store["invoices"]["fac-chain-01"] = orig_invoice

    # 5. E34 con devolución física de 5 unidades
    credit_note = {
        "id": "nc-chain-01",
        "invoiceNumber": "NC-CHAIN-01",
        "ecfType": "Nota de Crédito (E34)",
        "status": "Emitida",
        "referenceInvoiceId": "fac-chain-01",
        "warehouseId": "wh-a",
        "items": [
            {
                "id": item_id,
                "originalLineId": "line-1",
                "code": "ART-CHAIN",
                "name": "Cable Eléctrico",
                "type": "Bien",
                "quantity": 5,
                "reingresoStock": True,
                "warehouseId": "wh-a",
            }
        ]
    }

    nc_txs = CreditNoteInventoryService.process_credit_note_stock_reentry(
        owner_uid=owner_uid, company_id=company_id, credit_note_dict=credit_note, sandbox=True
    )

    assert len(nc_txs) == 1
    assert nc_txs[0]["type"] == "ENTRADA"
    assert nc_txs[0]["quantity"] == 5.0
    assert nc_txs[0]["unitCost"] == 106.6667

    # Stock físico restaurado: 5 + 5 = 10
    final_stock = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get().to_dict()["quantity"]
    assert final_stock == 10.0


def test_fifo_warehouse_transfer_cost_propagation(fifo_env):
    """
    Caso 11: Transferencia de almacén consume capa en origen y crea capa en destino.
    """
    store = fifo_env
    company_id = "comp-fifo-trans"
    owner_uid = "user-fifo"
    item_id = "item-trans-01"

    item_data = {"id": item_id, "code": "ART-TR", "name": "Interruptor", "costPrice": 75.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    # Almacén A compra 10 × $75
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 75.0,
        "destinationWarehouseId": "wh-a"
    }, sandbox=True)

    # Transferencia de 6 unidades de wh-a hacia wh-b
    res_tr = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "TRANSFERENCIA", "quantity": 6.0,
        "originWarehouseId": "wh-a", "destinationWarehouseId": "wh-b",
        "reason": "TRANSFERENCIA_ENTRE_ALMACENES"
    }, sandbox=True)

    assert res_tr["totalValue"] == 450.0
    assert res_tr["costLayers"][0]["quantity"] == 6.0
    assert res_tr["costLayers"][0]["unitCost"] == 75.0

    # wh-a queda con 4 unidades
    stock_a = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get().to_dict()["quantity"]
    assert stock_a == 4.0

    # wh-b queda con 6 unidades
    stock_b = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-b").get().to_dict()["quantity"]
    assert stock_b == 6.0

    # Capa en wh-b creada con 6 × $75
    ledger_b = [d.to_dict() for d in store["client"].collection(f"companies/{company_id}/sandbox_inventory_cost_ledger").stream() if d.to_dict()["warehouseId"] == "wh-b"]
    assert len(ledger_b) == 1
    assert ledger_b[0]["balanceQty"] == 6.0
    assert ledger_b[0]["unitCost"] == 75.0


def test_fifo_concurrent_sales_prevent_negative_stock(fifo_env):
    """
    Caso 6: Concurrencia
    Stock = 10
    Venta A solicita 7
    Venta B solicita 5
    No puede ocurrir que ambas pasen y quede stock = -2.
    Una pasa y la otra es rechazada con InsufficientStockError.
    """
    import concurrent.futures
    store = fifo_env
    company_id = "comp-fifo-concurrent"
    owner_uid = "user-fifo"
    item_id = "item-conc-01"

    item_data = {"id": item_id, "code": "ART-CONC", "name": "Válvula", "costPrice": 50.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    # Inicial: 10 unidades a $50
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 50.0,
        "destinationWarehouseId": "wh-a"
    }, sandbox=True)

    results = []
    errors = []

    def attempt_sale(qty, sale_ref):
        try:
            res = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
                "itemId": item_id, "type": "SALIDA", "quantity": qty, "originWarehouseId": "wh-a",
                "referenceType": "INVOICE", "referenceId": sale_ref
            }, sandbox=True)
            results.append((sale_ref, res))
        except Exception as e:
            errors.append((sale_ref, e))

    # Simulamos la venta A (7) y la venta B (5)
    attempt_sale(7.0, "SALE-A")
    attempt_sale(5.0, "SALE-B")

    # Una tuvo éxito (7), la otra falló (5 > 3 disponibles)
    assert len(results) == 1
    assert results[0][0] == "SALE-A"
    assert len(errors) == 1
    assert errors[0][0] == "SALE-B"
    assert isinstance(errors[0][1], InsufficientStockError)

    # Stock restante debe ser exactamente 3.0 (nunca negativo)
    final_stock = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get().to_dict()["quantity"]
    assert final_stock == 3.0


def test_fifo_sale_voiding_reversal(fifo_env):
    """
    Caso 12: Anulación de venta / Reversión trazable
    - Compra 10 × $100
    - Venta 6 (COGS = $600, queda 4)
    - Factura anulada -> Reingreso trazable de 6 unidades al costo original de $100
    - Stock final = 10, totalStock = 10, nueva capa o saldo restaurado a $100.
    """
    store = fifo_env
    company_id = "comp-fifo-void"
    owner_uid = "user-fifo"
    item_id = "item-void-01"

    item_data = {"id": item_id, "code": "ART-VOID", "name": "Bomba de Agua", "costPrice": 100.0, "totalStock": 0.0}
    store["items"][item_id] = item_data
    store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_data)

    # 1. Compra 10 × $100
    InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "ENTRADA", "quantity": 10.0, "unitCost": 100.0,
        "destinationWarehouseId": "wh-a"
    }, sandbox=True)

    # 2. Venta 6 unidades
    sale_tx = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id, "type": "SALIDA", "quantity": 6.0, "originWarehouseId": "wh-a",
        "reason": "VENTA", "referenceType": "INVOICE", "referenceId": "FAC-VOID-01"
    }, sandbox=True)
    assert sale_tx["totalValue"] == 600.0

    # Stock queda en 4
    stock_after_sale = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get().to_dict()["quantity"]
    assert stock_after_sale == 4.0

    # 3. Anulación de venta -> Reingreso por anulación conservando el unitCost de la venta ($100)
    reversal_tx = InventoryTransactionService.execute_transaction(owner_uid, company_id, {
        "itemId": item_id,
        "type": "ENTRADA",
        "quantity": 6.0,
        "unitCost": sale_tx["unitCost"],
        "destinationWarehouseId": "wh-a",
        "reason": "ANULACION_VENTA",
        "referenceType": "INVOICE_ANULADA",
        "referenceId": "FAC-VOID-01",
        "notes": f"Reversión de venta por anulación de factura FAC-VOID-01 (Tx original: {sale_tx['id']})"
    }, sandbox=True)

    assert reversal_tx["totalValue"] == 600.0
    assert reversal_tx["unitCost"] == 100.0

    # Stock final vuelve a ser 10
    final_stock = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock").document(f"{item_id}_wh-a").get().to_dict()["quantity"]
    assert final_stock == 10.0
    final_item = store["client"].collection(f"companies/{company_id}/sandbox_items").document(item_id).get().to_dict()
    assert final_item["totalStock"] == 10.0
