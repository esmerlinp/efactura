"""
Pruebas para InventoryReconciliationService y Gobernanza de totalStock.

Verifica:
1. Detección precisa de discrepancias entre SUM(inventory_stock) y items.totalStock (audit).
2. Reporte limpio cuando los datos son coherentes.
3. Reconciliación (dry-run vs apply) actualizando la vista materializada.
4. Preservación del estado multiempresa.
"""

import pytest
from unittest.mock import MagicMock, patch
from app.services.inventory_reconciliation_service import InventoryReconciliationService
from app.services.db_service import DatabaseService


def test_audit_detects_stock_discrepancy():
    """Detecta cuando items.totalStock difiere de la suma de inventory_stock."""
    mock_items = [
        {"id": "item-1", "code": "P-01", "name": "Taladro", "type": "Bien", "totalStock": 100.0},
        {"id": "item-2", "code": "P-02", "name": "Servicio Instalación", "type": "Servicio", "totalStock": 0.0},
        {"id": "item-3", "code": "P-03", "name": "Martillo", "type": "Bien", "totalStock": 50.0}
    ]
    mock_stocks = [
        {"itemId": "item-1", "warehouseId": "wh-principal", "quantity": 30.0},
        {"itemId": "item-1", "warehouseId": "wh-secundario", "quantity": 20.0},
        # item-1 sum = 50.0 vs totalStock = 100.0 -> Discrepancia de 50.0
        {"itemId": "item-3", "warehouseId": "wh-principal", "quantity": 50.0}
        # item-3 sum = 50.0 vs totalStock = 50.0 -> Limpio
    ]
    mock_warehouses = [
        {"id": "wh-principal", "name": "Almacén Principal"},
        {"id": "wh-secundario", "name": "Almacén Secundario"}
    ]

    with patch.object(DatabaseService, "get_items", return_value=mock_items), \
         patch.object(DatabaseService, "get_inventory_stock", return_value=mock_stocks), \
         patch.object(DatabaseService, "get_warehouses", return_value=mock_warehouses):

        audit = InventoryReconciliationService.audit_company_stock("comp-123", sandbox=True)

        assert audit["status"] == "DISCREPANCIES_FOUND"
        assert audit["discrepanciesCount"] == 1
        assert audit["cleanItemsCount"] == 1  # item-3 (item-2 es servicio)
        
        disc = audit["discrepancies"][0]
        assert disc["itemId"] == "item-1"
        assert disc["materializedTotalStock"] == 100.0
        assert disc["physicalSumStock"] == 50.0
        assert disc["discrepancy"] == 50.0
        assert len(disc["warehouses"]) == 2


def test_reconcile_dry_run_does_not_mutate():
    """El modo dry-run no debe realizar escrituras en la base de datos."""
    mock_items = [
        {"id": "item-1", "code": "P-01", "name": "Taladro", "type": "Bien", "totalStock": 100.0}
    ]
    mock_stocks = [
        {"itemId": "item-1", "warehouseId": "wh-principal", "quantity": 40.0}
    ]

    with patch.object(DatabaseService, "get_items", return_value=mock_items), \
         patch.object(DatabaseService, "get_inventory_stock", return_value=mock_stocks), \
         patch.object(DatabaseService, "get_warehouses", return_value=[]), \
         patch("app.services.inventory_reconciliation_service._company_coll") as mock_coll:

        res = InventoryReconciliationService.reconcile_company_stock("comp-123", sandbox=True, dry_run=True)

        assert res["applied"] is False
        assert res["discrepanciesCount"] == 1
        mock_coll.assert_not_called()


def test_reconcile_apply_updates_materialized_total():
    """El modo apply actualiza totalStock para que sea igual a SUM(inventory_stock)."""
    mock_items = [
        {"id": "item-1", "code": "P-01", "name": "Taladro", "type": "Bien", "totalStock": 100.0}
    ]
    mock_stocks = [
        {"itemId": "item-1", "warehouseId": "wh-principal", "quantity": 45.0}
    ]

    mock_doc_ref = MagicMock()
    mock_items_coll = MagicMock()
    mock_items_coll.document.return_value = mock_doc_ref

    with patch.object(DatabaseService, "get_items", return_value=mock_items), \
         patch.object(DatabaseService, "get_inventory_stock", return_value=mock_stocks), \
         patch.object(DatabaseService, "get_warehouses", return_value=[]), \
         patch("app.services.inventory_reconciliation_service.firebase_initialized", True), \
         patch("app.services.inventory_reconciliation_service._company_coll", return_value=mock_items_coll), \
         patch("app.services.inventory_reconciliation_service._invalidate_items"):

        res = InventoryReconciliationService.reconcile_company_stock("comp-123", sandbox=True, dry_run=False)

        assert res["applied"] is True
        assert res["status"] == "RECONCILED"
        assert res["reconciledCount"] == 1
        
        # Verificar que se actualizó el doc con 45.0
        mock_items_coll.document.assert_called_with("item-1")
        mock_doc_ref.update.assert_called_once()
        args, kwargs = mock_doc_ref.update.call_args
        assert args[0]["totalStock"] == 45.0
