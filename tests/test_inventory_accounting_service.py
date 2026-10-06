"""Pruebas unitarias para InventoryAccountingService (Fase 7B)."""

import pytest
from unittest.mock import patch, MagicMock
from app.services.inventory_accounting_service import InventoryAccountingService


MOCK_CHART_OF_ACCOUNTS = [
    {"id": "acc-inv", "code": "1.1.3.1.01", "name": "Inventario de Mercancías", "usage": "inventario", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-cogs", "code": "5.1.1.1.01", "name": "Costo de Ventas", "usage": "costo_ventas", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-merma", "code": "6.1.2.9.01", "name": "Merma / Pérdida en Inventario", "usage": "merma_perdida", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-ajuste", "code": "4.1.2.9.01", "name": "Ajuste de Inventario Ganancia", "usage": "ajuste_inventario", "type": "movimiento", "nature": "acreedora"},
    {"id": "acc-transito", "code": "2.1.1.2.01", "name": "Mercancía Recibida no Facturada", "usage": "mercancia_transito", "type": "movimiento", "nature": "acreedora"},
    {"id": "acc-cxc", "code": "1.1.2.1.01", "name": "Cuentas por Cobrar Clientes", "usage": "cxc", "type": "movimiento", "nature": "deudora"},
    {"id": "acc-cxp", "code": "2.1.1.1.01", "name": "Cuentas por Pagar Proveedores", "usage": "cxp", "type": "movimiento", "nature": "acreedora"},
]


class MockDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data else {}


class MockPostingsCollection:
    def __init__(self):
        self._store = {}

    def document(self, doc_id):
        mock_ref = MagicMock()
        mock_ref.get.side_effect = lambda: MockDoc(doc_id, self._store.get(doc_id))
        mock_ref.set.side_effect = lambda data: self._store.update({doc_id: data})
        mock_ref.update.side_effect = lambda data: self._store.get(doc_id, {}).update(data)
        return mock_ref

    def where(self, field, op, val):
        matches = []
        for k, v in self._store.items():
            if v.get(field) == val:
                matches.append(MockDoc(k, v))
        mock_query = MagicMock()
        mock_query.get.return_value = matches
        mock_query.stream.return_value = matches
        mock_query.limit.return_value = mock_query
        return mock_query

    def stream(self):
        return [MockDoc(k, v) for k, v in self._store.items()]

    def __bool__(self):
        return True

    def __len__(self):
        return len(self._store)

    def __getitem__(self, key):
        return self._store[key]

    def __contains__(self, key):
        return key in self._store




@pytest.fixture
def mock_db_env():
    postings_mock = MockPostingsCollection()
    entries_store = []

    def mock_save_entry(cid, eid, entry, **kwargs):
        entries_store.append(dict(entry))
        return entry

    with patch("app.services.db_service.DatabaseService.get_chart_of_accounts", return_value=MOCK_CHART_OF_ACCOUNTS), \
         patch("app.services.db_service.DatabaseService.get_accounting_entries", side_effect=lambda *a, **k: entries_store), \
         patch("app.services.db_service.DatabaseService.save_accounting_entry", side_effect=mock_save_entry), \
         patch("app.services.db_service.DatabaseService.get_next_entry_number", side_effect=lambda cid, prefix="A", **k: f"{prefix}-2026-{len(entries_store)+1:04d}"), \
         patch("app.services.fiscal_period_service.FiscalPeriodService.validate_period_open", return_value=None), \
         patch("app.services.ledger_audit_service.LedgerAuditService.log_entry_creation", return_value=None), \
         patch.object(InventoryAccountingService, "_postings_coll", return_value=postings_mock):
        yield {"postings": postings_mock, "entries": entries_store}




# ═════════════════════════════════════════════════════════════════════════════
# CASO 1: VENTA FIFO (COGS RD$ 1,600)
# ═════════════════════════════════════════════════════════════════════════════

def test_1_venta_fifo_cogs_accounting(mock_db_env):
    """
    Venta de 15 unidades con consumo FIFO:
    10 @ RD$100.00 + 5 @ RD$120.00 = COGS RD$1,600.00
    Debe generar:
      Débito: Costo de Ventas RD$ 1,600.00
      Crédito: Inventario de Mercancías RD$ 1,600.00
    """
    company_id = "comp-01"
    tx_venta = {
        "id": "tx-sale-001",
        "type": "SALIDA",
        "reason": "VENTA",
        "itemId": "art-01",
        "itemName": "Taladro Percutor",
        "quantity": 15.0,
        "totalValue": 1600.00,
        "costLayers": [
            {"layerId": "L1", "consumedQuantity": 10.0, "unitCost": 100.0, "totalCost": 1000.0},
            {"layerId": "L2", "consumedQuantity": 5.0, "unitCost": 120.0, "totalCost": 600.0}
        ],
        "referenceType": "invoice",
        "referenceId": "inv-001",
        "documentNumber": "E3100000045",
        "date": "2026-10-06T10:00:00Z",
        "performedBy": "cajero@vykone.com"
    }

    res = InventoryAccountingService.post_inventory_transaction(company_id, tx_venta)
    assert res["success"] is True
    assert res["status"] == "POSTED"
    
    posting = res["posting"]
    assert posting["inventoryTransactionId"] == "tx-sale-001"
    assert posting["amount"] == 1600.00
    assert posting["entryDate"] == "2026-10-06"
    assert posting["journalEntryNumber"] == "A-2026-0001"

    # Verificar asiento generado
    entry = res["journalEntry"]
    assert entry["totalDebit"] == 1600.00
    assert entry["totalCredit"] == 1600.00
    assert len(entry["lines"]) == 2

    # Línea Débito: Costo de Ventas
    line_debit = entry["lines"][0]
    assert line_debit["accountId"] == "acc-cogs"
    assert line_debit["debit"] == 1600.00
    assert line_debit["credit"] == 0.00

    # Línea Crédito: Inventario
    line_credit = entry["lines"][1]
    assert line_credit["accountId"] == "acc-inv"
    assert line_credit["debit"] == 0.00
    assert line_credit["credit"] == 1600.00


# ═════════════════════════════════════════════════════════════════════════════
# CASO 2: RETRY IDEMPOTENCIA (NUNCA DUPLICAR ASIENTOS)
# ═════════════════════════════════════════════════════════════════════════════

def test_2_retry_idempotency_prevents_duplicate_journal_entry(mock_db_env):
    """
    Llamar dos veces a post_inventory_transaction con la misma tx:
    Resultado: Exactamente 1 asiento contable y 1 posting, sin duplicidad.
    """
    company_id = "comp-01"
    tx = {
        "id": "tx-sale-002",
        "type": "SALIDA",
        "reason": "VENTA",
        "itemId": "art-01",
        "itemName": "Taladro Percutor",
        "quantity": 10.0,
        "totalValue": 1000.00,
        "referenceId": "inv-002",
        "documentNumber": "E3100000046",
        "date": "2026-10-06T10:15:00Z"
    }

    # Primer intento
    res1 = InventoryAccountingService.post_inventory_transaction(company_id, tx)
    assert res1["success"] is True
    assert res1["status"] == "POSTED"
    entry1_id = res1["journalEntryId"]

    # Segundo intento (retry)
    res2 = InventoryAccountingService.post_inventory_transaction(company_id, tx)
    assert res2["success"] is True
    assert res2["status"] == "POSTED"
    assert res2.get("idempotent") is True
    assert res2["journalEntryId"] == entry1_id

    # Comprobar que en el almacenamiento de asientos solo hay 1
    assert len(mock_db_env["entries"]) == 1


# ═════════════════════════════════════════════════════════════════════════════
# CASO 3: NOTA DE CRÉDITO E34 CON DEVOLUCIÓN FÍSICA
# ═════════════════════════════════════════════════════════════════════════════

def test_3_e34_physical_return_reenters_inventory_cost(mock_db_env):
    """
    Devolución física E34 de 5 uds @ RD$106.6667 = RD$533.33:
    Debe generar:
      Débito: Inventario de Mercancías RD$ 533.33
      Crédito: Costo de Ventas RD$ 533.33
    """
    company_id = "comp-01"
    tx_e34 = {
        "id": "tx-e34-001",
        "type": "ENTRADA",
        "reason": "DEVOLUCION_CLIENTE",
        "itemId": "art-01",
        "itemName": "Taladro Percutor",
        "quantity": 5.0,
        "totalValue": 533.33,
        "referenceType": "credit_note",
        "referenceId": "cn-001",
        "documentNumber": "E3400000005",
        "date": "2026-10-06T11:00:00Z",
    }

    res = InventoryAccountingService.post_inventory_transaction(company_id, tx_e34)
    assert res["success"] is True
    assert res["status"] == "POSTED"
    
    entry = res["journalEntry"]
    assert entry["totalDebit"] == 533.33
    assert entry["totalCredit"] == 533.33
    
    # Débito Inventario
    assert entry["lines"][0]["accountId"] == "acc-inv"
    assert entry["lines"][0]["debit"] == 533.33
    # Crédito Costo de Ventas
    assert entry["lines"][1]["accountId"] == "acc-cogs"
    assert entry["lines"][1]["credit"] == 533.33


# ═════════════════════════════════════════════════════════════════════════════
# CASO 4: E34 SIN REINGRESO FÍSICO O MOVIMIENTO CON VALOR 0
# ═════════════════════════════════════════════════════════════════════════════

def test_4_zero_value_or_no_physical_return_skips_inventory_entry(mock_db_env):
    """
    Si una transacción tiene totalValue 0 (o sin impacto económico de inventario):
    No genera asiento financiero, marca status SKIPPED_NEUTRAL.
    """
    company_id = "comp-01"
    tx_zero = {
        "id": "tx-zero-001",
        "type": "ENTRADA",
        "reason": "DEVOLUCION_CLIENTE",
        "itemId": "art-serv",
        "quantity": 1.0,
        "totalValue": 0.00,
        "referenceId": "cn-service",
        "date": "2026-10-06T11:05:00Z"
    }

    res = InventoryAccountingService.post_inventory_transaction(company_id, tx_zero)
    assert res["success"] is True
    assert res["status"] == "SKIPPED_NEUTRAL"
    assert len(mock_db_env["entries"]) == 0


# ═════════════════════════════════════════════════════════════════════════════
# CASO 5: RECEPCIÓN DE COMPRA (GOODS RECEIPT)
# ═════════════════════════════════════════════════════════════════════════════

def test_5_goods_receipt_inventory_accounting(mock_db_env):
    """
    Recepción de mercancía (RC-2026-0001) por 10 unidades @ RD$100.00 = RD$1,000.00:
    Debe generar:
      Débito: Inventario de Mercancías RD$ 1,000.00
      Crédito: Mercancía Recibida no Facturada / Tránsito RD$ 1,000.00
    """
    company_id = "comp-01"
    tx_receipt = {
        "id": "tx-gr-001",
        "type": "ENTRADA",
        "reason": "COMPRA",
        "itemId": "art-01",
        "itemName": "Taladro Percutor",
        "quantity": 10.0,
        "totalValue": 1000.00,
        "referenceType": "GOODS_RECEIPT",
        "referenceId": "RC-2026-0001",
        "documentNumber": "RC-2026-0001",
        "date": "2026-10-06T09:00:00Z"
    }

    res = InventoryAccountingService.post_inventory_transaction(company_id, tx_receipt)
    assert res["success"] is True
    assert res["status"] == "POSTED"

    entry = res["journalEntry"]
    assert entry["totalDebit"] == 1000.00
    assert entry["totalCredit"] == 1000.00
    assert entry["lines"][0]["accountId"] == "acc-inv"
    assert entry["lines"][0]["debit"] == 1000.00
    assert entry["lines"][1]["accountId"] == "acc-transito"
    assert entry["lines"][1]["credit"] == 1000.00


# ═════════════════════════════════════════════════════════════════════════════
# CASO 6: AJUSTE FÍSICO POSITIVO (SOBRANTE)
# ═════════════════════════════════════════════════════════════════════════════

def test_6_positive_physical_count_adjustment_accounting(mock_db_env):
    """
    Ajuste positivo por recuento físico (+2 unidades @ RD$100 = RD$200.00):
    Debe generar:
      Débito: Inventario de Mercancías RD$ 200.00
      Crédito: Ganancia en Ajuste de Inventario RD$ 200.00
    """
    company_id = "comp-01"
    tx_adj_pos = {
        "id": "tx-adj-pos-001",
        "type": "ENTRADA",
        "reason": "RECUENTO_FISICO",
        "itemId": "art-01",
        "itemName": "Taladro Percutor",
        "quantity": 2.0,
        "totalValue": 200.00,
        "referenceType": "PHYSICAL_COUNT",
        "referenceId": "CF-2026-001",
        "date": "2026-10-06T12:00:00Z"
    }

    res = InventoryAccountingService.post_inventory_transaction(company_id, tx_adj_pos)
    assert res["success"] is True
    assert res["status"] == "POSTED"

    entry = res["journalEntry"]
    assert entry["lines"][0]["accountId"] == "acc-inv"
    assert entry["lines"][0]["debit"] == 200.00
    assert entry["lines"][1]["accountId"] == "acc-ajuste"
    assert entry["lines"][1]["credit"] == 200.00


# ═════════════════════════════════════════════════════════════════════════════
# CASO 7: AJUSTE FÍSICO NEGATIVO / MERMA (FALTANTE)
# ═════════════════════════════════════════════════════════════════════════════

def test_7_negative_physical_count_or_merma_accounting(mock_db_env):
    """
    Ajuste negativo / merma (-1 unidad consumida en FIFO @ RD$120 = RD$120.00):
    Debe generar:
      Débito: Merma / Pérdida en Inventario RD$ 120.00
      Crédito: Inventario de Mercancías RD$ 120.00
    """
    company_id = "comp-01"
    tx_merma = {
        "id": "tx-merma-001",
        "type": "SALIDA",
        "reason": "MERMA",
        "itemId": "art-01",
        "itemName": "Taladro Percutor",
        "quantity": 1.0,
        "totalValue": 120.00,
        "referenceType": "PHYSICAL_COUNT",
        "referenceId": "CF-2026-001",
        "date": "2026-10-06T12:30:00Z"
    }

    res = InventoryAccountingService.post_inventory_transaction(company_id, tx_merma)
    assert res["success"] is True
    assert res["status"] == "POSTED"

    entry = res["journalEntry"]
    assert entry["lines"][0]["accountId"] == "acc-merma"
    assert entry["lines"][0]["debit"] == 120.00
    assert entry["lines"][1]["accountId"] == "acc-inv"
    assert entry["lines"][1]["credit"] == 120.00


# ═════════════════════════════════════════════════════════════════════════════
# CASO 8: REVERSIÓN NO DESTRUCTIVA (NUEVO ASIENTO INVERSO)
# ═════════════════════════════════════════════════════════════════════════════

def test_8_reversal_creates_new_opposite_entry_preserves_original(mock_db_env):
    """
    Reversión de una venta:
    1. El asiento original A-2026-0001 permanece POSTED.
    2. Se genera un NUEVO asiento A-2026-0002 con líneas invertidas.
    3. El posting original pasa a REVERSED con referencia al reversalEntryId.
    """
    company_id = "comp-01"
    tx = {
        "id": "tx-sale-rev-01",
        "type": "SALIDA",
        "reason": "VENTA",
        "itemId": "art-01",
        "itemName": "Taladro",
        "quantity": 5.0,
        "totalValue": 500.00,
        "referenceId": "inv-rev",
        "date": "2026-10-06T13:00:00Z"
    }

    # 1. Contabilizar venta
    post_res = InventoryAccountingService.post_inventory_transaction(company_id, tx)
    orig_entry_id = post_res["journalEntryId"]
    posting_id = post_res["posting"]["id"]

    # 2. Revertir
    reversal_tx = {"id": "tx-sale-rev-01-reversal", "date": "2026-10-06T13:30:00Z"}
    rev_res = InventoryAccountingService.reverse_posting(
        company_id=company_id,
        posting_id_or_tx_id="tx-sale-rev-01",
        reversal_tx=reversal_tx,
        reason="Factura anulada por cliente",
        user_id="admin@vykone.com"
    )

    assert rev_res["success"] is True
    assert rev_res["status"] == "REVERSED"
    
    reversal_entry = rev_res["reversalEntry"]
    assert reversal_entry["id"] != orig_entry_id
    assert reversal_entry["referenceType"] == "inventory_reversal"
    assert reversal_entry["reversalOfEntryId"] == orig_entry_id

    # En el asiento de reversión: Débito es Inventario y Crédito es Costo de Ventas
    assert reversal_entry["lines"][0]["accountId"] == "acc-cogs"
    assert reversal_entry["lines"][0]["debit"] == 0.00
    assert reversal_entry["lines"][0]["credit"] == 500.00

    assert reversal_entry["lines"][1]["accountId"] == "acc-inv"
    assert reversal_entry["lines"][1]["debit"] == 500.00
    assert reversal_entry["lines"][1]["credit"] == 0.00

    # Total de asientos en base de datos: 2 (Original + Reversión)
    assert len(mock_db_env["entries"]) == 2


# ═════════════════════════════════════════════════════════════════════════════
# CASO 9: MANEJO DE ERROR POR PERÍODO FISCAL CERRADO
# ═════════════════════════════════════════════════════════════════════════════

def test_9_closed_fiscal_period_marks_posting_failed(mock_db_env):
    """
    Si el período contable está cerrado en la fecha económica (entryDate):
    El movimiento físico ya está seguro en inventario, pero el posting pasa a FAILED.
    """
    company_id = "comp-01"
    tx_closed = {
        "id": "tx-closed-001",
        "type": "SALIDA",
        "reason": "VENTA",
        "itemId": "art-01",
        "quantity": 10.0,
        "totalValue": 1000.00,
        "date": "2026-08-15T10:00:00Z"  # Agosto cerrado
    }

    with patch("app.services.fiscal_period_service.FiscalPeriodService.validate_period_open", side_effect=ValueError("El período fiscal 2026-08 está cerrado.")):
        res = InventoryAccountingService.post_inventory_transaction(company_id, tx_closed)
        assert res["success"] is False
        assert res["status"] == "FAILED"
        assert "período fiscal 2026-08 está cerrado" in res["error"]
        assert res["posting"]["status"] == "FAILED"
        assert res["posting"]["entryDate"] == "2026-08-15"


# ═════════════════════════════════════════════════════════════════════════════
# CASO 10: TRANSFERENCIA NEUTRAL ENTRE ALMACENES
# ═════════════════════════════════════════════════════════════════════════════

def test_10_internal_warehouse_transfer_is_neutral(mock_db_env):
    """
    Transferencia entre Almacén Central y Almacén Secundario dentro de la misma empresa
    utilizando la misma cuenta general de inventario:
    Se marca SKIPPED_NEUTRAL, sin generar asiento financiero.
    """
    company_id = "comp-01"
    tx_transf = {
        "id": "tx-tr-001",
        "type": "TRANSFERENCIA",
        "reason": "TRANSFERENCIA",
        "itemId": "art-01",
        "quantity": 10.0,
        "totalValue": 1000.00,
        "originWarehouseId": "wh-central",
        "destinationWarehouseId": "wh-norte",
        "date": "2026-10-06T14:00:00Z"
    }

    res = InventoryAccountingService.post_inventory_transaction(company_id, tx_transf)
    assert res["success"] is True
    assert res["status"] == "SKIPPED_NEUTRAL"
    assert len(mock_db_env["entries"]) == 0


# ═════════════════════════════════════════════════════════════════════════════
# CASO 11: AUDITORÍA DE TRANSACCIONES NO CONTABILIZADAS
# ═════════════════════════════════════════════════════════════════════════════

def test_11_audit_unposted_inventory_transactions(mock_db_env):
    """
    audit_unposted_inventory_transactions compara inventory_transactions con inventory_postings
    y reporta transacciones pendientes o fallidas.
    """
    company_id = "comp-01"
    mock_txs = [
        {"id": "tx-ok-1", "type": "SALIDA", "reason": "VENTA", "totalValue": 500.0, "date": "2026-10-06"},
        {"id": "tx-unposted-2", "type": "SALIDA", "reason": "VENTA", "totalValue": 750.0, "date": "2026-10-06"}
    ]

    # Contabilizar solo tx-ok-1
    InventoryAccountingService.post_inventory_transaction(company_id, mock_txs[0])

    audit = InventoryAccountingService.audit_unposted_inventory_transactions(company_id, transactions=mock_txs)
    assert audit["totalTransactions"] == 2
    assert audit["postedCount"] == 1
    assert audit["unpostedCount"] == 1
    assert audit["status"] == "DISCREPANCY"
    assert audit["unpostedTransactions"][0]["txId"] == "tx-unposted-2"


# ═════════════════════════════════════════════════════════════════════════════
# CASO 12: CONCURRENCIA REAL (WORKERS CONCURRENTES MISMA TRANSACCIÓN)
# ═════════════════════════════════════════════════════════════════════════════

def test_12_concurrent_workers_same_transaction(mock_db_env):
    """
    Múltiples workers concurrentes intentando contabilizar la misma transacción física
    deben producir exactamente 1 JournalEntry y 1 InventoryPosting, y todos deben
    recibir el mismo journalEntryId.
    """
    import concurrent.futures

    company_id = "comp-01"
    tx = {
        "id": "tx-concurrent-100",
        "type": "SALIDA",
        "reason": "VENTA",
        "totalValue": 1600.00,
        "quantity": 15,
        "itemName": "Laptop Dell",
        "documentNumber": "E3100000099",
        "date": "2026-10-06T10:00:00Z"
    }

    results = []
    num_workers = 10

    def worker_task():
        return InventoryAccountingService.post_inventory_transaction(company_id, tx)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_task) for _ in range(num_workers)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    assert len(results) == num_workers
    for res in results:
        assert res["success"] is True
        assert res["status"] == "POSTED"

    # Todos los workers deben recibir el mismo journalEntryId
    first_entry_id = results[0]["journalEntryId"]
    assert all(r["journalEntryId"] == first_entry_id for r in results)

    # La base de datos debe tener exactamente 1 asiento y 1 posting
    assert len(mock_db_env["entries"]) == 1
    assert len(mock_db_env["postings"]) == 1


# ═════════════════════════════════════════════════════════════════════════════
# CASO 13: RETRY DESPUÉS DE FALLO (POST -> FAILED -> RETRY -> POSTED -> RETRY)
# ═════════════════════════════════════════════════════════════════════════════

def test_13_retry_lifecycle_failed_then_posted_then_retry(mock_db_env):
    """
    Flujo:
    1. post_inventory_transaction() falla (ej. período cerrado) -> FAILED, 0 asientos.
    2. retry_failed_posting() tras abrir período -> POSTED, 1 asiento generado.
    3. retry_failed_posting() posterior -> POSTED con alreadyPosted=True y mismo asiento.
    """
    company_id = "comp-01"
    tx = {
        "id": "tx-retry-lifecycle-1",
        "type": "SALIDA",
        "reason": "VENTA",
        "totalValue": 800.00,
        "quantity": 5,
        "itemName": "Monitor LG",
        "documentNumber": "E3100000105",
        "date": "2026-09-15T10:00:00Z"
    }

    # 1. Simular período cerrado para septiembre
    with patch("app.services.fiscal_period_service.FiscalPeriodService.validate_period_open", side_effect=ValueError("Período fiscal cerrado")):
        res_fail = InventoryAccountingService.post_inventory_transaction(company_id, tx)
        assert res_fail["success"] is False
        assert res_fail["status"] == "FAILED"
        assert len(mock_db_env["entries"]) == 0
        assert len(mock_db_env["postings"]) == 1
        posting_id = res_fail["posting"]["id"]
        assert res_fail["posting"]["status"] == "FAILED"

    # 2. Reintento con período abierto
    res_retry_1 = InventoryAccountingService.retry_failed_posting(company_id, posting_id, tx=tx)
    assert res_retry_1["success"] is True
    assert res_retry_1["status"] == "POSTED"
    assert len(mock_db_env["entries"]) == 1
    journal_entry_id = res_retry_1["journalEntryId"]
    assert journal_entry_id is not None

    # Verificar que el posting en la BD quedó POSTED y con retryCount incrementado
    assert mock_db_env["postings"][posting_id]["status"] == "POSTED"
    assert mock_db_env["postings"][posting_id]["retryCount"] >= 1

    # 3. Reintento subsecuente: debe ser completamente idempotente
    res_retry_2 = InventoryAccountingService.retry_failed_posting(company_id, posting_id, tx=tx)
    assert res_retry_2["success"] is True
    assert res_retry_2["status"] == "POSTED"
    assert res_retry_2.get("alreadyPosted") is True
    assert res_retry_2["posting"]["journalEntryId"] == journal_entry_id
    assert len(mock_db_env["entries"]) == 1


# ═════════════════════════════════════════════════════════════════════════════
# CASO 14: MULTIEMPRESA CONCURRENTE (AISLAMIENTO ESTRICTO)
# ═════════════════════════════════════════════════════════════════════════════

def test_14_multi_company_concurrency_isolation(mock_db_env):
    """
    Verifica que transacciones con el mismo ID en distintas empresas generen
    asientos y postings completamente aislados sin reutilizar o colisionar.
    """
    comp_a = "company-AAA"
    comp_b = "company-BBB"

    tx_a = {
        "id": "tx-same-id-999",
        "type": "SALIDA",
        "reason": "VENTA",
        "totalValue": 1000.00,
        "quantity": 10,
        "itemName": "Item A",
        "documentNumber": "E3100000001",
        "date": "2026-10-06"
    }
    tx_b = {
        "id": "tx-same-id-999",
        "type": "SALIDA",
        "reason": "VENTA",
        "totalValue": 2500.00,
        "quantity": 25,
        "itemName": "Item B",
        "documentNumber": "E3100000002",
        "date": "2026-10-06"
    }

    res_a = InventoryAccountingService.post_inventory_transaction(comp_a, tx_a)
    res_b = InventoryAccountingService.post_inventory_transaction(comp_b, tx_b)

    assert res_a["success"] is True
    assert res_b["success"] is True

    # Deben ser 2 asientos distintos y con importes distintos
    assert res_a["journalEntryId"] != res_b["journalEntryId"]
    assert res_a["posting"]["idempotencyKey"] == f"{comp_a}|INVENTORY|tx-same-id-999"
    assert res_b["posting"]["idempotencyKey"] == f"{comp_b}|INVENTORY|tx-same-id-999"
    assert res_a["posting"]["amount"] == 1000.00
    assert res_b["posting"]["amount"] == 2500.00

    assert len(mock_db_env["entries"]) == 2
    assert len(mock_db_env["postings"]) == 2


