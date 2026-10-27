import pytest
from flask import session
from unittest.mock import patch, MagicMock
from contextlib import contextmanager
from app import create_app
from app.utils.decorators import check_permission
from app.web.invoices import ALL_PERMISSION_KEYS, ROLES_PRESETS, PERMISSION_GROUPS


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _setup_session(user_perms=None, role="collaborator", uid="user_approver_1", email="approver@example.com", name="Aprobador"):
    perms = user_perms if user_perms is not None else {}
    return {
        "uid": uid,
        "email": email,
        "displayName": name,
        "name": name,
        "ownerUID": "owner_p123",
        "company_id": "comp_p123",
        "role": role,
        "permissions": perms,
    }


def _setup_company_modules():
    return {
        "cxp_compras": {"enabled": True},
        "gastos": {"enabled": True},
        "e_cf": {"enabled": True},
    }


@contextmanager
def _mock_env(user_data):
    company_doc = {
        "id": "comp_p123",
        "status": "Activo",
        "planId": "plan_test",
        "plan_id": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_p123",
        "country": "DO",
        "configured": True,
        "pos_enabled": False,
        "production_enabled": True,
        "sandbox_enabled": True,
        "companyName": "Compras Test SRL",
        "companyRNC": "131880681",
    }
    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': user_data.get('role', 'collaborator'), 'permissions': user_data.get('permissions', {})}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'cxp_compras': {'enabled': True}, 'gastos': {'enabled': True}, 'e_cf': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_p123', 'owner_uid': 'owner_p123', 'company_name': 'Compras Test SRL', 'rnc': '131880681', 'role': user_data.get('role', 'collaborator'), 'permissions': user_data.get('permissions', {}), 'company': company_doc}):
        yield


def test_po_approval_permission_resolution(app):
    """Test resolution of canApprovePurchaseOrders and canSelfApprovePurchaseOrders."""
    with app.test_request_context("/"):
        # Owner always has both permissions
        session["user"] = _setup_session({}, role="owner")
        assert check_permission("canApprovePurchaseOrders") is True
        assert check_permission("canSelfApprovePurchaseOrders") is True

        # Non-owner with explicit True
        session["user"] = _setup_session({"canApprovePurchaseOrders": True, "canSelfApprovePurchaseOrders": False})
        assert check_permission("canApprovePurchaseOrders") is True
        assert check_permission("canSelfApprovePurchaseOrders") is False

        # Non-owner with both True
        session["user"] = _setup_session({"canApprovePurchaseOrders": True, "canSelfApprovePurchaseOrders": True})
        assert check_permission("canApprovePurchaseOrders") is True
        assert check_permission("canSelfApprovePurchaseOrders") is True

        # Non-owner with absent keys defaults to False (secure by default)
        session["user"] = _setup_session({"canManagePurchaseOrders": True})
        assert check_permission("canApprovePurchaseOrders") is False
        assert check_permission("canSelfApprovePurchaseOrders") is False


def test_po_approval_presets_and_groups():
    """Verify presence and configuration in ALL_PERMISSION_KEYS, PERMISSION_GROUPS and ROLES_PRESETS."""
    assert "canApprovePurchaseOrders" in ALL_PERMISSION_KEYS
    assert "canSelfApprovePurchaseOrders" in ALL_PERMISSION_KEYS

    compras_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Compras y Proveedores"), None)
    assert compras_group is not None
    assert "canApprovePurchaseOrders" in compras_group.get("perms", [])
    assert "canSelfApprovePurchaseOrders" in compras_group.get("perms", [])
    assert "canApprovePurchaseOrders" in compras_group.get("labels", {})
    assert "canSelfApprovePurchaseOrders" in compras_group.get("labels", {})

    # Administrator has canApprovePurchaseOrders
    assert ROLES_PRESETS["administrador"]["canApprovePurchaseOrders"] is True
    # Contador can approve orders of others but not self-approve
    assert ROLES_PRESETS["contador"]["canApprovePurchaseOrders"] is True
    assert ROLES_PRESETS["contador"]["canSelfApprovePurchaseOrders"] is False
    # Vendedor and Consulta cannot approve
    assert ROLES_PRESETS["vendedor"]["canApprovePurchaseOrders"] is False
    assert ROLES_PRESETS["consulta"]["canApprovePurchaseOrders"] is False


def test_approve_purchase_order_denied_without_permission(app, client):
    """User without canApprovePurchaseOrders gets 403."""
    user_data = _setup_session({"canManagePurchaseOrders": True, "canApprovePurchaseOrders": False})
    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["company_modules"] = _setup_company_modules()
        sess["selected_company_id"] = "comp_p123"
        sess["selected_owner_uid"] = "owner_p123"

    with _mock_env(user_data):
        res = client.post("/purchase-orders/po_123/approve")
        assert res.status_code == 403
        json_data = res.get_json()
        assert json_data["success"] is False
        assert "no tienes autorización" in json_data["error"]


def test_approve_purchase_order_success_by_different_user(app, client):
    """User with canApprovePurchaseOrders can approve an order created by another person."""
    user_data = _setup_session(
        {"canManagePurchaseOrders": True, "canApprovePurchaseOrders": True, "canSelfApprovePurchaseOrders": False},
        uid="approver_user_99",
        email="approver@corp.com",
        name="Gerente de Compras"
    )

    mock_po = {
        "id": "po_456",
        "poNumber": "OC-2026-0001",
        "status": "borrador",
        "createdByUid": "creator_user_11",
        "createdByEmail": "buyer@corp.com",
        "createdBy": "Comprador Junior",
        "total": 15000.0,
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["company_modules"] = _setup_company_modules()
        sess["selected_company_id"] = "comp_p123"
        sess["selected_owner_uid"] = "owner_p123"

    with _mock_env(user_data), \
         patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_order", return_value=mock_po), \
         patch("app.services.purchase_order_service.PurchaseOrderService.update_status") as mock_update_status, \
         patch("app.services.audit_service.AuditService.log_from_request"):

        mock_update_status.return_value = {**mock_po, "status": "aprobada", "approvedBy": "Gerente de Compras"}

        res = client.post("/purchase-orders/po_456/approve")
        assert res.status_code == 200
        json_data = res.get_json()
        assert json_data["success"] is True

        mock_update_status.assert_called_once_with(
            owner_uid="owner_p123",
            po_id="po_456",
            new_status="aprobada",
            company_id="comp_p123",
            sandbox=True,
            user="Gerente de Compras",
            approver_uid="approver_user_99",
            approver_email="approver@corp.com"
        )


def test_approve_purchase_order_sod_blocked_for_creator(app, client):
    """Creator with canApprovePurchaseOrders is blocked by SoD unless owner or has canSelfApprovePurchaseOrders."""
    user_data = _setup_session(
        {"canManagePurchaseOrders": True, "canApprovePurchaseOrders": True, "canSelfApprovePurchaseOrders": False},
        uid="buyer_user_11",
        email="buyer@corp.com",
        name="Comprador Junior"
    )

    mock_po = {
        "id": "po_456",
        "poNumber": "OC-2026-0001",
        "status": "pendiente_aprobacion",
        "createdByUid": "buyer_user_11",
        "createdByEmail": "buyer@corp.com",
        "createdBy": "Comprador Junior",
        "total": 25000.0,
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["company_modules"] = _setup_company_modules()
        sess["selected_company_id"] = "comp_p123"
        sess["selected_owner_uid"] = "owner_p123"

    with _mock_env(user_data), \
         patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_order", return_value=mock_po), \
         patch("app.services.purchase_order_service.PurchaseOrderService.update_status") as mock_update_status:

        res = client.post("/purchase-orders/po_456/approve")
        assert res.status_code == 403
        json_data = res.get_json()
        assert json_data["success"] is False
        assert json_data["code"] == "SOD_SELF_APPROVAL_DENIED"
        assert "segregación de funciones" in json_data["error"]
        mock_update_status.assert_not_called()


def test_approve_purchase_order_self_approval_granted(app, client):
    """Creator with explicit canSelfApprovePurchaseOrders permission CAN approve their own order."""
    user_data = _setup_session(
        {"canManagePurchaseOrders": True, "canApprovePurchaseOrders": True, "canSelfApprovePurchaseOrders": True},
        uid="director_user_55",
        email="director@corp.com",
        name="Director de Operaciones"
    )

    mock_po = {
        "id": "po_789",
        "poNumber": "OC-2026-0002",
        "status": "borrador",
        "createdByUid": "director_user_55",
        "createdByEmail": "director@corp.com",
        "createdBy": "Director de Operaciones",
        "total": 50000.0,
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["company_modules"] = _setup_company_modules()
        sess["selected_company_id"] = "comp_p123"
        sess["selected_owner_uid"] = "owner_p123"

    with _mock_env(user_data), \
         patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_order", return_value=mock_po), \
         patch("app.services.purchase_order_service.PurchaseOrderService.update_status") as mock_update_status, \
         patch("app.services.audit_service.AuditService.log_from_request"):

        mock_update_status.return_value = {**mock_po, "status": "aprobada"}

        res = client.post("/purchase-orders/po_789/approve")
        assert res.status_code == 200
        assert res.get_json()["success"] is True
        mock_update_status.assert_called_once()


def test_approve_purchase_order_owner_can_always_approve_own(app, client):
    """Owner can always approve their own order."""
    user_data = _setup_session(
        {},
        role="owner",
        uid="owner_p123",
        email="owner@corp.com",
        name="Dueño de Empresa"
    )

    mock_po = {
        "id": "po_999",
        "poNumber": "OC-2026-0003",
        "status": "borrador",
        "createdByUid": "owner_p123",
        "createdByEmail": "owner@corp.com",
        "createdBy": "Dueño de Empresa",
        "total": 100000.0,
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["company_modules"] = _setup_company_modules()
        sess["selected_company_id"] = "comp_p123"
        sess["selected_owner_uid"] = "owner_p123"

    with _mock_env(user_data), \
         patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_order", return_value=mock_po), \
         patch("app.services.purchase_order_service.PurchaseOrderService.update_status") as mock_update_status, \
         patch("app.services.audit_service.AuditService.log_from_request"):

        mock_update_status.return_value = {**mock_po, "status": "aprobada"}

        res = client.post("/purchase-orders/po_999/approve")
        assert res.status_code == 200
        assert res.get_json()["success"] is True
        mock_update_status.assert_called_once()


def test_approve_purchase_order_legacy_name_matching(app, client):
    """For legacy POs where only createdBy string was stored, SoD still blocks self-approval."""
    user_data = _setup_session(
        {"canManagePurchaseOrders": True, "canApprovePurchaseOrders": True, "canSelfApprovePurchaseOrders": False},
        uid="some_new_uid_99",
        email="pedro@empresa.com",
        name="Pedro Perez"
    )

    # Legacy PO without createdByUid, only displayName
    mock_po = {
        "id": "po_legacy_1",
        "poNumber": "OC-2025-0099",
        "status": "borrador",
        "createdBy": "Pedro Perez",
        "total": 5000.0,
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["company_modules"] = _setup_company_modules()
        sess["selected_company_id"] = "comp_p123"
        sess["selected_owner_uid"] = "owner_p123"

    with _mock_env(user_data), \
         patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_order", return_value=mock_po), \
         patch("app.services.purchase_order_service.PurchaseOrderService.update_status") as mock_update_status:

        res = client.post("/purchase-orders/po_legacy_1/approve")
        assert res.status_code == 403
        assert res.get_json()["code"] == "SOD_SELF_APPROVAL_DENIED"
        mock_update_status.assert_not_called()


def test_detail_view_sod_feedback_rendering(app, client):
    """Verify that detail page renders SoD banner and disabled button when creator cannot self-approve."""
    user_data = _setup_session(
        {"canManagePurchaseOrders": True, "canApprovePurchaseOrders": True, "canSelfApprovePurchaseOrders": False},
        uid="creator_123",
        email="creator@corp.com",
        name="Creador OC"
    )

    mock_po = {
        "id": "po_view_1",
        "poNumber": "OC-2026-0010",
        "status": "borrador",
        "createdByUid": "creator_123",
        "createdByEmail": "creator@corp.com",
        "createdBy": "Creador OC",
        "total": 12000.0,
        "subtotal": 10000.0,
        "items": [],
        "attachments": [],
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["company_modules"] = _setup_company_modules()
        sess["selected_company_id"] = "comp_p123"
        sess["selected_owner_uid"] = "owner_p123"

    with _mock_env(user_data), \
         patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_order", return_value=mock_po), \
         patch("app.services.goods_receipt_service.GoodsReceiptService.get_receipts_by_po", return_value=[]), \
         patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_by_po", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_resource_comments", return_value=[]), \
         patch("app.web.purchase_orders._get_taggable_users", return_value=[]):

        res = client.get("/purchase-orders/po_view_1")
        assert res.status_code == 200
        html = res.data.decode("utf-8")

        # SoD banner is visible
        assert "Segregación de Funciones" in html
        assert "Requiere 2do Aprobador" in html
        assert "Esperando aprobación de otro usuario (SoD)" in html
