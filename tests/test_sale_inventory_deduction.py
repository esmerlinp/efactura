"""
Pruebas para verificar la deducción automática de inventario al emitir ventas (Web y API).
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock
from app.services.db_service import DatabaseService
from app.services.inventory_transaction_service import InventoryTransactionService


def test_save_invoice_deducts_inventory_by_catalog_id():
    """Verifica que una factura emitida con catalogId rebaja el stock del producto."""
    owner_uid = "owner-test-inv-sale"
    company_id = "comp-test-inv-sale"
    wh_id = "wh-principal"
    item_id = "prod-cemento-1"

    item_catalog = [
        {
            "id": item_id,
            "name": "Cemento Gris 50kg",
            "code": "CEM-001",
            "type": "Bien",
            "price": 450.0,
            "costPrice": 350.0,
            "totalStock": 100.0,
            "unit": "Funda"
        }
    ]

    executed_txs = []
    def mock_execute_tx(owner_uid, company_id, tx_dict, sandbox=True, **kwargs):
        executed_txs.append(tx_dict)
        return {"id": "tx-123", "status": "COMPLETED", "quantity": tx_dict["quantity"], "unitCost": 350.0, "totalCost": 3500.0}

    with patch.object(DatabaseService, "get_items", return_value=item_catalog), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": wh_id, "name": "Principal"}]), \
         patch.object(InventoryTransactionService, "execute_transaction", side_effect=mock_execute_tx), \
         patch("app.services.db_service.firebase_initialized", False):

        invoice_dict = {
            "invoiceNumber": "FAC-000001",
            "status": "Emitida",
            "isSyncedWithDGII": True,
            "warehouseId": wh_id,
            "items": [
                {
                    "catalogId": item_id,
                    "name": "Cemento Gris 50kg",
                    "price": 450.0,
                    "quantity": 10.0,
                    "subtotal": 4500.0,
                    "total": 5310.0,
                    "type": "Bien"
                }
            ]
        }

        DatabaseService.save_invoice(
            owner_uid=owner_uid,
            invoice_id="inv-test-1",
            inv_dict=invoice_dict,
            company_id=company_id,
            sandbox=True
        )

        assert len(executed_txs) == 1
        assert executed_txs[0]["itemId"] == item_id
        assert executed_txs[0]["type"] == "SALIDA"
        assert executed_txs[0]["quantity"] == 10.0
        assert executed_txs[0]["originWarehouseId"] == wh_id
        assert invoice_dict.get("stockReduced") is True


def test_save_invoice_resolves_product_by_name_and_code_fallback():
    """Verifica que si la partida no tiene catalogId explícito, se resuelva por código o nombre."""
    owner_uid = "owner-test-inv-sale"
    company_id = "comp-test-inv-sale"
    wh_id = "wh-principal"
    item_id = "prod-varilla-1"

    item_catalog = [
        {
            "id": item_id,
            "name": "Varilla Corrugada 3/8",
            "code": "VAR-38",
            "type": "Bien",
            "price": 280.0,
            "costPrice": 210.0,
            "totalStock": 500.0,
            "unit": "Unidad"
        }
    ]

    executed_txs = []
    def mock_execute_tx(owner_uid, company_id, tx_dict, sandbox=True, **kwargs):
        executed_txs.append(tx_dict)
        return {"id": "tx-124", "status": "COMPLETED", "quantity": tx_dict["quantity"], "unitCost": 210.0, "totalCost": 1050.0}

    with patch.object(DatabaseService, "get_items", return_value=item_catalog), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": wh_id, "name": "Principal"}]), \
         patch.object(InventoryTransactionService, "execute_transaction", side_effect=mock_execute_tx), \
         patch("app.services.db_service.firebase_initialized", False):

        # Partida con ID generado al azar o UUID, pero con nombre exacto
        invoice_dict = {
            "invoiceNumber": "FAC-000002",
            "status": "Pendiente DGII",
            "warehouseId": wh_id,
            "items": [
                {
                    "id": str(uuid.uuid4()),  # UUID generado
                    "name": "Varilla Corrugada 3/8",
                    "price": 280.0,
                    "quantity": 5.0,
                    "subtotal": 1400.0,
                    "total": 1652.0,
                    "type": "Bien"
                }
            ]
        }

        DatabaseService.save_invoice(
            owner_uid=owner_uid,
            invoice_id="inv-test-2",
            inv_dict=invoice_dict,
            company_id=company_id,
            sandbox=True
        )

        assert len(executed_txs) == 1
        assert executed_txs[0]["itemId"] == item_id
        assert executed_txs[0]["type"] == "SALIDA"
        assert executed_txs[0]["quantity"] == 5.0
        assert invoice_dict.get("stockReduced") is True


def test_save_invoice_services_do_not_deduct_inventory():
    """Verifica que los servicios nunca generen transacciones de salida de inventario."""
    owner_uid = "owner-test-inv-sale"
    company_id = "comp-test-inv-sale"
    wh_id = "wh-principal"
    item_id = "srv-consultoria-1"

    item_catalog = [
        {
            "id": item_id,
            "name": "Servicio de Consultoría Fiscal",
            "code": "SRV-001",
            "type": "Servicio",
            "price": 5000.0,
            "costPrice": 0.0,
            "unit": "Hora"
        }
    ]

    executed_txs = []
    with patch.object(DatabaseService, "get_items", return_value=item_catalog), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": wh_id, "name": "Principal"}]), \
         patch.object(InventoryTransactionService, "execute_transaction", side_effect=lambda *a, **k: executed_txs.append(k)), \
         patch("app.services.db_service.firebase_initialized", False):

        invoice_dict = {
            "invoiceNumber": "FAC-000003",
            "status": "Cobrada",
            "isSyncedWithDGII": True,
            "warehouseId": wh_id,
            "items": [
                {
                    "catalogId": item_id,
                    "name": "Servicio de Consultoría Fiscal",
                    "price": 5000.0,
                    "quantity": 2.0,
                    "subtotal": 10000.0,
                    "total": 11800.0,
                    "type": "Servicio"
                }
            ]
        }

        DatabaseService.save_invoice(
            owner_uid=owner_uid,
            invoice_id="inv-test-3",
            inv_dict=invoice_dict,
            company_id=company_id,
            sandbox=True
        )

        assert len(executed_txs) == 0


def test_save_invoice_draft_does_not_deduct_inventory():
    """Verifica que un borrador de factura no rebaje inventario."""
    owner_uid = "owner-test-inv-sale"
    company_id = "comp-test-inv-sale"
    wh_id = "wh-principal"
    item_id = "prod-pintura-1"

    item_catalog = [
        {
            "id": item_id,
            "name": "Pintura Blanca Cubeta",
            "code": "PIN-001",
            "type": "Bien",
            "price": 1800.0,
            "costPrice": 1200.0,
            "totalStock": 20.0
        }
    ]

    executed_txs = []
    with patch.object(DatabaseService, "get_items", return_value=item_catalog), \
         patch.object(DatabaseService, "get_warehouses", return_value=[{"id": wh_id, "name": "Principal"}]), \
         patch.object(InventoryTransactionService, "execute_transaction", side_effect=lambda *a, **k: executed_txs.append(k)), \
         patch("app.services.db_service.firebase_initialized", False):

        invoice_dict = {
            "invoiceNumber": "FAC-000004",
            "status": "Borrador",
            "warehouseId": wh_id,
            "items": [
                {
                    "catalogId": item_id,
                    "name": "Pintura Blanca Cubeta",
                    "price": 1800.0,
                    "quantity": 3.0,
                    "subtotal": 5400.0,
                    "total": 6372.0,
                    "type": "Bien"
                }
            ]
        }

        DatabaseService.save_invoice(
            owner_uid=owner_uid,
            invoice_id="inv-test-4",
            inv_dict=invoice_dict,
            company_id=company_id,
            sandbox=True
        )

        assert len(executed_txs) == 0
        assert invoice_dict.get("stockReduced") is not True
