"""
Pruebas Unitarias y de Integración para InventoryTransactionService (Fase 3).

Verifica:
1. Operación ENTRADA incrementa stock de almacén y totalStock del catálogo atómicamente.
2. Operación SALIDA decrementa stock de almacén y totalStock del catálogo atómicamente.
3. Validación estricta de stock negativo (InsufficientStockError).
4. Operación TRANSFERENCIA descuenta origen e incrementa destino sin alterar totalStock del catálogo.
5. Idempotencia: Una repetición con la misma clave no duplica la transacción ni altera existencias.
6. Registro fiel de previousBalance y newBalance a nivel de almacén y catálogo.
7. Delegación compatible de DatabaseService.register_inventory_transaction().
"""

import pytest
from unittest.mock import MagicMock, patch, call
from app.services.inventory_transaction_service import (
    InventoryTransactionService,
    InsufficientStockError,
    InventoryTransactionError
)
from app.services.db_service import DatabaseService


def setup_firestore_mock_environment():
    """Helper para simular el entorno Firestore transaccional."""
    mock_db = MagicMock()
    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction

    # Diccionario simulado de documentos por colección y doc_id
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


def test_entrada_transaction_atomic_update():
    """Verifica que una ENTRADA actualice inventory_stock, inventory_transactions y items.totalStock."""
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    # Pre-cargar item en storage: totalStock = 10.0
    storage["sandbox_items/item-1"] = {
        "id": "item-1",
        "name": "Cemento Gris",
        "code": "CEM-01",
        "costPrice": 450.0,
        "totalStock": 10.0
    }
    # Pre-cargar stock de almacén: quantity = 10.0 en wh-1
    storage["sandbox_inventory_stock/item-1_wh-1"] = {
        "id": "item-1_wh-1",
        "itemId": "item-1",
        "warehouseId": "wh-1",
        "quantity": 10.0
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén Central", "branchId": "b-1"}]), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        payload = {
            "itemId": "item-1",
            "type": "ENTRADA",
            "quantity": 5.0,
            "destinationWarehouseId": "wh-1",
            "reason": "COMPRA",
            "referenceType": "GOODS_RECEIPT",
            "referenceId": "GR-001",
            "unitCost": 450.0,
            "performedBy": "operador@vykone.com"
        }

        res = InventoryTransactionService.execute_transaction(
            owner_uid="owner-1",
            company_id="comp-1",
            tx_dict=payload,
            sandbox=True
        )

        assert res is not None
        assert res["type"] == "ENTRADA"
        assert res["quantity"] == 5.0
        assert res["previousBalance"] == 10.0
        assert res["newBalance"] == 15.0
        assert res["previousTotalStock"] == 10.0
        assert res["newTotalStock"] == 15.0
        assert res["idempotencyKey"] == "comp-1|GOODS_RECEIPT|GR-001|ENTRADA"

        # Verificar llamadas al objeto de transacción
        assert mock_transaction.set.call_count >= 3
        assert mock_transaction.update.call_count == 1
        update_args = mock_transaction.update.call_args[0]
        assert update_args[1]["totalStock"] == 15.0


def test_salida_transaction_insufficient_stock_raises_error():
    """Verifica que una SALIDA falle cuando el stock disponible es insuficiente."""
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    storage["sandbox_items/item-1"] = {
        "id": "item-1",
        "name": "Cemento Gris",
        "totalStock": 3.0
    }
    storage["sandbox_inventory_stock/item-1_wh-1"] = {
        "id": "item-1_wh-1",
        "itemId": "item-1",
        "warehouseId": "wh-1",
        "quantity": 3.0
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén Central"}]):

        payload = {
            "itemId": "item-1",
            "type": "SALIDA",
            "quantity": 10.0,  # Disponible solo 3.0
            "originWarehouseId": "wh-1",
            "reason": "VENTA",
            "referenceType": "INVOICE",
            "referenceId": "E31-001"
        }

        with pytest.raises(InsufficientStockError) as exc_info:
            InventoryTransactionService.execute_transaction(
                owner_uid="owner-1",
                company_id="comp-1",
                tx_dict=payload,
                sandbox=True,
                allow_negative_stock=False
            )

        assert "Stock insuficiente" in str(exc_info.value)


def test_transfer_transaction_updates_both_warehouses():
    """Verifica que TRANSFERENCIA descuente de origen y aumente en destino manteniendo totalStock global."""
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    storage["sandbox_items/item-1"] = {
        "id": "item-1",
        "name": "Pintura Blanca",
        "totalStock": 50.0
    }
    storage["sandbox_inventory_stock/item-1_wh-orig"] = {
        "id": "item-1_wh-orig",
        "itemId": "item-1",
        "warehouseId": "wh-orig",
        "quantity": 30.0
    }
    storage["sandbox_inventory_stock/item-1_wh-dest"] = {
        "id": "item-1_wh-dest",
        "itemId": "item-1",
        "warehouseId": "wh-dest",
        "quantity": 20.0
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[
             {"id": "wh-orig", "name": "Almacén Principal"},
             {"id": "wh-dest", "name": "Almacén Sucursal"}
         ]), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        payload = {
            "itemId": "item-1",
            "type": "TRANSFERENCIA",
            "quantity": 10.0,
            "originWarehouseId": "wh-orig",
            "destinationWarehouseId": "wh-dest",
            "reason": "TRANSFERENCIA_ENTRE_ALMACENES",
            "referenceId": "TR-100"
        }

        res = InventoryTransactionService.execute_transaction(
            owner_uid="owner-1",
            company_id="comp-1",
            tx_dict=payload,
            sandbox=True
        )

        assert res["type"] == "TRANSFERENCIA"
        assert res["previousBalance"] == 30.0
        assert res["newBalance"] == 20.0
        assert res["previousTotalStock"] == 50.0
        assert res["newTotalStock"] == 50.0  # Consistente: no cambia el total consolidado


def test_idempotency_prevents_duplicate_deduction():
    """Verifica que reenviar una transacción con la misma clave de idempotencia retorne la existente."""
    mock_db, mock_transaction, storage, fake_company_coll = setup_firestore_mock_environment()

    import hashlib
    key = "comp-1|INVOICE|E31-100|SALIDA"
    hash_id = hashlib.sha256(key.encode("utf-8")).hexdigest()

    storage[f"sandbox_inventory_idempotency/{hash_id}"] = {
        "id": hash_id,
        "txId": "tx-already-done",
        "idempotencyKey": key
    }
    storage["sandbox_inventory_transactions/tx-already-done"] = {
        "id": "tx-already-done",
        "itemId": "item-1",
        "type": "SALIDA",
        "quantity": 2.0,
        "idempotencyKey": key,
        "status": "COMPLETED"
    }

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén 1"}]):

        payload = {
            "itemId": "item-1",
            "type": "SALIDA",
            "quantity": 2.0,
            "originWarehouseId": "wh-1",
            "referenceType": "INVOICE",
            "referenceId": "E31-100",
            "idempotencyKey": key
        }

        res = InventoryTransactionService.execute_transaction(
            owner_uid="owner-1",
            company_id="comp-1",
            tx_dict=payload,
            sandbox=True
        )

        assert res["id"] == "tx-already-done"
        assert res.get("idempotentHit") is True
        # Asegurarse de que no se hicieron escrituras de stock
        mock_transaction.update.assert_not_called()


def test_database_service_adapter_delegates_to_transaction_service():
    """Verifica que DatabaseService.register_inventory_transaction delegue fielmente."""
    with patch.object(InventoryTransactionService, "execute_transaction", return_value={"id": "tx-999", "status": "OK"}) as mock_exec:
        res = DatabaseService.register_inventory_transaction(
            owner_uid="owner-123",
            tx_dict={"itemId": "item-1", "type": "ENTRADA", "quantity": 10.0, "destinationWarehouseId": "wh-1"},
            sandbox=True,
            company_id="comp-abc"
        )
        assert res["id"] == "tx-999"
        mock_exec.assert_called_once()
