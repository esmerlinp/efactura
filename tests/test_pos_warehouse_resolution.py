import pytest
from unittest.mock import MagicMock, patch
from app.services.db_service import DatabaseService
from app.services.inventory_transaction_service import InsufficientStockError


def test_get_default_warehouse_prioritizes_default():
    mock_whs = [
        {"id": "wh-secondary", "name": "Almacen Secundario", "isDefault": False, "branchId": "default-sucursal-principal"},
        {"id": "default-almacen-principal", "name": "Almacén Principal", "isDefault": True, "branchId": "default-sucursal-principal"},
    ]
    with patch.object(DatabaseService, "get_warehouses", return_value=mock_whs):
        chosen = DatabaseService.get_default_warehouse("owner-123", company_id="comp-1", sandbox=True)
        assert chosen == "default-almacen-principal"


def test_get_default_warehouse_respects_branch():
    mock_whs = [
        {"id": "wh-branch-b-1", "name": "Almacén Sucursal B", "isDefault": True, "branchId": "branch-b"},
        {"id": "default-almacen-principal", "name": "Almacén Principal", "isDefault": True, "branchId": "default-sucursal-principal"},
    ]
    with patch.object(DatabaseService, "get_warehouses", return_value=mock_whs):
        chosen_b = DatabaseService.get_default_warehouse("owner-123", company_id="comp-1", sandbox=True, branch_id="branch-b")
        assert chosen_b == "wh-branch-b-1"

        chosen_main = DatabaseService.get_default_warehouse("owner-123", company_id="comp-1", sandbox=True, branch_id="default-sucursal-principal")
        assert chosen_main == "default-almacen-principal"


def test_get_default_warehouse_fallback_principal_keyword():
    mock_whs = [
        {"id": "wh-a", "name": "Almacen A", "isDefault": False, "branchId": "default-sucursal-principal"},
        {"id": "wh-main-custom", "name": "Depósito Central Principal", "isDefault": False, "branchId": "default-sucursal-principal"},
    ]
    with patch.object(DatabaseService, "get_warehouses", return_value=mock_whs):
        chosen = DatabaseService.get_default_warehouse("owner-123", company_id="comp-1", sandbox=True)
        assert chosen == "wh-main-custom"


def test_save_invoice_uses_default_warehouse_when_empty():
    mock_save = MagicMock()
    with patch.object(DatabaseService, "get_default_warehouse", return_value="default-almacen-principal") as mock_def, \
         patch.object(DatabaseService, "get_items", return_value=[]), \
         patch("app.services.db_service.firebase_initialized", False):
        inv_dict = {
            "invoiceNumber": "INV-001",
            "ecfType": "Factura de Consumo (E32)",
            "status": "Cobrada",
            "branchId": "default-sucursal-principal",
            "items": []
        }
        # Calling save_invoice directly
        DatabaseService.save_invoice("owner-123", "inv-1", inv_dict, company_id="comp-1", sandbox=True)
        assert inv_dict.get("warehouseId") == "default-almacen-principal"
        mock_def.assert_called_once()


def test_create_pos_sale_catches_insufficient_stock_returns_400():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    mock_shift = {"id": "shift-123", "registerId": "reg-1", "status": "OPEN"}
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "warehouseId": "default-almacen-principal"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=InsufficientStockError("Stock insuficiente en almacén 'Almacén Principal'")):
        
        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "default",
            "clientName": "Consumidor Final",
            "clientRNC": "000000000",
            "paymentMethod": "Efectivo",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "item-1", "name": "Producto", "price": 100, "quantity": 1}]
        }):
            from flask import session
            session["user"] = {"ownerUID": "owner-1", "uid": "user-1", "email": "test@vyk.com", "role": "owner"}
            session["selected_company_id"] = "comp-1"
            session["is_sandbox_mode"] = True
            
            view_fn = app.view_functions["web_pos.create_pos_sale"]
            resp, status_code = view_fn()
            assert status_code == 400
            data = resp.get_json()
            assert data["success"] is False
            assert "Stock insuficiente" in data["error"]


def test_create_pos_sale_sets_warehouse_id_on_invoice():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    mock_shift = {"id": "shift-123", "registerId": "reg-1", "status": "OPEN"}
    captured_invoice = {}

    def fake_save_invoice(owner_uid, invoice_id, inv_dict, **kwargs):
        captured_invoice.update(inv_dict)

    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "warehouseId": "default-almacen-principal"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": True}), \
         patch("app.web.pos.DatabaseService.register_cash_transaction", return_value=True), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=fake_save_invoice):
        
        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "default",
            "clientName": "Consumidor Final",
            "clientRNC": "000000000",
            "paymentMethod": "Efectivo",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "item-1", "name": "Producto", "price": 100, "quantity": 1}]
        }):
            from flask import session
            session["user"] = {"ownerUID": "owner-1", "uid": "user-1", "email": "test@vyk.com", "role": "owner"}
            session["selected_company_id"] = "comp-1"
            session["is_sandbox_mode"] = True
            
            view_fn = app.view_functions["web_pos.create_pos_sale"]
            resp = view_fn()
            assert captured_invoice.get("warehouseId") == "default-almacen-principal"


