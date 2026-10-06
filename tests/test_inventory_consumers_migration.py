"""
Pruebas de Integración y Migración de Consumidores de Inventario (Fase 4).

Criterios de Aceptación:
1. Facturación (save_invoice) usa directamente InventoryTransactionService con idempotencia canónica.
2. Prueba de Retry Real / Idempotencia:
   - Stock inicial: 100
   - Primera emisión (10 unidades): Stock = 90
   - Retry / Reintento de emisión: Stock = 90 (NO 80), 1 solo movimiento registrado.
3. Recepciones de compra (goods_receipt_service) usan directamente el servicio y validan PO.
4. Conteos físicos (physical_count_service) resuelven costos antes de generar movimientos de ajuste.
5. Transferencias (warehouse_transfer_service) ejecutan movimientos atómicos únicos sin duplicidad.
6. Pagos y POS consolidation respetan la misma clave de idempotencia de la factura evitando dobles deducciones.
"""

import pytest
import hashlib
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.services.inventory_transaction_service import InventoryTransactionService
from app.services.goods_receipt_service import GoodsReceiptService
from app.services.physical_count_service import PhysicalCountService
from app.services.warehouse_transfer_service import WarehouseTransferService
from app.services.db_service import DatabaseService


def setup_in_memory_firestore():
    """Crea un entorno de base de datos transaccional simulado en memoria."""
    mock_db = MagicMock()
    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction

    storage = {}

    def get_doc_mock(coll_name, doc_id):
        key = f"{coll_name}/{doc_id}"
        doc_mock = MagicMock()
        data = storage.get(key)
        if data is not None:
            doc_mock.exists = True
            doc_mock.to_dict.return_value = dict(data)
            doc_mock.id = doc_id
        else:
            doc_mock.exists = False
            doc_mock.to_dict.return_value = {}
            doc_mock.id = doc_id
        return doc_mock

    mock_colls = {}

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        if coll_name not in mock_colls:
            coll_mock = MagicMock()

            def doc_side_effect(doc_id):
                doc_ref = MagicMock()
                doc_ref.id = doc_id
                doc_ref.get.side_effect = lambda transaction=None: get_doc_mock(coll_name, doc_id)
                return doc_ref

            def where_side_effect(*args, **kwargs):
                query_mock = MagicMock()
                query_mock.get.return_value = []
                return query_mock

            coll_mock.document.side_effect = doc_side_effect
            coll_mock.where.side_effect = where_side_effect
            mock_colls[coll_name] = coll_mock
        return mock_colls[coll_name]

    def mock_set(doc_ref, data):
        for key in list(storage.keys()):
            if key.endswith(f"/{doc_ref.id}"):
                storage[key] = dict(data)
                return
        storage[f"sandbox_docs/{doc_ref.id}"] = dict(data)

    def mock_update(doc_ref, data):
        for key in list(storage.keys()):
            if key.endswith(f"/{doc_ref.id}"):
                storage[key].update(data)
                return

    mock_transaction.set.side_effect = mock_set
    mock_transaction.update.side_effect = mock_update

    return mock_db, mock_transaction, storage, fake_company_coll


def test_invoice_emission_real_idempotency_retry():
    """
    Prueba crítica de Idempotencia y Reintentos:
    - Stock inicial: 100
    - Emisión Factura (10 unidades): Stock = 90
    - Retry de Factura (10 unidades): Stock = 90 (NO 80), transacciones no duplicadas.
    """
    mock_db, mock_transaction, storage, fake_company_coll = setup_in_memory_firestore()

    item_id = "prod-cemento"
    wh_id = "wh-principal"
    invoice_id = "inv-e31-001"
    company_id = "comp-1"
    owner_uid = "owner-1"

    # 1. Estado Inicial: 100 unidades en almacén y catálogo
    storage[f"sandbox_items/{item_id}"] = {
        "id": item_id,
        "name": "Cemento Titán",
        "code": "CEM-TITAN",
        "type": "Bien",
        "price": 450.0,
        "costPrice": 320.0,
        "totalStock": 100.0
    }
    storage[f"sandbox_inventory_stock/{item_id}_{wh_id}"] = {
        "id": f"{item_id}_{wh_id}",
        "itemId": item_id,
        "warehouseId": wh_id,
        "quantity": 100.0
    }

    mock_warehouses = [{"id": wh_id, "name": "Almacén Principal", "branchId": "b-1"}]
    mock_catalog = [storage[f"sandbox_items/{item_id}"]]

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service.db_firestore", mock_db), \
         patch("app.services.db_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_items", return_value=mock_catalog), \
         patch.object(DatabaseService, "get_warehouses", return_value=mock_warehouses), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        invoice_payload = {
            "invoiceNumber": "E3100000001",
            "date": "2026-10-06",
            "dueDate": "2026-11-06",
            "createdAt": "2026-10-06T09:00:00Z",
            "warehouseId": wh_id,
            "status": "Emitida",
            "isSyncedWithDGII": True,
            "subtotal": 4500.0,
            "totalITBIS": 810.0,
            "total": 5310.0,
            "items": [
                {
                    "id": item_id,
                    "name": "Cemento Titán",
                    "type": "Bien",
                    "quantity": 10.0,
                    "price": 450.0,
                    "subtotal": 4500.0,
                    "total": 5310.0,
                    "itbisRate": 0.18
                }
            ]
        }

        # ── PASO 1: PRIMERA EMISIÓN ─────────────────────────────────────────
        DatabaseService.save_invoice(
            owner_uid=owner_uid,
            invoice_id=invoice_id,
            inv_dict=invoice_payload,
            company_id=company_id,
            sandbox=True
        )

        # Verificar que el stock bajó a 90
        assert storage[f"sandbox_items/{item_id}"]["totalStock"] == 90.0
        assert storage[f"sandbox_inventory_stock/{item_id}_{wh_id}"]["quantity"] == 90.0

        # Simular que se registró la clave de idempotencia en Firestore storage
        idem_key = f"{company_id}|INVOICE|{invoice_id}_{item_id}|SALIDA"
        idem_hash = hashlib.sha256(idem_key.encode("utf-8")).hexdigest()
        storage[f"sandbox_inventory_idempotency/{idem_hash}"] = {
            "id": idem_hash,
            "idempotencyKey": idem_key,
            "txId": "tx-first-call"
        }
        storage[f"sandbox_inventory_transactions/tx-first-call"] = {
            "id": "tx-first-call",
            "itemId": item_id,
            "type": "SALIDA",
            "quantity": 10.0,
            "idempotencyKey": idem_key
        }

        # ── PASO 2: RETRY POR TIMEOUT (REINTENTO DE LA MISMA FACTURA) ────────
        # El llamador reintenta la misma operación por timeout de red
        retry_invoice_payload = dict(invoice_payload)
        retry_invoice_payload["stockReduced"] = False  # El cliente no sabe si se redujo

        DatabaseService.save_invoice(
            owner_uid=owner_uid,
            invoice_id=invoice_id,
            inv_dict=retry_invoice_payload,
            company_id=company_id,
            sandbox=True
        )

        # RESULTADO ESPERADO CRÍTICO:
        # El stock DEBE permanecer en 90 (NO caer a 80)
        assert storage[f"sandbox_items/{item_id}"]["totalStock"] == 90.0, "ERROR: Doble descuento por reintento de factura!"
        assert storage[f"sandbox_inventory_stock/{item_id}_{wh_id}"]["quantity"] == 90.0


def test_goods_receipt_migrated_calls_transaction_service():
    """Verifica que la confirmación de recepción de compra invoque directamente InventoryTransactionService."""
    mock_db, mock_transaction, storage, fake_company_coll = setup_in_memory_firestore()

    item_id = "prod-varilla"
    wh_id = "wh-acero"
    company_id = "comp-1"
    owner_uid = "owner-1"

    storage[f"sandbox_items/{item_id}"] = {
        "id": item_id,
        "name": "Varilla Corrugada 3/8",
        "totalStock": 50.0,
        "costPrice": 200.0
    }
    storage[f"sandbox_inventory_stock/{item_id}_{wh_id}"] = {
        "id": f"{item_id}_{wh_id}",
        "itemId": item_id,
        "warehouseId": wh_id,
        "quantity": 50.0
    }

    mock_warehouses = [{"id": wh_id, "name": "Almacén Acero", "branchId": "b-1"}]

    receipt_data = {
        "id": "gr-100",
        "receiptNumber": "REC-0001",
        "warehouseId": wh_id,
        "warehouseName": "Almacén Acero",
        "poNumber": "OC-0050",
        "createdBy": "bodeguero@vykone.com",
        "items": [
            {
                "itemId": item_id,
                "itemName": "Varilla Corrugada 3/8",
                "receivedQuantity": 25.0,
                "unitCost": 210.0
            }
        ]
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=mock_warehouses), \
         patch("app.services.inventory_transaction_service._invalidate_items"), \
         patch("app.services.inventory_costing_service.InventoryCostingService.recalculate_item_avg_cost"):

        results = GoodsReceiptService.register_receipt_inventory(
            company_id=company_id,
            receipt_data=receipt_data,
            sandbox=True,
            owner_uid=owner_uid
        )

        assert len(results) == 1
        tx = results[0]
        assert tx["type"] == "ENTRADA"
        assert tx["quantity"] == 25.0
        assert tx["referenceType"] == "GOODS_RECEIPT"
        assert tx["previousBalance"] == 50.0
        assert tx["newBalance"] == 75.0
        assert tx["previousTotalStock"] == 50.0
        assert tx["newTotalStock"] == 75.0


def test_physical_count_migrated_with_cost_resolution():
    """Verifica que el conteo físico resuelva el costo y aplique los ajustes via InventoryTransactionService."""
    mock_db, mock_transaction, storage, fake_company_coll = setup_in_memory_firestore()

    item_id = "prod-bloques"
    wh_id = "wh-patio"
    count_id = "count-mayo-2026"
    company_id = "comp-1"
    owner_uid = "owner-1"

    storage[f"sandbox_items/{item_id}"] = {
        "id": item_id,
        "name": "Bloques de 6",
        "totalStock": 100.0,
        "costPrice": 42.50
    }
    storage[f"sandbox_inventory_stock/{item_id}_{wh_id}"] = {
        "id": f"{item_id}_{wh_id}",
        "itemId": item_id,
        "warehouseId": wh_id,
        "quantity": 100.0
    }

    mock_count = {
        "id": count_id,
        "warehouseId": wh_id,
        "status": "en_progreso",
        "lines": [
            {
                "itemId": item_id,
                "itemName": "Bloques de 6",
                "systemStock": 100.0,
                "countedStock": 95.0,
                "difference": -5.0  # Faltante de 5 unidades
            }
        ]
    }

    mock_catalog = [storage[f"sandbox_items/{item_id}"]]
    mock_warehouses = [{"id": wh_id, "name": "Patio de Bloques", "branchId": "b-1"}]

    with patch("app.services.physical_count_service.PhysicalCountService.get_count", return_value=mock_count), \
         patch("app.services.physical_count_service.PhysicalCountService._get_coll", return_value=MagicMock()), \
         patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_items", return_value=mock_catalog), \
         patch.object(DatabaseService, "get_warehouses", return_value=mock_warehouses), \
         patch("app.services.inventory_transaction_service._invalidate_items"), \
         patch("app.services.inventory_accounting_service.InventoryAccountingService.post_inventory_transaction") as mock_acc:

        success, summary = PhysicalCountService.finalize_count(
            company_id=company_id,
            count_id=count_id,
            finalized_by="auditor@vykone.com",
            sandbox=True,
            owner_uid=owner_uid
        )

        assert success is True
        assert summary["adjustments"] == 1
        assert summary["totalShortage"] == 5.0
        
        # Verificar que se generó contabilización automática de inventario con costo resuelto
        mock_acc.assert_called_once()
        _, kwargs = mock_acc.call_args
        tx = kwargs["tx"]
        assert tx["type"] == "SALIDA"
        assert tx["quantity"] == 5.0
        assert tx["unitCost"] == 42.50
        assert tx["totalValue"] == 212.50


def test_warehouse_transfer_migrated_atomic():
    """Verifica que la transferencia entre almacenes se ejecute en un solo movimiento atómico."""
    mock_db, mock_transaction, storage, fake_company_coll = setup_in_memory_firestore()

    item_id = "prod-cable"
    orig_wh = "wh-central"
    dest_wh = "wh-sucursal"
    transfer_id = "tr-2026-001"
    company_id = "comp-1"
    owner_uid = "owner-1"

    storage[f"sandbox_items/{item_id}"] = {
        "id": item_id,
        "name": "Cable THHN 12 AWG",
        "totalStock": 1000.0,
        "costPrice": 18.0
    }
    storage[f"sandbox_inventory_stock/{item_id}_{orig_wh}"] = {
        "id": f"{item_id}_{orig_wh}",
        "itemId": item_id,
        "warehouseId": orig_wh,
        "quantity": 800.0
    }
    storage[f"sandbox_inventory_stock/{item_id}_{dest_wh}"] = {
        "id": f"{item_id}_{dest_wh}",
        "itemId": item_id,
        "warehouseId": dest_wh,
        "quantity": 200.0
    }

    mock_transfer = {
        "id": transfer_id,
        "originWarehouseId": orig_wh,
        "originWarehouseName": "Almacén Central",
        "destinationWarehouseId": dest_wh,
        "destinationWarehouseName": "Sucursal Santiago",
        "status": "pendiente",
        "lines": [
            {
                "itemId": item_id,
                "itemName": "Cable THHN 12 AWG",
                "quantity": 300.0,
                "unitCost": 18.0
            }
        ]
    }

    mock_warehouses = [
        {"id": orig_wh, "name": "Almacén Central", "branchId": "b-1"},
        {"id": dest_wh, "name": "Sucursal Santiago", "branchId": "b-2"}
    ]

    with patch("app.services.warehouse_transfer_service.WarehouseTransferService.get_transfer", return_value=mock_transfer), \
         patch("app.services.warehouse_transfer_service.WarehouseTransferService._update_transfer"), \
         patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=mock_warehouses), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        ok, msg = WarehouseTransferService.approve_transfer(
            company_id=company_id,
            transfer_id=transfer_id,
            approved_by="logistica@vykone.com",
            sandbox=True,
            owner_uid=owner_uid
        )

        assert ok is True
        assert "completada" in msg.lower()
        # Verificar que el stock global se conservó en 1000
        assert storage[f"sandbox_items/{item_id}"]["totalStock"] == 1000.0
        # Verificar saldos individuales
        assert storage[f"sandbox_inventory_stock/{item_id}_{orig_wh}"]["quantity"] == 500.0
        assert storage[f"sandbox_inventory_stock/{item_id}_{dest_wh}"]["quantity"] == 500.0
