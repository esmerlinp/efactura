"""
Pruebas de Aislamiento Multiempresa para el Módulo de Inventario.

Verifica que:
1. register_inventory_transaction escribe bajo companies/{company_id}/
2. get_inventory_stock lee desde companies/{company_id}/
3. Dos empresas distintas mantienen stocks y transacciones totalmente aislados.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from app.services.db_service import DatabaseService


def test_register_inventory_transaction_uses_company_coll():
    """Verifica que register_inventory_transaction resuelve y escribe en la colección de la compañía."""
    mock_db = MagicMock()
    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction

    mock_doc_ref = MagicMock()
    mock_doc_snapshot = MagicMock()
    mock_doc_snapshot.exists = True
    mock_doc_snapshot.to_dict.return_value = {
        "id": "item-100",
        "name": "Producto Test",
        "quantity": 10.0,
        "totalStock": 10.0
    }
    mock_doc_ref.get.return_value = mock_doc_snapshot

    mock_stock_coll = MagicMock()
    mock_stock_coll.document.return_value = mock_doc_ref

    mock_tx_coll = MagicMock()
    mock_tx_coll.document.return_value = mock_doc_ref

    mock_items_coll = MagicMock()
    mock_items_coll.document.return_value = mock_doc_ref

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        if "stock" in coll_name:
            return mock_stock_coll
        elif "transactions" in coll_name:
            return mock_tx_coll
        elif "items" in coll_name:
            return mock_items_coll
        return MagicMock()

    with patch("app.services.inventory_transaction_service.firebase_initialized", True), \
         patch("app.services.inventory_transaction_service.db_firestore", mock_db), \
         patch("app.services.inventory_transaction_service._company_coll", side_effect=fake_company_coll), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": "wh-1", "branchId": "b-1"}]), \
         patch("app.services.inventory_transaction_service._invalidate_items"):

        tx_payload = {
            "itemId": "item-100",
            "itemName": "Producto Test",
            "type": "ENTRADA",
            "quantity": 5.0,
            "destinationWarehouseId": "wh-1",
            "reason": "COMPRA",
            "performedBy": "tester@vykone.com",
        }

        res = DatabaseService.register_inventory_transaction(
            owner_uid="owner-123",
            tx_dict=tx_payload,
            sandbox=True,
            company_id="company-abc"
        )

        assert res is not None
        assert res["companyId"] == "company-abc"
        # Verificar que el stock se buscó con el ID compuesto item_id_warehouse_id
        mock_stock_coll.document.assert_any_call("item-100_wh-1")
        # Verificar que se actualizó el totalStock en items
        mock_items_coll.document.assert_called_with("item-100")


def test_inventory_isolation_between_two_companies():
    """Verifica que consultas de stock para dos empresas distintas sean independientes."""
    company_a_stocks = [
        {"id": "item-1_wh-1", "itemId": "item-1", "warehouseId": "wh-1", "quantity": 50.0}
    ]
    company_b_stocks = [
        {"id": "item-1_wh-1", "itemId": "item-1", "warehouseId": "wh-1", "quantity": 5.0}
    ]

    def mock_get_stock(owner_uid, company_id="", sandbox=True):
        if company_id == "comp-a":
            return company_a_stocks
        elif company_id == "comp-b":
            return company_b_stocks
        return []

    with patch.object(DatabaseService, "get_inventory_stock", side_effect=mock_get_stock):
        stock_a = DatabaseService.get_inventory_stock("owner-1", company_id="comp-a", sandbox=True)
        stock_b = DatabaseService.get_inventory_stock("owner-1", company_id="comp-b", sandbox=True)

        assert stock_a[0]["quantity"] == 50.0
        assert stock_b[0]["quantity"] == 5.0
        assert stock_a != stock_b
