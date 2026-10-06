# tests/test_credit_note_inventory.py
"""
Suite de Pruebas Automatizadas para la Fase 5A — E34 y Devoluciones Físicas.

Valida:
1. Reingreso físico de stock (`reingresoStock: True`) por línea en E34.
2. Almacén destino configurable de la devolución.
3. Omisión estricta de movimientos de inventario cuando `reingresoStock: False`
   (correcciones de precio, descuentos o servicios).
4. Recuperación del costo original de venta (`originalCost`) sin asumir el `costPrice` actual.
5. Idempotencia y protección contra doble reingreso en retries.
6. Reversión limpia en caso de Anulación de la Nota de Crédito.
7. Trazabilidad completa (invoiceId, lineId, warehouseId, originalCost).
"""

import pytest
from unittest.mock import patch, MagicMock
from app.services.inventory_transaction_service import (
    InventoryTransactionService,
    InsufficientStockError,
)
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
        return self

    def limit(self, count):
        return self

    def stream(self):
        for doc_id, data in self._storage.items():
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
def mock_store():
    store = {
        "client": MockFirestoreClient(),
        "items": {},
        "warehouses": [
            {"id": "wh-main", "name": "Almacén Principal", "branchId": "branch-1"},
            {"id": "wh-secondary", "name": "Almacén Secundario", "branchId": "branch-1"},
        ],
        "invoices": {},
        "transactions": {},
    }
    return store


@pytest.fixture
def setup_environment(mock_store):
    def mock_company_coll(company_id=None, owner_uid=None, coll_name=""):
        return mock_store["client"].collection(f"companies/{company_id}/{coll_name}")

    def mock_get_items(owner_uid, sandbox=True, company_id=None, **kwargs):
        return list(mock_store["items"].values())

    def mock_get_warehouses(owner_uid, sandbox=True, company_id=None):
        return mock_store["warehouses"]

    def mock_get_invoice(owner_uid, invoice_id, sandbox=True, company_id=None):
        return mock_store["invoices"].get(invoice_id)

    def mock_get_invoices(owner_uid, sandbox=True, company_id=None):
        return list(mock_store["invoices"].values())

    with patch("app.services.inventory_transaction_service._company_coll", side_effect=mock_company_coll), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_store["client"]), \
         patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses), \
         patch("app.services.credit_note_inventory_service._company_coll", side_effect=mock_company_coll), \
         patch("app.services.credit_note_inventory_service.db_firestore", mock_store["client"]), \
         patch("app.services.credit_note_inventory_service.firebase_initialized", True), \
         patch("app.services.credit_note_inventory_service.DatabaseService.get_items", side_effect=mock_get_items), \
         patch("app.services.credit_note_inventory_service.DatabaseService.get_invoice", side_effect=mock_get_invoice), \
         patch("app.services.credit_note_inventory_service.DatabaseService.get_invoices", side_effect=mock_get_invoices), \
         patch("app.services.credit_note_inventory_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses), \
         patch("app.services.db_service._company_coll", side_effect=mock_company_coll), \
         patch("app.services.db_service.db_firestore", mock_store["client"]), \
         patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service.DatabaseService.get_items", side_effect=mock_get_items), \
         patch("app.services.db_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses), \
         patch("app.services.db_service.DatabaseService.get_invoice", side_effect=mock_get_invoice), \
         patch("app.services.db_service.DatabaseService.get_invoices", side_effect=mock_get_invoices):
        yield mock_store


def test_e34_physical_return_reenters_stock_with_original_cost(setup_environment):
    """
    Escenario 1 & 2:
    - Venta original: 10 unidades a costo original $45.00 cada una.
    - El catálogo de artículos sube de costo posteriormente a $60.00.
    - E34 con devolución física de 5 unidades (`reingresoStock: True`).
    - El reingreso DEBE recuperar el costo original de $45.00 (no el actual $60.00).
    - El stock debe aumentar en +5.
    """
    store = setup_environment
    company_id = "comp-fase5a"
    owner_uid = "user-123"

    # 1. Articulo inicial en catálogo
    item_id = "prod-001"
    item_data = {
        "id": item_id,
        "code": "PROD-001",
        "name": "Laptop Pro",
        "type": "Bien",
        "totalStock": 50.0,
        "costPrice": 60.0,  # Costo actual inflado en catálogo
    }
    store["items"][item_id] = item_data
    items_coll = store["client"].collection(f"companies/{company_id}/sandbox_items")
    items_coll.document(item_id).set(item_data)

    stock_coll = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock")
    stock_coll.document(f"{item_id}_wh-main").set({
        "id": f"{item_id}_wh-main",
        "itemId": item_id,
        "warehouseId": "wh-main",
        "quantity": 50.0,
    })

    # 2. Factura original emitida con costo original $45.00
    orig_invoice_id = "inv-orig-100"
    orig_invoice = {
        "id": orig_invoice_id,
        "invoiceNumber": "E310000000100",
        "encf": "E310000000100",
        "status": "Emitida",
        "warehouseId": "wh-main",
        "items": [
            {
                "id": "line-orig-1",
                "code": "PROD-001",
                "name": "Laptop Pro",
                "type": "Bien",
                "price": 100.0,
                "quantity": 10,
                "subtotal": 1000.0,
                "total": 1180.0,
                "unitCost": 45.0,
                "originalCost": 45.0,
                "costPrice": 45.0
            }
        ]
    }
    store["invoices"][orig_invoice_id] = orig_invoice

    # 3. Registrar venta (SALIDA de 10)
    tx_venta = {
        "itemId": item_id,
        "itemName": "Laptop Pro",
        "type": "SALIDA",
        "quantity": 10.0,
        "unitCost": 45.0,
        "reason": "VENTA",
        "referenceType": "INVOICE",
        "referenceId": "E310000000100",
        "originWarehouseId": "wh-main",
        "destinationWarehouseId": "",
    }
    InventoryTransactionService.execute_transaction(owner_uid, company_id, tx_venta, sandbox=True)

    # Verificar stock post-venta: 40
    stock_doc = stock_coll.document(f"{item_id}_wh-main").get()
    assert stock_doc.to_dict()["quantity"] == 40.0
    item_doc = items_coll.document(item_id).get()
    assert item_doc.to_dict()["totalStock"] == 40.0

    # 4. Crear y procesar Nota de Crédito E34 con reingreso físico de 5 unidades
    credit_note_id = "nc-001"
    credit_note = {
        "id": credit_note_id,
        "invoiceNumber": "NC-E310000000100",
        "ecfType": "Nota de Crédito (E34)",
        "status": "Emitida",
        "referenceInvoiceId": orig_invoice_id,
        "warehouseId": "wh-main",
        "informationReference": {
            "modificationCode": 1,  # Devolución
            "ncfModified": "E310000000100"
        },
        "items": [
            {
                "id": item_id,
                "originalLineId": "line-orig-1",
                "code": "PROD-001",
                "name": "Laptop Pro",
                "type": "Bien",
                "price": 100.0,
                "quantity": 5,
                "subtotal": 500.0,
                "total": 590.0,
                "reingresoStock": True,
                "warehouseId": "wh-main"
            }
        ]
    }

    # Procesar reingreso
    txs = CreditNoteInventoryService.process_credit_note_stock_reentry(
        owner_uid=owner_uid,
        company_id=company_id,
        credit_note_dict=credit_note,
        sandbox=True
    )

    assert len(txs) == 1
    tx_rec = txs[0]
    assert tx_rec["type"] == "ENTRADA"
    assert tx_rec["reason"] == "DEVOLUCION_CLIENTE"
    assert tx_rec["quantity"] == 5.0
    # Costo recuperado de la venta original ($45.00), no del catálogo actual ($60.00)
    assert tx_rec["unitCost"] == 45.0
    assert tx_rec["totalValue"] == 225.0
    assert tx_rec["referenceType"] == "CREDIT_NOTE"

    # Verificar existencias físicas: 40 + 5 = 45
    stock_doc = stock_coll.document(f"{item_id}_wh-main").get()
    assert stock_doc.to_dict()["quantity"] == 45.0
    item_doc = items_coll.document(item_id).get()
    assert item_doc.to_dict()["totalStock"] == 45.0

    # Trazabilidad en el item
    assert credit_note["stockReentered"] is True
    assert credit_note["items"][0]["originalCost"] == 45.0
    assert credit_note["items"][0]["quantityReturned"] == 5.0
    assert credit_note["items"][0]["originalInvoiceId"] == orig_invoice_id


def test_e34_without_physical_return_leaves_stock_untouched(setup_environment):
    """
    Escenario 3:
    - E34 por corrección de precio / descuento comercial (`reingresoStock: False`).
    - NO debe generar movimientos de inventario ni alterar existencias.
    """
    store = setup_environment
    company_id = "comp-fase5a"
    owner_uid = "user-123"

    item_id = "prod-002"
    item_data = {
        "id": item_id,
        "code": "PROD-002",
        "name": "Monitor 4K",
        "type": "Bien",
        "totalStock": 20.0,
        "costPrice": 150.0,
    }
    store["items"][item_id] = item_data
    items_coll = store["client"].collection(f"companies/{company_id}/sandbox_items")
    items_coll.document(item_id).set(item_data)

    stock_coll = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock")
    stock_coll.document(f"{item_id}_wh-main").set({
        "id": f"{item_id}_wh-main",
        "itemId": item_id,
        "warehouseId": "wh-main",
        "quantity": 20.0,
    })

    credit_note = {
        "id": "nc-002",
        "invoiceNumber": "NC-DESCUENTO",
        "ecfType": "Nota de Crédito (E34)",
        "status": "Emitida",
        "informationReference": {
            "modificationCode": 3,  # Descuento
            "ncfModified": "E310000000200"
        },
        "items": [
            {
                "id": item_id,
                "code": "PROD-002",
                "name": "Monitor 4K (Ajuste de Precio)",
                "type": "Bien",
                "price": 30.0,
                "quantity": 2,
                "reingresoStock": False  # Sin devolución física
            }
        ]
    }

    txs = CreditNoteInventoryService.process_credit_note_stock_reentry(
        owner_uid=owner_uid,
        company_id=company_id,
        credit_note_dict=credit_note,
        sandbox=True
    )

    assert len(txs) == 0
    assert credit_note.get("stockReentered") is not True

    # El stock debe permanecer intacto en 20.0
    stock_doc = stock_coll.document(f"{item_id}_wh-main").get()
    assert stock_doc.to_dict()["quantity"] == 20.0
    item_doc = items_coll.document(item_id).get()
    assert item_doc.to_dict()["totalStock"] == 20.0


def test_e34_service_item_never_generates_inventory_movement(setup_environment):
    """
    Escenario 4:
    - E34 para líneas de servicio (`type: 'Servicio'`).
    - No debe generar movimientos de inventario bajo ninguna circunstancia.
    """
    store = setup_environment
    company_id = "comp-fase5a"
    owner_uid = "user-123"

    credit_note = {
        "id": "nc-003",
        "invoiceNumber": "NC-SERVICIO",
        "ecfType": "Nota de Crédito (E34)",
        "status": "Emitida",
        "items": [
            {
                "id": "srv-001",
                "name": "Servicio de Consultoría IT",
                "type": "Servicio",
                "price": 5000.0,
                "quantity": 1,
                "reingresoStock": True  # Aunque venga en True, debe ser ignorado por ser Servicio
            }
        ]
    }

    txs = CreditNoteInventoryService.process_credit_note_stock_reentry(
        owner_uid=owner_uid,
        company_id=company_id,
        credit_note_dict=credit_note,
        sandbox=True
    )

    assert len(txs) == 0
    assert credit_note.get("stockReentered") is not True
    assert credit_note["items"][0]["reingresoStock"] is False


def test_e34_destination_warehouse_routing(setup_environment):
    """
    Escenario 6:
    - Devolución a un almacén diferente al de la factura original.
    - Se verifica que solo el almacén destino recibe el stock.
    """
    store = setup_environment
    company_id = "comp-fase5a"
    owner_uid = "user-123"

    item_id = "prod-003"
    item_data = {
        "id": item_id,
        "code": "PROD-003",
        "name": "Teclado Mecánico",
        "type": "Bien",
        "totalStock": 30.0,
        "costPrice": 25.0,
    }
    store["items"][item_id] = item_data
    items_coll = store["client"].collection(f"companies/{company_id}/sandbox_items")
    items_coll.document(item_id).set(item_data)

    stock_coll = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock")
    stock_coll.document(f"{item_id}_wh-main").set({
        "id": f"{item_id}_wh-main",
        "itemId": item_id,
        "warehouseId": "wh-main",
        "quantity": 30.0,
    })
    stock_coll.document(f"{item_id}_wh-secondary").set({
        "id": f"{item_id}_wh-secondary",
        "itemId": item_id,
        "warehouseId": "wh-secondary",
        "quantity": 0.0,
    })

    credit_note = {
        "id": "nc-004",
        "invoiceNumber": "NC-ROUTING",
        "ecfType": "Nota de Crédito (E34)",
        "status": "Emitida",
        "warehouseId": "wh-secondary",  # Destino almacén secundario
        "items": [
            {
                "id": item_id,
                "code": "PROD-003",
                "name": "Teclado Mecánico",
                "type": "Bien",
                "price": 50.0,
                "quantity": 8,
                "reingresoStock": True,
                "warehouseId": "wh-secondary",
                "unitCost": 25.0
            }
        ]
    }

    txs = CreditNoteInventoryService.process_credit_note_stock_reentry(
        owner_uid=owner_uid,
        company_id=company_id,
        credit_note_dict=credit_note,
        sandbox=True
    )

    assert len(txs) == 1
    # wh-main permanece en 30
    assert stock_coll.document(f"{item_id}_wh-main").get().to_dict()["quantity"] == 30.0
    # wh-secondary incrementa en +8
    assert stock_coll.document(f"{item_id}_wh-secondary").get().to_dict()["quantity"] == 8.0
    # Total consolidado = 38
    assert items_coll.document(item_id).get().to_dict()["totalStock"] == 38.0


def test_e34_idempotency_prevents_double_reentry(setup_environment):
    """
    Escenario 7:
    - Reintentar procesar la misma E34 no debe duplicar el reingreso de stock.
    """
    store = setup_environment
    company_id = "comp-fase5a"
    owner_uid = "user-123"

    item_id = "prod-005"
    item_data = {
        "id": item_id,
        "code": "PROD-005",
        "name": "Mouse Gamer",
        "type": "Bien",
        "totalStock": 15.0,
        "costPrice": 12.0,
    }
    store["items"][item_id] = item_data
    items_coll = store["client"].collection(f"companies/{company_id}/sandbox_items")
    items_coll.document(item_id).set(item_data)

    stock_coll = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock")
    stock_coll.document(f"{item_id}_wh-main").set({
        "id": f"{item_id}_wh-main",
        "itemId": item_id,
        "warehouseId": "wh-main",
        "quantity": 15.0,
    })

    credit_note = {
        "id": "nc-idem-001",
        "invoiceNumber": "NC-IDEM-001",
        "ecfType": "Nota de Crédito (E34)",
        "status": "Emitida",
        "warehouseId": "wh-main",
        "items": [
            {
                "id": item_id,
                "code": "PROD-005",
                "name": "Mouse Gamer",
                "type": "Bien",
                "price": 25.0,
                "quantity": 3,
                "reingresoStock": True,
                "unitCost": 12.0
            }
        ]
    }

    # Primera ejecución
    txs_1 = CreditNoteInventoryService.process_credit_note_stock_reentry(
        owner_uid=owner_uid, company_id=company_id, credit_note_dict=credit_note, sandbox=True
    )
    assert len(txs_1) == 1
    assert stock_coll.document(f"{item_id}_wh-main").get().to_dict()["quantity"] == 18.0

    # Segunda ejecución (retry)
    txs_2 = CreditNoteInventoryService.process_credit_note_stock_reentry(
        owner_uid=owner_uid, company_id=company_id, credit_note_dict=credit_note, sandbox=True
    )
    # Ya marcado como stockReentered -> retorna lista vacía sin re-procesar
    assert len(txs_2) == 0
    assert stock_coll.document(f"{item_id}_wh-main").get().to_dict()["quantity"] == 18.0


def test_e34_anulacion_reverts_reentered_stock(setup_environment):
    """
    Escenario 8:
    - Anular una Nota de Crédito que reingresó mercancía debe revertir la entrada.
    """
    store = setup_environment
    company_id = "comp-fase5a"
    owner_uid = "user-123"

    item_id = "prod-006"
    item_data = {
        "id": item_id,
        "code": "PROD-006",
        "name": "Silla Ergonómica",
        "type": "Bien",
        "totalStock": 10.0,
        "costPrice": 80.0,
    }
    store["items"][item_id] = item_data
    items_coll = store["client"].collection(f"companies/{company_id}/sandbox_items")
    items_coll.document(item_id).set(item_data)

    stock_coll = store["client"].collection(f"companies/{company_id}/sandbox_inventory_stock")
    stock_coll.document(f"{item_id}_wh-main").set({
        "id": f"{item_id}_wh-main",
        "itemId": item_id,
        "warehouseId": "wh-main",
        "quantity": 10.0,
    })

    credit_note = {
        "id": "nc-anular-001",
        "invoiceNumber": "NC-ANULAR-001",
        "ecfType": "Nota de Crédito (E34)",
        "status": "Emitida",
        "warehouseId": "wh-main",
        "items": [
            {
                "id": item_id,
                "code": "PROD-006",
                "name": "Silla Ergonómica",
                "type": "Bien",
                "price": 150.0,
                "quantity": 2,
                "reingresoStock": True,
                "unitCost": 80.0
            }
        ]
    }

    # 1. Emitir E34 -> Stock pasa de 10 a 12
    CreditNoteInventoryService.process_credit_note_stock_reentry(
        owner_uid=owner_uid, company_id=company_id, credit_note_dict=credit_note, sandbox=True
    )
    assert stock_coll.document(f"{item_id}_wh-main").get().to_dict()["quantity"] == 12.0
    assert credit_note["stockReentered"] is True

    # 2. Anular E34 -> Stock regresa de 12 a 10
    credit_note["status"] = "Anulada"
    rev_txs = CreditNoteInventoryService.revert_credit_note_stock_reentry(
        owner_uid=owner_uid, company_id=company_id, credit_note_dict=credit_note, sandbox=True
    )

    assert len(rev_txs) == 1
    assert rev_txs[0]["type"] == "SALIDA"
    assert rev_txs[0]["quantity"] == 2.0
    assert stock_coll.document(f"{item_id}_wh-main").get().to_dict()["quantity"] == 10.0
    assert items_coll.document(item_id).get().to_dict()["totalStock"] == 10.0
    assert credit_note["stockReverted"] is True
