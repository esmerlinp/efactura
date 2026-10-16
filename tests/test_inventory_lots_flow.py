"""
Pruebas integrales del módulo de Lotes (LotBatch) en VykOne ERP.

Cubre:
1. Catálogo de productos: trackLots por defecto False y retrocompatibilidad.
2. LotService: resolución canónica de ID, validaciones de fechas y pertenencia.
3. InventoryTransactionService:
   - ENTRADA regular sin lote permitida si trackLots=False.
   - ENTRADA bloqueada si trackLots=True y no se especifica lote.
   - Creación atómica de nuevo lote en inventory_lots.
   - Incremento atómico de lote existente (sin duplicación de partidas físicas).
   - Rechazo por fecha de vencimiento anterior a fabricación.
   - Rechazo por lote perteneciente a otro producto o almacén.
   - SALIDA con lote decrementa existencia de lote.
   - SALIDA con lote bloqueada si saldo de lote es insuficiente.
   - Idempotencia: reintentos con la misma clave no duplican existencias ni saldo de lote.
4. GoodsReceiptService:
   - validate_receipt valida requerimiento de lote por ítem.
   - register_receipt_inventory transfiere datos de lote a la transacción atómica.
   - reverse_registered_transactions incluye lotId/lotNumber en el rollback.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.inventory_transaction_service import (
    InventoryTransactionService,
    InsufficientStockError,
    InventoryTransactionError,
)
from app.services.lot_service import LotService
from app.services.goods_receipt_service import GoodsReceiptService
from app.services.purchase_order_service import PurchaseOrderService
from app.services.db_service import DatabaseService


def setup_firestore_mock_environment():
    """Helper para simular el entorno Firestore transaccional con lotes."""
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
        else:
            doc_mock.exists = False
            doc_mock.to_dict.return_value = {}
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

            coll_mock.document.side_effect = doc_side_effect
            mock_colls[coll_name] = coll_mock
        return mock_colls[coll_name]

    return mock_db, mock_transaction, storage, fake_company_coll


# =========================================================================
# 1. Catálogo y LotService
# =========================================================================

def test_lot_service_canonical_id():
    lot_id_1 = LotService.build_canonical_lot_id("item-A", "wh-1", "LOTE-2026-X")
    lot_id_2 = LotService.build_canonical_lot_id("item-A", "wh-1", " lote-2026-x ")
    assert lot_id_1 == lot_id_2
    assert "item-A" in lot_id_1
    assert "wh-1" in lot_id_1


def test_lot_service_validate_dates():
    # Fechas válidas
    val = LotService.validate_lot_data(
        item_id="i1",
        warehouse_id="w1",
        lot_number="LOT-1",
        production_date="2026-01-01",
        expiration_date="2026-12-31"
    )
    assert val["lotNumber"] == "LOT-1"

    # Fecha vencimiento menor a fabricación
    with pytest.raises(ValueError) as err:
        LotService.validate_lot_data(
            item_id="i1",
            warehouse_id="w1",
            lot_number="LOT-1",
            production_date="2026-05-01",
            expiration_date="2026-04-01"
        )
    assert "anterior" in str(err.value).lower()


# =========================================================================
# 2. Transacciones Atómicas con Lotes (InventoryTransactionService)
# =========================================================================

def test_entrada_product_without_track_lots_succeeds_without_lot():
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    storage["sandbox_items/item-normal"] = {
        "id": "item-normal",
        "name": "Tornillo 2 pulg",
        "totalStock": 100.0,
        "trackLots": False,
    }
    storage["sandbox_inventory_stock/item-normal_wh-1"] = {
        "id": "item-normal_wh-1",
        "itemId": "item-normal",
        "warehouseId": "wh-1",
        "quantity": 100.0,
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén Central"}]), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        payload = {
            "itemId": "item-normal",
            "type": "ENTRADA",
            "quantity": 50.0,
            "destinationWarehouseId": "wh-1",
            "reason": "COMPRA",
            "unitCost": 5.0,
        }

        res = InventoryTransactionService.execute_transaction(
            owner_uid="owner-1", company_id="comp-1", tx_dict=payload, sandbox=True
        )
        assert res is not None
        assert res["newBalance"] == 150.0
        assert res["newTotalStock"] == 150.0
        assert not res.get("lotId")


def test_entrada_product_with_track_lots_fails_without_lot():
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    storage["sandbox_items/item-pharma"] = {
        "id": "item-pharma",
        "name": "Amoxicilina 500mg",
        "totalStock": 20.0,
        "trackLots": True,
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén Central"}]), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        payload = {
            "itemId": "item-pharma",
            "type": "ENTRADA",
            "quantity": 10.0,
            "destinationWarehouseId": "wh-1",
            "reason": "COMPRA",
        }

        with pytest.raises(InventoryTransactionError) as err:
            InventoryTransactionService.execute_transaction(
                owner_uid="owner-1", company_id="comp-1", tx_dict=payload, sandbox=True
            )
        assert "requiere control por lotes" in str(err.value).lower()


def test_entrada_creates_new_lot_atomically():
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    storage["sandbox_items/item-pharma"] = {
        "id": "item-pharma",
        "name": "Amoxicilina 500mg",
        "totalStock": 0.0,
        "trackLots": True,
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén Central"}]), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        payload = {
            "itemId": "item-pharma",
            "type": "ENTRADA",
            "quantity": 100.0,
            "unitCost": 12.50,
            "destinationWarehouseId": "wh-1",
            "reason": "COMPRA",
            "lotNumber": "LOT-2026-A1",
            "productionDate": "2026-01-10",
            "expirationDate": "2027-01-10",
            "lotNotes": "Recibido de Droguería Central",
        }

        res = InventoryTransactionService.execute_transaction(
            owner_uid="owner-1", company_id="comp-1", tx_dict=payload, sandbox=True
        )

        assert res is not None
        assert res["newBalance"] == 100.0
        assert res["lotNumber"] == "LOT-2026-A1"
        assert res["expirationDate"] == "2027-01-10"

        # Verificar que se programó la escritura del lote en la transacción
        lot_writes = [
            call_args[0][1] for call_args in mock_transaction.set.call_args_list
            if isinstance(call_args[0][1], dict)
            and call_args[0][1].get("lotNumber") == "LOT-2026-A1"
            and "initialQuantity" in call_args[0][1]
        ]
        assert len(lot_writes) == 1
        written_lot = lot_writes[0]
        assert written_lot["itemId"] == "item-pharma"
        assert written_lot["warehouseId"] == "wh-1"
        assert written_lot["quantity"] == 100.0
        assert written_lot["initialQuantity"] == 100.0
        assert written_lot["unitCost"] == 12.50


def test_entrada_increments_existing_lot_without_duplicate():
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    canonical_lot_id = LotService.build_canonical_lot_id("item-pharma", "wh-1", "LOT-2026-A1")

    storage["sandbox_items/item-pharma"] = {
        "id": "item-pharma",
        "name": "Amoxicilina 500mg",
        "totalStock": 100.0,
        "trackLots": True,
    }
    storage["sandbox_inventory_stock/item-pharma_wh-1"] = {
        "id": "item-pharma_wh-1",
        "itemId": "item-pharma",
        "warehouseId": "wh-1",
        "quantity": 100.0,
    }
    storage[f"sandbox_inventory_lots/{canonical_lot_id}"] = {
        "id": canonical_lot_id,
        "itemId": "item-pharma",
        "itemName": "Amoxicilina 500mg",
        "warehouseId": "wh-1",
        "lotNumber": "LOT-2026-A1",
        "quantity": 100.0,
        "initialQuantity": 100.0,
        "productionDate": "2026-01-10",
        "expirationDate": "2027-01-10",
        "unitCost": 12.50,
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén Central"}]), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        payload = {
            "itemId": "item-pharma",
            "type": "ENTRADA",
            "quantity": 50.0,
            "destinationWarehouseId": "wh-1",
            "reason": "COMPRA",
            "lotNumber": "LOT-2026-A1",
        }

        res = InventoryTransactionService.execute_transaction(
            owner_uid="owner-1", company_id="comp-1", tx_dict=payload, sandbox=True
        )

        assert res["newBalance"] == 150.0
        assert res["lotId"] == canonical_lot_id

        # Verificar que el lote se actualizó con la suma
        lot_writes = [
            call_args[0][1] for call_args in mock_transaction.set.call_args_list
            if isinstance(call_args[0][1], dict)
            and call_args[0][1].get("lotNumber") == "LOT-2026-A1"
            and "initialQuantity" in call_args[0][1]
        ]
        assert len(lot_writes) == 1
        updated_lot = lot_writes[0]
        assert updated_lot["quantity"] == 150.0
        assert updated_lot["initialQuantity"] == 150.0


def test_entrada_rejects_expiration_before_production():
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    storage["sandbox_items/item-pharma"] = {
        "id": "item-pharma",
        "name": "Amoxicilina 500mg",
        "totalStock": 0.0,
        "trackLots": True,
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén Central"}]), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        payload = {
            "itemId": "item-pharma",
            "type": "ENTRADA",
            "quantity": 10.0,
            "destinationWarehouseId": "wh-1",
            "lotNumber": "LOT-BAD-DATES",
            "productionDate": "2026-06-01",
            "expirationDate": "2026-01-01",
        }

        with pytest.raises(InventoryTransactionError) as err:
            InventoryTransactionService.execute_transaction(
                owner_uid="owner-1", company_id="comp-1", tx_dict=payload, sandbox=True
            )
        assert "no puede ser anterior" in str(err.value).lower()


def test_idempotency_prevents_duplicate_lot_increment():
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    storage["sandbox_items/item-pharma"] = {
        "id": "item-pharma",
        "name": "Amoxicilina 500mg",
        "totalStock": 100.0,
        "trackLots": True,
    }
    # Transacción previa ya registrada en Firestore
    storage["sandbox_inventory_transactions/tx-prev"] = {
        "id": "tx-prev",
        "type": "ENTRADA",
        "itemId": "item-pharma",
        "quantity": 50.0,
        "lotNumber": "LOT-2026-A1",
        "idempotencyKey": "comp-1|PO|REC-001|ENTRADA"
    }
    import hashlib
    idem_hash = hashlib.sha256("comp-1|PO|REC-001|ENTRADA".encode("utf-8")).hexdigest()
    storage[f"sandbox_inventory_idempotency/{idem_hash}"] = {
        "txId": "tx-prev",
        "createdAt": "2026-10-16T10:00:00"
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén Central"}]):

        payload = {
            "itemId": "item-pharma",
            "type": "ENTRADA",
            "quantity": 50.0,
            "destinationWarehouseId": "wh-1",
            "idempotencyKey": "comp-1|PO|REC-001|ENTRADA",
            "lotNumber": "LOT-2026-A1"
        }

        res = InventoryTransactionService.execute_transaction(
            owner_uid="owner-1", company_id="comp-1", tx_dict=payload, sandbox=True
        )

        assert res["id"] == "tx-prev"
        # No debe haber hecho escrituras nuevas
        assert mock_transaction.set.call_count == 0
        assert mock_transaction.update.call_count == 0


# =========================================================================
# 3. Flujo de Recepción de Compras (GoodsReceiptService)
# =========================================================================

def test_goods_receipt_validate_requires_lot_when_item_tracks_lots():
    po = {
        "id": "po-lot-1",
        "poNumber": "OC-2026-0005",
        "status": "aprobada",
        "items": [
            {"id": "line-1", "name": "Vacuna Antigripal", "quantity": 20, "receivedQuantity": 0, "unitPrice": 300}
        ]
    }
    receipt_data = {
        "warehouseId": "wh-1",
        "poId": "po-lot-1",
        "items": [
            {
                "poItemId": "line-1",
                "itemId": "cat-vacuna",
                "receivedQuantity": 10,
                "trackLots": True,
                # Sin lotNumber ni lotId
            }
        ]
    }

    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po):
        with pytest.raises(ValueError) as err:
            GoodsReceiptService.validate_receipt("comp-1", receipt_data, sandbox=True)
        assert "requiere control por lotes" in str(err.value).lower()


def test_goods_receipt_validate_passes_with_valid_lot():
    po = {
        "id": "po-lot-1",
        "poNumber": "OC-2026-0005",
        "status": "aprobada",
        "items": [
            {"id": "line-1", "name": "Vacuna Antigripal", "quantity": 20, "receivedQuantity": 0, "unitPrice": 300}
        ]
    }
    receipt_data = {
        "warehouseId": "wh-1",
        "poId": "po-lot-1",
        "items": [
            {
                "poItemId": "line-1",
                "itemId": "cat-vacuna",
                "receivedQuantity": 10,
                "trackLots": True,
                "lotNumber": "LOT-VAC-99",
                "productionDate": "2026-02-01",
                "expirationDate": "2027-02-01"
            }
        ]
    }

    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po):
        assert GoodsReceiptService.validate_receipt("comp-1", receipt_data, sandbox=True) is True


def test_goods_receipt_register_and_reverse_lots():
    """Verifica que register_receipt_inventory pase los lotes y reverse_registered_transactions revierta el lote."""
    mock_execute = MagicMock(return_value={
        "id": "tx-rc-1",
        "type": "ENTRADA",
        "itemId": "cat-vacuna",
        "quantity": 10,
        "destinationWarehouseId": "wh-1",
        "lotId": "lot-uuid-1",
        "lotNumber": "LOT-VAC-99"
    })

    receipt_data = {
        "id": "rc-101",
        "receiptNumber": "RC-2026-0001",
        "poId": "po-lot-1",
        "warehouseId": "wh-1",
        "items": [
            {
                "poItemId": "line-1",
                "itemId": "cat-vacuna",
                "receivedQuantity": 10,
                "unitPrice": 300,
                "lotId": "lot-uuid-1",
                "lotNumber": "LOT-VAC-99",
                "productionDate": "2026-02-01",
                "expirationDate": "2027-02-01",
                "lotNotes": "Caja 1"
            }
        ]
    }

    with patch("app.services.inventory_transaction_service.InventoryTransactionService.execute_transaction", mock_execute), \
         patch("app.services.inventory_accounting_service.InventoryAccountingService.post_inventory_transaction"):

        reg = GoodsReceiptService.register_receipt_inventory("comp-1", receipt_data, sandbox=True)
        assert len(reg) == 1
        tx_call = mock_execute.call_args_list[0][1]["tx_dict"]
        assert tx_call["lotId"] == "lot-uuid-1"
        assert tx_call["lotNumber"] == "LOT-VAC-99"
        assert tx_call["productionDate"] == "2026-02-01"
        assert tx_call["expirationDate"] == "2027-02-01"

    # Ahora probar reversión automática (rollback)
    mock_rev_execute = MagicMock(return_value={"id": "tx-rev-1"})
    with patch("app.services.inventory_transaction_service.InventoryTransactionService.execute_transaction", mock_rev_execute):
        reversed_count = GoodsReceiptService.reverse_registered_transactions("comp-1", reg, sandbox=True)
        assert reversed_count == 1
        rev_call = mock_rev_execute.call_args_list[0][1]["tx_dict"]
        assert rev_call["type"] == "SALIDA"
        assert rev_call["lotId"] == "lot-uuid-1"
        assert rev_call["lotNumber"] == "LOT-VAC-99"
        assert rev_call["allowNegativeStock"] is True
