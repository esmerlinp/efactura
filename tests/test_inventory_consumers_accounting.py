"""
Pruebas de Integración para la Fase 7C: Integración con Consumidores de Inventario.

Verifica la conexión post-commit de:
1. 7C.1: Recepción de mercancías (GoodsReceiptService) -> D Inventario / C Mercancía Recibida no Facturada.
2. 7C.2: Ventas / Facturación (DatabaseService.save_invoice) -> D Costo de Ventas / C Inventario (FIFO real, sin doble COGS).
3. 7C.3: Devoluciones en Notas de Crédito E34 (CreditNoteInventoryService) -> D Inventario / C Costo de Ventas.
4. 7C.4: Conteos Físicos y Mermas (PhysicalCountService) -> D Inventario / C Ganancia o D Pérdida Merma / C Inventario.
5. Caso E2E Completo: Cadena completa Compra -> Venta -> E34 -> Conteo y Conciliación Kardex <-> Contabilidad.
"""

import pytest
import contextlib
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app.services.inventory_accounting_service import InventoryAccountingService
from app.services.inventory_transaction_service import InventoryTransactionService
from app.services.inventory_costing_service import InventoryCostingService
from app.services.goods_receipt_service import GoodsReceiptService
from app.services.credit_note_inventory_service import CreditNoteInventoryService
from app.services.physical_count_service import PhysicalCountService
from app.services.db_service import DatabaseService
from app.services.kardex_service import KardexService
from app.services.accounting_service import AccountingService


MOCK_CHART_OF_ACCOUNTS = [
    {"id": "acc-inv", "code": "1.1.3.1.01", "name": "Inventario de Mercancías", "usage": "inventario", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-cogs", "code": "5.1.1.1.01", "name": "Costo de Ventas", "usage": "costo_ventas", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-merma", "code": "6.1.2.9.01", "name": "Merma / Pérdida en Inventario", "usage": "merma_perdida", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-ajuste", "code": "4.1.2.9.01", "name": "Ajuste de Inventario Ganancia", "usage": "ajuste_inventario", "type": "movimiento", "nature": "acreedora"},
    {"id": "acc-transito", "code": "2.1.1.2.01", "name": "Mercancía Recibida no Facturada", "usage": "mercancia_transito", "type": "movimiento", "nature": "acreedora"},
    {"id": "acc-cxc", "code": "1.1.2.1.01", "name": "Cuentas por Cobrar Clientes", "usage": "cxc", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-caja", "code": "1.1.1.1.01", "name": "Caja General", "usage": "efectivo", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-banco", "code": "1.1.1.2.01", "name": "Banco", "usage": "banco", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-cxp", "code": "2.1.1.1.01", "name": "Cuentas por Pagar Proveedores", "usage": "cxp", "type": "movimiento", "nature": "acreedora"},
    {"id": "acc-ventas", "code": "4.1.1.1.01", "name": "Ingresos por Ventas", "usage": "ventas", "type": "movimiento", "nature": "acreedora"},
    {"id": "acc-itbis", "code": "2.1.2.1.01", "name": "ITBIS por Pagar", "usage": "itbis_pagar", "type": "movimiento", "nature": "acreedora"},
]


class MockFieldFilter:
    def __init__(self, field_path=None, op_string=None, value=None):
        self.field_path = field_path
        self.op_string = op_string
        self.value = value


class MockDocumentSnapshot:
    def __init__(self, doc_id, data=None, exists=True):
        self.id = doc_id
        self._data = dict(data) if data is not None else {}
        self.exists = exists

    def to_dict(self):
        return dict(self._data)


class MockDocumentReference:
    def __init__(self, coll, doc_id):
        self.coll = coll
        self.id = doc_id

    def collection(self, name):
        if hasattr(self.coll, "client") and self.coll.client:
            return self.coll.client.collection(f"{self.coll.name}/{self.id}/{name}")
        return MockCollectionReference(f"{self.coll.name}/{self.id}/{name}", client=getattr(self.coll, "client", None))

    def get(self, transaction=None):
        data = self.coll._storage.get(self.id)
        if data is not None:
            return MockDocumentSnapshot(self.id, data=data, exists=True)
        return MockDocumentSnapshot(self.id, data=None, exists=False)

    def set(self, data, merge=False):
        if merge and self.id in self.coll._storage:
            self.coll._storage[self.id].update(dict(data))
        else:
            self.coll._storage[self.id] = dict(data)

    def update(self, data):
        if self.id in self.coll._storage:
            self.coll._storage[self.id].update(dict(data))
        else:
            self.coll._storage[self.id] = dict(data)


class MockCollectionReference:
    def __init__(self, name, client=None):
        self.name = name
        self.client = client
        self._storage = {}

    def document(self, doc_id):
        return MockDocumentReference(self, doc_id)

    def where(self, field=None, op=None, val=None, filter=None):
        if filter is not None:
            if isinstance(filter, MockFieldFilter):
                field = filter.field_path
                op = filter.op_string
                val = filter.value
            elif hasattr(filter, "field_path") and not isinstance(filter.field_path, MagicMock):
                field = filter.field_path
                val = getattr(filter, "value", None)
            elif hasattr(filter, "_field_path") and not isinstance(filter._field_path, MagicMock):
                field = filter._field_path
                val = getattr(filter, "_value", None)
            elif isinstance(filter, MagicMock):
                parent = getattr(filter, "_mock_parent", None)
                if parent and hasattr(parent, "call_args") and parent.call_args:
                    args = parent.call_args[0] if isinstance(parent.call_args, tuple) else parent.call_args.args
                    if len(args) >= 3:
                        field, op, val = args[0], args[1], args[2]
                    elif len(args) == 1:
                        field = args[0]
                elif hasattr(filter, "call_args") and filter.call_args:
                    args = filter.call_args[0] if isinstance(filter.call_args, tuple) else filter.call_args.args
                    if len(args) >= 3:
                        field, op, val = args[0], args[1], args[2]
                    elif len(args) == 1:
                        field = args[0]
        
        field_str = str(field) if field is not None else None
        matches = []
        for k, v in self._storage.items():
            if field_str is None or str(v.get(field_str)) == str(val):
                matches.append(MockDocumentSnapshot(k, data=v, exists=True))
        
        mock_query = MagicMock()
        mock_query.get.return_value = matches
        mock_query.stream.return_value = matches
        mock_query.limit.side_effect = lambda n: mock_query
        mock_query.order_by.side_effect = lambda *a, **k: mock_query
        mock_query.where.side_effect = lambda *a, **k: mock_query
        return mock_query

    def order_by(self, *args, **kwargs):
        mock_query = MagicMock()
        items = [MockDocumentSnapshot(k, data=v, exists=True) for k, v in self._storage.items()]
        mock_query.get.return_value = items
        mock_query.stream.return_value = items
        mock_query.limit.side_effect = lambda n: mock_query
        mock_query.where.side_effect = self.where
        return mock_query

    def stream(self):
        for k, v in list(self._storage.items()):
            yield MockDocumentSnapshot(k, data=v, exists=True)

    def get(self, transaction=None):
        return [MockDocumentSnapshot(k, data=v, exists=True) for k, v in list(self._storage.items())]

    def __bool__(self):
        return True

    def __len__(self):
        return len(self._storage)

    def __getitem__(self, key):
        return self._storage[key]

    def __contains__(self, key):
        return key in self._storage


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
            self.collections[name] = MockCollectionReference(name, client=self)
        return self.collections[name]

    def transaction(self):
        txn = MockFirestoreTransaction(self)

        def runner(fn):
            return fn(txn)

        txn.__call__ = runner
        return txn


@pytest.fixture
def mock_erp_env():
    """Entorno simulado con base de datos unificada para inventario, capas FIFO, postings y asientos."""
    client = MockFirestoreClient()
    entries_store = []
    items_store = {}
    warehouses_list = [{"id": "wh-central", "name": "Almacén Central", "branchId": "branch-1"}]

    def mock_company_coll(company_id=None, owner_uid=None, coll_name=""):
        full_name = f"companies/{company_id}/{coll_name}"
        coll = client.collection(full_name)
        # Sincronizar catálogo con items_store
        if "items" in coll_name:
            for item_id, item_data in items_store.items():
                if item_id not in coll._storage:
                    coll._storage[item_id] = item_data
        return coll

    def mock_save_entry(cid, eid, entry, **kwargs):
        entries_store.append(dict(entry))
        return entry

    def mock_get_items(uid=None, sandbox=True, company_id=None, owner_uid=None, **kwargs):
        return list(items_store.values())

    def mock_get_warehouses(uid=None, sandbox=True, company_id=None, owner_uid=None, **kwargs):
        return warehouses_list

    def set_item(item_id, item_dict, company_id="comp-01"):
        items_store[item_id] = dict(item_dict)
        client.collection(f"companies/{company_id}/sandbox_items").document(item_id).set(item_dict)
        client.collection(f"companies/{company_id}/items").document(item_id).set(item_dict)

    mock_gc = MagicMock()
    mock_gc.FieldFilter = MockFieldFilter
    mock_gc.firestore.FieldFilter = MockFieldFilter
    mock_gc.SERVER_TIMESTAMP = datetime.now(timezone.utc).isoformat()
    mock_gc.transactional = lambda fn: fn

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.dict("sys.modules", {"google.cloud.firestore": mock_gc}))
        stack.enter_context(patch("app.services.db_service._company_coll", side_effect=mock_company_coll))
        stack.enter_context(patch("app.services.db_service.db_firestore", client))
        stack.enter_context(patch("app.services.db_service.firebase_initialized", True))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_chart_of_accounts", return_value=MOCK_CHART_OF_ACCOUNTS))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_accounting_entries", side_effect=lambda *a, **k: entries_store))
        stack.enter_context(patch("app.services.db_service.DatabaseService.save_accounting_entry", side_effect=mock_save_entry))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_next_entry_number", side_effect=lambda cid, prefix="A", **k: f"{prefix}-2026-{len(entries_store)+1:04d}"))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_items", side_effect=mock_get_items))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses))
        stack.enter_context(patch("app.services.inventory_transaction_service._company_coll", side_effect=mock_company_coll))
        stack.enter_context(patch("app.services.inventory_transaction_service.db_firestore", client))
        stack.enter_context(patch("app.services.inventory_transaction_service.firebase_initialized", True))
        stack.enter_context(patch("app.services.inventory_transaction_service.DatabaseService.get_items", side_effect=mock_get_items))
        stack.enter_context(patch("app.services.inventory_transaction_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses))
        stack.enter_context(patch("app.services.inventory_accounting_service._company_coll", side_effect=mock_company_coll))
        stack.enter_context(patch("app.services.inventory_accounting_service.db_firestore", client))
        stack.enter_context(patch("app.services.inventory_accounting_service.firebase_initialized", True))
        stack.enter_context(patch("app.services.kardex_service._company_coll", side_effect=mock_company_coll))
        stack.enter_context(patch("app.services.kardex_service.db_firestore", client))
        stack.enter_context(patch("app.services.kardex_service.firebase_initialized", True))
        stack.enter_context(patch("app.services.kardex_service.DatabaseService.get_items", side_effect=mock_get_items))
        stack.enter_context(patch("app.services.kardex_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses))
        stack.enter_context(patch("app.services.credit_note_inventory_service._company_coll", side_effect=mock_company_coll))
        stack.enter_context(patch("app.services.credit_note_inventory_service.db_firestore", client))
        stack.enter_context(patch("app.services.credit_note_inventory_service.firebase_initialized", True))
        stack.enter_context(patch("app.services.credit_note_inventory_service.DatabaseService.get_items", side_effect=mock_get_items))
        stack.enter_context(patch("app.services.credit_note_inventory_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses))
        stack.enter_context(patch("app.services.goods_receipt_service._company_coll", side_effect=mock_company_coll))
        stack.enter_context(patch("app.services.goods_receipt_service.db_firestore", client))
        stack.enter_context(patch("app.services.goods_receipt_service.firebase_initialized", True))
        stack.enter_context(patch("app.services.goods_receipt_service.DatabaseService.get_warehouses", side_effect=mock_get_warehouses))
        stack.enter_context(patch("app.services.fiscal_period_service.FiscalPeriodService.validate_period_open", return_value=None))
        stack.enter_context(patch("app.services.ledger_audit_service.LedgerAuditService.log_entry_creation", return_value=None))

        yield {
            "client": client,
            "entries": entries_store,
            "items": items_store,
            "set_item": set_item,
            "get_coll": lambda coll_name, comp_id="comp-01": client.collection(f"companies/{comp_id}/{coll_name}"),
        }


# ═════════════════════════════════════════════════════════════════════════════
# 7C.1: RECEPCIÓN DE MERCANCÍA (GoodsReceiptService -> InventoryAccountingService)
# ═════════════════════════════════════════════════════════════════════════════

def test_7c1_goods_receipt_triggers_inventory_and_grni_accounting(mock_erp_env):
    """
    Recepción de mercancía de compra:
    10 unidades @ RD$ 100.00
    Debe generar:
      - Transacción física de inventario (ENTRADA / COMPRA, totalValue = 1000.00)
      - Capa FIFO de costo = 1000.00
      - Asiento contable:
          Débito: Inventario de Mercancías RD$ 1,000.00
          Crédito: Mercancía Recibida no Facturada RD$ 1,000.00
      - InventoryPosting en estado POSTED
    """
    company_id = "comp-01"
    owner_uid = "comp-01"

    # Registrar item en catálogo
    mock_erp_env["set_item"]("art-100", {"id": "art-100", "code": "INV-01", "name": "Inversor 3.5KW", "costPrice": 100.0, "totalStock": 0})

    receipt_data = {
        "id": "rc-001",
        "receiptNumber": "RC-2026-0001",
        "poId": "po-100",
        "poNumber": "OC-2026-0050",
        "warehouseId": "wh-central",
        "warehouseName": "Almacén Central",
        "receiptDate": "2026-10-06",
        "createdBy": "almacenero@vykone.com",
        "items": [
            {
                "itemId": "art-100",
                "itemName": "Inversor 3.5KW",
                "receivedQuantity": 10.0,
                "unitCost": 100.00,
            }
        ]
    }

    registered = GoodsReceiptService.register_receipt_inventory(company_id, receipt_data, sandbox=True, owner_uid=owner_uid)
    assert len(registered) == 1
    tx = registered[0]
    assert tx["type"] == "ENTRADA"
    assert tx["reason"] == "COMPRA"
    assert tx["totalValue"] == 1000.00

    # Verificar contabilización automática
    assert len(mock_erp_env["entries"]) == 1
    entry = mock_erp_env["entries"][0]
    assert entry["totalDebit"] == 1000.00
    assert entry["totalCredit"] == 1000.00

    # Líneas contables: Débito Inventario, Crédito Mercancía no facturada
    debit_line = next(l for l in entry["lines"] if l["debit"] > 0)
    credit_line = next(l for l in entry["lines"] if l["credit"] > 0)
    assert debit_line["accountId"] == "acc-inv"
    assert credit_line["accountId"] == "acc-transito"

    # Verificar posting
    posting = InventoryAccountingService.get_inventory_posting_by_tx(company_id, tx["id"], sandbox=True)
    assert posting is not None
    assert posting["status"] == "POSTED"
    assert posting["amount"] == 1000.00
    assert posting["journalEntryId"] == entry["id"]


def test_7c1_goods_receipt_idempotent_retry_prevents_duplicate_entry(mock_erp_env):
    """
    Ejecutar doble llamada a register_receipt_inventory no duplica inventario ni asientos contables.
    """
    company_id = "comp-01"
    owner_uid = "comp-01"

    mock_erp_env["set_item"]("art-100", {"id": "art-100", "code": "INV-01", "name": "Inversor 3.5KW", "costPrice": 100.0, "totalStock": 0})

    receipt_data = {
        "id": "rc-002",
        "receiptNumber": "RC-2026-0002",
        "warehouseId": "wh-central",
        "receiptDate": "2026-10-06",
        "createdBy": "almacenero@vykone.com",
        "items": [{"itemId": "art-100", "itemName": "Inversor 3.5KW", "receivedQuantity": 5.0, "unitCost": 120.00}]
    }

    # Primer registro
    reg1 = GoodsReceiptService.register_receipt_inventory(company_id, receipt_data, sandbox=True, owner_uid=owner_uid)
    assert len(mock_erp_env["entries"]) == 1

    # Segundo registro (reintento)
    reg2 = GoodsReceiptService.register_receipt_inventory(company_id, receipt_data, sandbox=True, owner_uid=owner_uid)
    
    # Debe mantenerse exactamente 1 asiento contable
    assert len(mock_erp_env["entries"]) == 1
    postings_coll = mock_erp_env["get_coll"]("sandbox_inventory_postings")
    assert len(postings_coll) == 1


# ═════════════════════════════════════════════════════════════════════════════
# 7C.2: VENTAS / FACTURACIÓN (save_invoice -> FIFO COGS contable único)
# ═════════════════════════════════════════════════════════════════════════════

def test_7c2_sale_invoice_emits_fifo_cogs_without_legacy_double_cogs(mock_erp_env):
    """
    Flujo de Venta:
    1. Existencia: 10 @ RD$ 100.00 + 10 @ RD$ 120.00
    2. Venta de 15 unidades en Factura E31:
       - 10 @ 100 = 1,000
       - 5 @ 120 = 600
       - COGS FIFO real = RD$ 1,600.00
    3. Contabilidad de inventario genera:
       Débito: Costo de Ventas RD$ 1,600.00
       Crédito: Inventario de Mercancías RD$ 1,600.00
    4. El asiento financiero de la factura (auto_generate_invoice_entry) contiene
       únicamente ingresos, CxC e impuestos, SIN líneas estimadas de COGS duplicadas.
    """
    company_id = "comp-01"
    owner_uid = "comp-01"

    # 1. Crear stock y capas iniciales
    mock_erp_env["set_item"]("art-laptop", {"id": "art-laptop", "code": "LAP-01", "name": "Laptop ThinkPad", "costPrice": 100.0, "totalStock": 0})
    
    # Capa 1: 10 @ 100
    InventoryTransactionService.execute_transaction(
        owner_uid, company_id,
        {"itemId": "art-laptop", "itemName": "Laptop", "type": "ENTRADA", "quantity": 10, "unitCost": 100.0, "destinationWarehouseId": "wh-central", "reason": "COMPRA"},
        sandbox=True
    )
    # Capa 2: 10 @ 120
    InventoryTransactionService.execute_transaction(
        owner_uid, company_id,
        {"itemId": "art-laptop", "itemName": "Laptop", "type": "ENTRADA", "quantity": 10, "unitCost": 120.0, "destinationWarehouseId": "wh-central", "reason": "COMPRA"},
        sandbox=True
    )
    
    # Limpiar asientos de las entradas para aislar la prueba de la venta
    mock_erp_env["entries"].clear()

    # 2. Emitir Factura de Venta de 15 unidades
    invoice_dict = {
        "id": "inv-sale-001",
        "invoiceNumber": "E3100000050",
        "clientName": "Acme Corp",
        "clientRnc": "101010101",
        "paymentType": "Crédito",
        "warehouseId": "wh-central",
        "date": "2026-10-06",
        "dueDate": "2026-10-06",
        "status": "Emitida",
        "subtotal": 30000.00,
        "tax": 5400.00,
        "itbis": 5400.00,
        "totalITBIS": 5400.00,
        "total": 35400.00,
        "items": [
            {
                "id": "art-laptop",
                "name": "Laptop ThinkPad",
                "type": "Bien",
                "quantity": 15.0,
                "price": 2000.00,
                "unitPrice": 2000.00,
                "costPrice": 100.00,  # Precio de catálogo desactualizado
                "subtotal": 30000.00,
                "tax": 5400.00,
                "itbisAmount": 5400.00,
                "total": 35400.00
            }
        ]
    }

    # Guardar factura (descuenta stock físico + genera COGS contable FIFO)
    DatabaseService.save_invoice(owner_uid, "inv-sale-001", invoice_dict, sandbox=True, company_id=company_id)

    # 3. Generar asiento comercial de la factura
    commercial_entry = AccountingService.auto_generate_invoice_entry(company_id, invoice_dict, sandbox=True)
    assert commercial_entry is not None

    # Verificar que el asiento comercial NO tiene líneas de Costo de Ventas ni Inventario
    cogs_in_commercial = [l for l in commercial_entry["lines"] if l["accountId"] in ("acc-cogs", "acc-inv")]
    assert len(cogs_in_commercial) == 0

    # 4. Verificar que el asiento de COGS generado por InventoryAccountingService es exacto a RD$ 1,600
    inv_entries = [e for e in mock_erp_env["entries"] if e.get("entryType") == "inventory"]
    assert len(inv_entries) == 1
    cogs_entry = inv_entries[0]
    assert cogs_entry["totalDebit"] == 1600.00
    assert cogs_entry["totalCredit"] == 1600.00

    debit_cogs = next(l for l in cogs_entry["lines"] if l["accountId"] == "acc-cogs")
    credit_inv = next(l for l in cogs_entry["lines"] if l["accountId"] == "acc-inv")
    assert debit_cogs["debit"] == 1600.00
    assert credit_inv["credit"] == 1600.00


# ═════════════════════════════════════════════════════════════════════════════
# 7C.3: NOTAS DE CRÉDITO E34 (CreditNoteInventoryService -> InventoryAccountingService)
# ═════════════════════════════════════════════════════════════════════════════

def test_7c3_credit_note_physical_return_and_skip_when_no_reentry(mock_erp_env):
    """
    Notas de Crédito E34:
    - Con reingresoStock=True: genera reingreso físico + D Inventario / C Costo de Ventas.
    - Con reingresoStock=False: no genera movimiento de inventario ni asiento de inventario.
    """
    company_id = "comp-01"
    owner_uid = "comp-01"

    mock_erp_env["set_item"]("art-dev", {"id": "art-dev", "code": "BAT-01", "name": "Batería Trojan", "costPrice": 100.0, "totalStock": 10})

    # Caso A: E34 con reingreso físico de 2 unidades @ RD$ 100.00 = RD$ 200.00
    nc_with_reentry = {
        "id": "nc-e34-001",
        "invoiceNumber": "E3400000010",
        "ecfType": "E34",
        "clientName": "Cliente Devolución",
        "warehouseId": "wh-central",
        "date": "2026-10-06",
        "dueDate": "2026-10-06",
        "status": "Emitida",
        "items": [
            {
                "id": "art-dev",
                "name": "Batería Trojan",
                "type": "Bien",
                "quantity": 2.0,
                "quantityReturned": 2.0,
                "originalCost": 100.00,
                "reingresoStock": True,
                "price": 150.00,
                "unitPrice": 150.00,
            }
        ]
    }

    txs_a = CreditNoteInventoryService.process_credit_note_stock_reentry(owner_uid, company_id, nc_with_reentry, sandbox=True)
    assert len(txs_a) == 1
    assert txs_a[0]["type"] == "ENTRADA"
    assert txs_a[0]["reason"] == "DEVOLUCION_CLIENTE"
    assert txs_a[0]["totalValue"] == 200.00

    # Debe haber 1 asiento contable de inventario: D Inventario 200 / C Costo de Ventas 200
    assert len(mock_erp_env["entries"]) == 1
    entry_a = mock_erp_env["entries"][0]
    assert entry_a["totalDebit"] == 200.00
    debit_line = next(l for l in entry_a["lines"] if l["accountId"] == "acc-inv")
    credit_line = next(l for l in entry_a["lines"] if l["accountId"] == "acc-cogs")
    assert debit_line["debit"] == 200.00
    assert credit_line["credit"] == 200.00

    # Caso B: E34 sin reingreso físico (reingresoStock=False, ej. descuento o ajuste comercial)
    nc_without_reentry = {
        "id": "nc-e34-002",
        "invoiceNumber": "E3400000011",
        "ecfType": "E34",
        "clientName": "Cliente Descuento",
        "warehouseId": "wh-central",
        "date": "2026-10-06",
        "dueDate": "2026-10-06",
        "status": "Emitida",
        "items": [
            {
                "id": "art-dev",
                "name": "Batería Trojan",
                "type": "Bien",
                "quantity": 1.0,
                "reingresoStock": False,
                "price": 50.00,
                "unitPrice": 50.00,
            }
        ]
    }

    txs_b = CreditNoteInventoryService.process_credit_note_stock_reentry(owner_uid, company_id, nc_without_reentry, sandbox=True)
    assert len(txs_b) == 0
    # No deben haberse añadido nuevos asientos de inventario
    assert len(mock_erp_env["entries"]) == 1


# ═════════════════════════════════════════════════════════════════════════════
# 7C.4: CONTEO FÍSICO / MERMA (PhysicalCountService -> InventoryAccountingService)
# ═════════════════════════════════════════════════════════════════════════════

def test_7c4_physical_count_surplus_and_shortage_accounting(mock_erp_env):
    """
    Ajuste por conteo físico:
    - Sobrante (diff > 0): D Inventario / C Ganancia por Ajuste.
    - Faltante / Merma (diff < 0): D Pérdida por Merma / C Inventario.
    """
    company_id = "comp-01"
    owner_uid = "comp-01"

    mock_erp_env["set_item"]("art-cable", {"id": "art-cable", "code": "CAB-01", "name": "Cable Solar", "costPrice": 50.0, "totalStock": 0})
    mock_erp_env["set_item"]("art-fusible", {"id": "art-fusible", "code": "FUS-01", "name": "Fusible DC", "costPrice": 20.0, "totalStock": 0})

    # Crear stock base
    InventoryTransactionService.execute_transaction(
        owner_uid, company_id,
        {"itemId": "art-cable", "itemName": "Cable Solar", "type": "ENTRADA", "quantity": 100, "unitCost": 50.0, "destinationWarehouseId": "wh-central", "reason": "COMPRA"},
        sandbox=True
    )
    InventoryTransactionService.execute_transaction(
        owner_uid, company_id,
        {"itemId": "art-fusible", "itemName": "Fusible DC", "type": "ENTRADA", "quantity": 50, "unitCost": 20.0, "destinationWarehouseId": "wh-central", "reason": "COMPRA"},
        sandbox=True
    )
    mock_erp_env["entries"].clear()

    count_doc = {
        "id": "count-100",
        "warehouseId": "wh-central",
        "warehouseName": "Almacén Central",
        "status": "en_progreso",
        "startedDate": "2026-10-06T10:00:00Z",
        "lines": [
            # Sobrante de 5 cables @ 50.00 = +250.00
            {
                "itemId": "art-cable",
                "itemName": "Cable Solar",
                "systemQuantity": 100.0,
                "physicalQuantity": 105.0,
                "difference": 5.0,
                "costPrice": 50.00
            },
            # Faltante (merma) de 2 fusibles @ 20.00 = -40.00
            {
                "itemId": "art-fusible",
                "itemName": "Fusible DC",
                "systemQuantity": 50.0,
                "physicalQuantity": 48.0,
                "difference": -2.0,
                "costPrice": 20.00
            }
        ]
    }
    mock_erp_env["get_coll"]("sandbox_physical_counts").document("count-100").set(count_doc)

    success, _ = PhysicalCountService.finalize_count(
        company_id=company_id,
        count_id="count-100",
        finalized_by="auditor@vykone.com",
        sandbox=True,
        owner_uid=owner_uid
    )
    assert success is True

    # Deben haberse generado 2 asientos contables de inventario
    assert len(mock_erp_env["entries"]) == 2

    # Asiento 1 (Sobrante Cable): D Inventario 250 / C Ajuste Ganancia 250
    entry_surplus = next(e for e in mock_erp_env["entries"] if e["totalDebit"] == 250.00)
    assert any(l["accountId"] == "acc-inv" and l["debit"] == 250.00 for l in entry_surplus["lines"])
    assert any(l["accountId"] == "acc-ajuste" and l["credit"] == 250.00 for l in entry_surplus["lines"])

    # Asiento 2 (Faltante Fusible): D Pérdida Merma 40 / C Inventario 40
    entry_shortage = next(e for e in mock_erp_env["entries"] if e["totalDebit"] == 40.00)
    assert any(l["accountId"] == "acc-merma" and l["debit"] == 40.00 for l in entry_shortage["lines"])
    assert any(l["accountId"] == "acc-inv" and l["credit"] == 40.00 for l in entry_shortage["lines"])


# ═════════════════════════════════════════════════════════════════════════════
# 7C.5: PRUEBA DE INTEGRACIÓN COMPLETA E2E Y CONCILIACIÓN
# ═════════════════════════════════════════════════════════════════════════════

def test_7c5_full_e2e_integration_and_continuous_reconciliation(mock_erp_env):
    """
    Prueba E2E obligatoria:
    1. COMPRA 10 @ 100 -> Recepción RC -> Inventario=10, FIFO=1000 -> D Inventario 1000 / C GRNI 1000
    2. VENTA 6 -> Factura -> FIFO COGS=600 -> D COGS 600 / C Inventario 600
    3. E34 físico 2 -> NC -> Costo histórico=200 -> D Inventario 200 / C COGS 200
    4. Conteo -1 -> Merma -> D Merma 100 / C Inventario 100
    5. Balance final de existencias:
       10 - 6 + 2 - 1 = 5 unidades @ 100.00 = RD$ 500.00
    6. Conciliación Kardex <-> Capas FIFO <-> Contabilidad sin diferencias.
    """
    company_id = "comp-01"
    owner_uid = "comp-01"
    item_id = "art-panel-solar"

    mock_erp_env["set_item"](item_id, {
        "id": item_id,
        "name": "Panel Solar 550W",
        "code": "PS-550",
        "costPrice": 100.00,
        "totalStock": 0.0
    })

    # ── PASO 1: COMPRA Y RECEPCIÓN 10 @ 100 ──
    receipt = {
        "id": "rc-e2e-1",
        "receiptNumber": "RC-2026-0099",
        "warehouseId": "wh-central",
        "receiptDate": "2026-10-06",
        "dueDate": "2026-10-06",
        "createdBy": "compras@vykone.com",
        "items": [{"itemId": item_id, "itemName": "Panel Solar 550W", "receivedQuantity": 10.0, "unitCost": 100.00}]
    }
    GoodsReceiptService.register_receipt_inventory(company_id, receipt, sandbox=True, owner_uid=owner_uid)

    # ── PASO 2: VENTA DE 6 UNIDADES ──
    invoice = {
        "id": "inv-e2e-1",
        "invoiceNumber": "E3100000099",
        "clientName": "Cliente Sol",
        "paymentType": "Crédito",
        "warehouseId": "wh-central",
        "date": "2026-10-06",
        "dueDate": "2026-10-06",
        "status": "Emitida",
        "subtotal": 12000.00,
        "tax": 2160.00,
        "itbis": 2160.00,
        "totalITBIS": 2160.00,
        "total": 14160.00,
        "items": [{"id": item_id, "name": "Panel Solar 550W", "type": "Bien", "quantity": 6.0, "price": 2000.00, "unitPrice": 2000.00, "costPrice": 100.00, "subtotal": 12000.00, "itbisAmount": 2160.00, "total": 14160.00}]
    }
    DatabaseService.save_invoice(owner_uid, "inv-e2e-1", invoice, sandbox=True, company_id=company_id)

    # ── PASO 3: DEVOLUCIÓN FÍSICA E34 DE 2 UNIDADES ──
    credit_note = {
        "id": "nc-e2e-1",
        "invoiceNumber": "E3400000099",
        "ecfType": "E34",
        "clientName": "Cliente Sol",
        "warehouseId": "wh-central",
        "date": "2026-10-06",
        "dueDate": "2026-10-06",
        "status": "Emitida",
        "items": [
            {
                "id": item_id,
                "name": "Panel Solar 550W",
                "type": "Bien",
                "quantity": 2.0,
                "quantityReturned": 2.0,
                "originalCost": 100.00,
                "reingresoStock": True,
                "price": 2000.00,
                "unitPrice": 2000.00,
            }
        ]
    }
    CreditNoteInventoryService.process_credit_note_stock_reentry(owner_uid, company_id, credit_note, sandbox=True)

    # ── PASO 4: CONTEO FÍSICO FALTANTE DE 1 UNIDAD (MERMA) ──
    count = {
        "id": "count-e2e-1",
        "warehouseId": "wh-central",
        "warehouseName": "Almacén Central",
        "status": "en_progreso",
        "startedDate": "2026-10-06T10:00:00Z",
        "lines": [
            {
                "itemId": item_id,
                "itemName": "Panel Solar 550W",
                "systemQuantity": 6.0,
                "physicalQuantity": 5.0,
                "difference": -1.0,
                "costPrice": 100.00
            }
        ]
    }
    mock_erp_env["get_coll"]("sandbox_physical_counts").document("count-e2e-1").set(count)

    success, _ = PhysicalCountService.finalize_count(
        company_id=company_id,
        count_id="count-e2e-1",
        finalized_by="auditor@vykone.com",
        sandbox=True,
        owner_uid=owner_uid
    )
    assert success is True

    # ── VERIFICACIONES Y CONCILIACIÓN CONTINUA ──

    # 1. Existencia física final: 10 - 6 + 2 - 1 = 5 unidades
    stock_doc = mock_erp_env["get_coll"]("sandbox_inventory_stock").document(f"{item_id}_wh-central").get().to_dict()
    assert stock_doc["quantity"] == 5.0

    # 2. Capas FIFO activas: 5 unidades @ 100.00 = RD$ 500.00
    active_layers = [r for r in InventoryCostingService.get_fifo_ledger(company_id, item_id, warehouse_id="wh-central", sandbox=True) if r.get("balanceQty", 0) > 0]
    remaining_qty = sum(l.get("balanceQty", 0.0) for l in active_layers)
    remaining_val = sum(l.get("balanceQty", 0.0) * l.get("unitCost", 0.0) for l in active_layers)
    assert remaining_qty == 5.0
    assert remaining_val == 500.00

    # 3. Kardex valorizado
    kardex_res = KardexService.get_kardex(company_id, item_id, sandbox=True, owner_uid=owner_uid)
    assert len(kardex_res["movements"]) == 4
    assert kardex_res["finalBalance"]["quantity"] == 5.0
    assert kardex_res["finalBalance"]["totalValue"] == 500.00

    # 4. Asientos contables generados: 4 asientos de inventario
    inv_entries = [e for e in mock_erp_env["entries"] if e.get("entryType") == "inventory"]
    assert len(inv_entries) == 4

    # Asiento 1: Recepción (D 1000 / C 1000)
    assert any(e["totalDebit"] == 1000.00 and any(l["accountId"] == "acc-transito" for l in e["lines"]) for e in inv_entries)
    # Asiento 2: Venta COGS (D 600 / C 600)
    assert any(e["totalDebit"] == 600.00 and any(l["accountId"] == "acc-cogs" and l["debit"] == 600.00 for l in e["lines"]) for e in inv_entries)
    # Asiento 3: E34 Devolución (D 200 / C 200)
    assert any(e["totalDebit"] == 200.00 and any(l["accountId"] == "acc-inv" and l["debit"] == 200.00 for l in e["lines"]) for e in inv_entries)
    # Asiento 4: Merma (D 100 / C 100)
    assert any(e["totalDebit"] == 100.00 and any(l["accountId"] == "acc-merma" and l["debit"] == 100.00 for l in e["lines"]) for e in inv_entries)

    # 5. Saldo Neto en Cuenta de Inventario Contable (1.1.3.1.01):
    # +1000 (Recepción) - 600 (Venta) + 200 (E34) - 100 (Merma) = RD$ 500.00 Débito
    net_inv_balance = 0.0
    for e in inv_entries:
        for l in e["lines"]:
            if l["accountId"] == "acc-inv":
                net_inv_balance += float(l.get("debit", 0)) - float(l.get("credit", 0))

    assert round(net_inv_balance, 2) == 500.00

    # 6. Auditoría de InventoryPostings: Cero discrepancias
    audit = InventoryAccountingService.audit_unposted_inventory_transactions(company_id, sandbox=True, owner_uid=owner_uid)
    assert audit["totalTransactions"] == 4
    assert audit["postedCount"] == 4
    assert audit["unpostedCount"] == 0
    assert audit["failedCount"] == 0
    assert audit["status"] == "OK"
