"""Pruebas de integración para las rutas Web y API REST de Kardex."""

import pytest
from unittest.mock import patch
import io

MOCK_USER_PROFILE = {
    "uid": "test-uid",
    "email": "admin@test.com",
    "name": "Admin",
    "role": "owner",
    "ownerUID": "test-owner",
    "status": "active",
    "permissions": {"canManageInventory": True, "canInvoice": True}
}

MOCK_COMPANY = {
    "companyRNC": "132-10912-2",
    "companyName": "Empresa Test SRL",
    "configured": True,
    "planId": "plan-pro",
    "country": "DO",
    "modules": {"inventario": {"enabled": True}, "e_cf": {"enabled": True}},
}


MOCK_DB_COMPANY = {
    "id": "comp-test-01",
    "owner_uid": "test-owner",
    "name": "Empresa Test SRL",
    "companyRNC": "132-10912-2",
    "plan_id": "plan-pro",
    "configured": True,
    "country": "DO",
    "modules": {"inventario": {"enabled": True}, "e_cf": {"enabled": True}},
}

MOCK_COMPANY_CTX = {
    "company_id": "comp-test-01",
    "role": "owner",
    "permissions": {"canManageInventory": True, "canInvoice": True},
}


MOCK_PLAN = {
    "id": "plan-pro",
    "name": "Plan Pro",
    "modules": {"inventario": {"enabled": True}, "e_cf": {"enabled": True}, "contabilidad": {"enabled": True}},
}

MOCK_MEMBERSHIP = {
    "userId": "test-uid",
    "companyId": "comp-test-01",
    "status": "active",
    "role": "owner",
}


def mock_login(client, owner_uid="test-owner"):
    with client.session_transaction() as sess:
        sess["user"] = {
            "uid": "test-uid",
            "ownerUID": owner_uid,
            "role": "owner",
            "email": "admin@test.com",
            "name": "Admin",
            "permissions": {"canManageInventory": True, "canInvoice": True},
        }
        sess["selected_company_id"] = "comp-test-01"
        sess["selected_owner_uid"] = owner_uid
        sess["company_country"] = "DO"
        sess["company_modules"] = {
            "inventario": {"enabled": True},
            "e_cf": {"enabled": True},
            "contabilidad": {"enabled": True},
        }
        sess["is_sandbox_mode"] = True


def test_kardex_web_view_summary(client):
    """Prueba GET /inventory/kardex sin artículo (vista resumen consolidado)."""
    mock_login(client)
    mock_warehouses = [{"id": "wh-1", "name": "Almacén Central"}]
    mock_items = [{"id": "item-1", "name": "Taladro", "code": "ART-01", "type": "Bien", "totalStock": 10.0, "costPrice": 100.0}]

    with patch("app.services.db_service.DatabaseService.get_user_profile", return_value=MOCK_USER_PROFILE), \
         patch("app.services.db_service.DatabaseService.get_associated_companies", return_value=[{"ownerUID": "test-owner", "companyName": "Empresa Test SRL", "role": "owner"}]), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=MOCK_DB_COMPANY), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value=MOCK_COMPANY_CTX), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value=MOCK_MEMBERSHIP), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value=MOCK_PLAN), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_warehouses", return_value=mock_warehouses), \
         patch("app.services.db_service.DatabaseService.get_items", return_value=mock_items), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=MOCK_COMPANY), \
         patch("app.services.kardex_service.KardexService.get_kardex_summary", return_value={
             "companyId": "comp-test-01", "warehouseId": None, "warehouseName": "Todos los Almacenes",
             "dateFrom": None, "dateTo": None, "totalItems": 1, "discrepanciesCount": 0, "overallStatus": "OK",
             "totals": {"initialValue": 1000.0, "inValue": 0.0, "outValue": 0.0, "finalValue": 1000.0},
             "items": [{
                 "itemId": "item-1", "itemCode": "ART-01", "itemName": "Taladro", "unit": "Unidad",
                 "initialQty": 10.0, "initialValue": 1000.0, "periodInQty": 0.0, "periodInValue": 0.0,
                 "periodOutQty": 0.0, "periodOutValue": 0.0, "finalQty": 10.0, "finalValue": 1000.0,
                 "finalUnitCost": 100.0, "stockQty": 10.0, "ledgerValue": 1000.0, "qtyDifference": 0.0,
                 "valueDifference": 0.0, "reconciliationStatus": "OK"
             }]
         }):
        resp = client.get("/inventory/kardex")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Kardex Valorizado Continuo" in html
        assert "Taladro" in html
        assert "ART-01" in html
        assert "RD$ 1,000.00" in html


def test_kardex_web_view_item_detail(client):
    """Prueba GET /inventory/kardex?item_id=item-1 (vista detallada de un artículo)."""
    mock_login(client)
    mock_warehouses = [{"id": "wh-1", "name": "Almacén Central"}]
    mock_items = [{"id": "item-1", "name": "Taladro", "code": "ART-01", "type": "Bien", "totalStock": 10.0, "costPrice": 100.0}]

    mock_kardex_item = {
        "companyId": "comp-test-01", "itemId": "item-1",
        "item": {"id": "item-1", "name": "Taladro", "code": "ART-01", "totalStock": 10.0},
        "warehouseId": "wh-1", "warehouseName": "Almacén Central",
        "dateFrom": "2026-08-01", "dateTo": "2026-08-31",
        "initialBalance": {"quantity": 0.0, "totalValue": 0.0, "unitCost": 0.0, "date": "2026-08-01"},
        "movements": [{
            "transactionId": "tx-1", "date": "2026-08-05T10:00:00Z", "type": "ENTRADA", "reason": "COMPRA",
            "documentNumber": "OC-100", "referenceId": "OC-100", "warehouseId": "wh-1", "warehouseName": "Almacén Central",
            "inQty": 10.0, "inUnitCost": 100.0, "inTotalValue": 1000.0, "outQty": 0.0, "outUnitCost": 0.0, "outTotalValue": 0.0,
            "balanceQty": 10.0, "balanceUnitCost": 100.0, "balanceTotalValue": 1000.0, "costLayers": [],
            "performedBy": "Admin", "notes": "Compra inicial"
        }],
        "finalBalance": {"quantity": 10.0, "totalValue": 1000.0, "unitCost": 100.0},
        "periodTotals": {"inQuantity": 10.0, "inTotalValue": 1000.0, "outQuantity": 0.0, "outTotalValue": 0.0},
        "reconciliation": {
            "stockQty": 10.0, "kardexQty": 10.0, "qtyDifference": 0.0, "ledgerValue": 1000.0,
            "kardexValue": 1000.0, "valueDifference": 0.0, "catalogTotalStock": 10.0,
            "catalogDifference": 0.0, "status": "OK", "notes": "Saldos conciliados correctamente."
        }
    }

    with patch("app.services.db_service.DatabaseService.get_user_profile", return_value=MOCK_USER_PROFILE), \
         patch("app.services.db_service.DatabaseService.get_associated_companies", return_value=[{"ownerUID": "test-owner", "companyName": "Empresa Test SRL", "role": "owner"}]), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=MOCK_DB_COMPANY), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value=MOCK_COMPANY_CTX), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value=MOCK_MEMBERSHIP), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value=MOCK_PLAN), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_warehouses", return_value=mock_warehouses), \
         patch("app.services.db_service.DatabaseService.get_items", return_value=mock_items), \
         patch("app.services.kardex_service.KardexService.get_kardex_summary", return_value=mock_kardex_item):
        resp = client.get("/inventory/kardex?item_id=item-1&warehouse_id=wh-1&date_from=2026-08-01&date_to=2026-08-31")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "Taladro" in html
        assert "DATOS DEL MOVIMIENTO" in html
        assert "ENTRADAS" in html
        assert "SALIDAS (COGS FIFO)" in html
        assert "SALDO ACUMULADO" in html
        assert "OC-100" in html


def test_kardex_web_export_excel(client):
    """Prueba GET /inventory/kardex/export/excel."""
    mock_login(client)
    fake_excel = io.BytesIO(b"fake excel content")

    with patch("app.services.db_service.DatabaseService.get_user_profile", return_value=MOCK_USER_PROFILE), \
         patch("app.services.db_service.DatabaseService.get_associated_companies", return_value=[{"ownerUID": "test-owner", "companyName": "Empresa Test SRL", "role": "owner"}]), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=MOCK_DB_COMPANY), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value=MOCK_COMPANY_CTX), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value=MOCK_MEMBERSHIP), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value=MOCK_PLAN), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.kardex_service.KardexService.export_kardex_excel", return_value=fake_excel):
        resp = client.get("/inventory/kardex/export/excel?item_id=item-1")
        assert resp.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers.get("Content-Type", "")
        assert "attachment" in resp.headers.get("Content-Disposition", "")


def test_kardex_web_export_pdf(client):
    """Prueba GET /inventory/kardex/export/pdf."""
    mock_login(client)
    fake_pdf = b"%PDF-1.4 mock pdf bytes"

    with patch("app.services.db_service.DatabaseService.get_user_profile", return_value=MOCK_USER_PROFILE), \
         patch("app.services.db_service.DatabaseService.get_associated_companies", return_value=[{"ownerUID": "test-owner", "companyName": "Empresa Test SRL", "role": "owner"}]), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=MOCK_DB_COMPANY), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value=MOCK_COMPANY_CTX), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value=MOCK_MEMBERSHIP), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value=MOCK_PLAN), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.kardex_service.KardexService.export_kardex_pdf", return_value=fake_pdf):
        resp = client.get("/inventory/kardex/export/pdf?item_id=item-1")
        assert resp.status_code == 200
        assert "application/pdf" in resp.headers.get("Content-Type", "")


def test_kardex_api_endpoints(client):
    """Prueba los endpoints REST de API v1 para Kardex con autenticación por API Key."""
    mock_company_api = {
        "id": "comp-api-01",
        "ownerUID": "test-owner",
        "companyName": "Empresa API Test",
        "modules": {"inventario": {"enabled": True}},
    }

    mock_summary_res = {
        "companyId": "comp-api-01",
        "totalItems": 1,
        "items": []
    }

    mock_item_res = {
        "companyId": "comp-api-01",
        "itemId": "item-01",
        "finalBalance": {"quantity": 10.0, "totalValue": 500.0, "unitCost": 50.0}
    }

    headers = {"X-API-Key": "valid-test-key"}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=mock_company_api), \
         patch("app.services.kardex_service.KardexService.get_kardex_summary", side_effect=lambda **kwargs: mock_item_res if kwargs.get("item_id") else mock_summary_res):
        
        # 1. Sin itemId -> Error 400
        resp_err = client.get("/api/v1/inventory/kardex", headers=headers)
        assert resp_err.status_code == 400

        # 2. Con itemId -> 200 OK
        resp_item = client.get("/api/v1/inventory/kardex?itemId=item-01", headers=headers)
        assert resp_item.status_code == 200
        data = resp_item.get_json()
        assert data["success"] is True
        assert data["kardex"]["itemId"] == "item-01"

        # 3. Resumen consolidado -> 200 OK
        resp_sum = client.get("/api/v1/inventory/kardex/summary", headers=headers)
        assert resp_sum.status_code == 200
        data_sum = resp_sum.get_json()
        assert data_sum["success"] is True
        assert data_sum["summary"]["companyId"] == "comp-api-01"
