import pytest
from flask import session
from app.utils.decorators import check_permission
from app.web.invoices import ROLES_PRESETS, ALL_PERMISSION_KEYS, PERMISSION_GROUPS, resolve_permissions, detect_role_from_permissions


def _setup_session(app, user_perms, role="employee"):
    return {
        "uid": "emp_123",
        "ownerUID": "owner_abc",
        "company_id": "company_test_01",
        "role": role,
        "email": "employee@example.com",
        "name": "Test Employee",
        "permissions": user_perms,
    }


def test_granular_quotations_permission_logic(app):
    with app.test_request_context():
        # 1. Owner always has permission
        session["user"] = {"role": "owner", "permissions": {}}
        assert check_permission("canManageQuotations") is True
        assert check_permission("canCreateQuotation") is True

        # 2. Explicitly True
        session["user"] = _setup_session(app, {"canManageQuotations": True, "canInvoice": False})
        assert check_permission("canManageQuotations") is True

        # 3. Explicitly False
        session["user"] = _setup_session(app, {"canManageQuotations": False, "canInvoice": True})
        assert check_permission("canManageQuotations") is False

        # 4. Backward compatibility fallback: key absent -> fallback to canInvoice
        session["user"] = _setup_session(app, {"canInvoice": True})
        assert check_permission("canManageQuotations") is True

        session["user"] = _setup_session(app, {"canInvoice": False})
        assert check_permission("canManageQuotations") is False


def test_granular_inventory_permissions_logic(app):
    with app.test_request_context():
        # 1. Owner always has permission
        session["user"] = {"role": "owner", "permissions": {}}
        for key in (
            "canManageCatalog", "canViewInventoryDashboard", "canInventoryKardex",
            "canInventoryReceipts", "canInventoryTransfers", "canInventoryCounts",
            "canInventoryLots", "canManageWarehouses", "canInventoryAdjustments", "canManagePriceLists"
        ):
            assert check_permission(key) is True

        # 2. Granular inventory permissions when explicitly set
        session["user"] = _setup_session(app, {
            "canManageInventory": False,
            "canManageCatalog": True,
            "canViewInventoryDashboard": True,
            "canInventoryKardex": False,
            "canInventoryReceipts": True,
            "canInventoryTransfers": False,
            "canInventoryCounts": False,
            "canInventoryLots": True,
            "canManageWarehouses": False,
            "canInventoryAdjustments": False,
            "canManagePriceLists": False,
        })
        assert check_permission("canManageCatalog") is True
        assert check_permission("canViewInventoryDashboard") is True
        assert check_permission("canInventoryKardex") is False
        assert check_permission("canInventoryReceipts") is True
        assert check_permission("canInventoryTransfers") is False
        assert check_permission("canInventoryLots") is True
        assert check_permission("canManageWarehouses") is False
        assert check_permission("canInventoryAdjustments") is False

        # 3. Backward compatibility fallback: granular keys absent -> fallback to canManageInventory
        session["user"] = _setup_session(app, {"canManageInventory": True})
        for key in (
            "canManageCatalog", "canViewInventoryDashboard", "canInventoryKardex",
            "canInventoryReceipts", "canInventoryTransfers", "canInventoryCounts",
            "canInventoryLots", "canManageWarehouses", "canInventoryAdjustments", "canManagePriceLists"
        ):
            assert check_permission(key) is True

        session["user"] = _setup_session(app, {"canManageInventory": False})
        for key in (
            "canViewInventoryDashboard", "canInventoryKardex", "canInventoryReceipts",
            "canInventoryTransfers", "canInventoryCounts", "canInventoryLots",
            "canManageWarehouses", "canInventoryAdjustments"
        ):
            assert check_permission(key) is False

        # 4. Catalog fallback to canClients if canManageInventory not present
        session["user"] = _setup_session(app, {"canClients": True})
        assert check_permission("canManageCatalog") is True

        session["user"] = _setup_session(app, {"canClients": False})
        assert check_permission("canManageCatalog") is False


def test_presets_matrix_contains_granular_permissions():
    for key in (
        "canManageQuotations", "canManageCatalog", "canViewInventoryDashboard",
        "canInventoryKardex", "canInventoryReceipts", "canInventoryTransfers",
        "canInventoryCounts", "canInventoryLots", "canManageWarehouses",
        "canInventoryAdjustments", "canManagePriceLists"
    ):
        assert key in ALL_PERMISSION_KEYS
        assert key in ROLES_PRESETS["administrador"]
        assert key in ROLES_PRESETS["vendedor"]
        assert key in ROLES_PRESETS["contador"]
        assert key in ROLES_PRESETS["consulta"]

    # Role specific validations
    assert ROLES_PRESETS["administrador"]["canManageQuotations"] is True
    assert ROLES_PRESETS["administrador"]["canInventoryKardex"] is True

    assert ROLES_PRESETS["vendedor"]["canManageQuotations"] is True
    assert ROLES_PRESETS["vendedor"]["canManageCatalog"] is True
    assert ROLES_PRESETS["vendedor"]["canViewInventoryDashboard"] is True
    assert ROLES_PRESETS["vendedor"]["canInventoryKardex"] is False
    assert ROLES_PRESETS["vendedor"]["canInventoryReceipts"] is False

    assert ROLES_PRESETS["contador"]["canManageQuotations"] is False
    assert ROLES_PRESETS["contador"]["canInventoryKardex"] is True
    assert ROLES_PRESETS["contador"]["canInventoryCounts"] is True
    assert ROLES_PRESETS["contador"]["canManageCatalog"] is False

    assert ROLES_PRESETS["consulta"]["canManageQuotations"] is False
    assert ROLES_PRESETS["consulta"]["canViewInventoryDashboard"] is True
    assert ROLES_PRESETS["consulta"]["canInventoryKardex"] is False


def test_permission_groups_structure():
    group_names = [g["name"] for g in PERMISSION_GROUPS]
    assert "Módulos Principales" in group_names
    assert "Productos e Inventario" in group_names

    main_group = next(g for g in PERMISSION_GROUPS if g["name"] == "Módulos Principales")
    assert "canManageQuotations" in main_group["perms"]

    inv_group = next(g for g in PERMISSION_GROUPS if g["name"] == "Productos e Inventario")
    expected_inv_perms = [
        "canManageCatalog", "canViewInventoryDashboard", "canInventoryKardex",
        "canInventoryReceipts", "canInventoryTransfers", "canInventoryCounts",
        "canInventoryLots", "canManageWarehouses", "canInventoryAdjustments",
        "canManagePriceLists", "canManageInventory"
    ]
    for p in expected_inv_perms:
        assert p in inv_group["perms"]
        assert p in inv_group["labels"]


def test_http_route_protection_quotations_and_inventory(client):
    from unittest.mock import patch

    user_data = {
        "uid": "collab_01",
        "ownerUID": "owner_01",
        "role": "employee",
        "email": "collab@example.com",
        "name": "Collab Test",
        "permissions": {
            "canManageQuotations": False,
            "canManageCatalog": False,
            "canViewInventoryDashboard": False,
            "canInventoryKardex": False,
            "canInventoryReceipts": False,
            "canInventoryTransfers": False,
            "canInventoryCounts": False,
            "canInventoryLots": False,
            "canManageWarehouses": False,
            "canInventoryAdjustments": False,
        }
    }
    company_doc = {
        'id': 'comp_test',
        'status': 'Activo',
        'owner_uid': 'owner_01',
        'configured': True,
        'planId': 'test_plan',
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["selected_company_id"] = "comp_test"
        sess["is_sandbox_mode"] = True
        sess["company_modules"] = {}

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'modules': {}}), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value={'status': 'active', 'role': 'employee', 'permissions': user_data['permissions']}), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value={'company_id': 'comp_test', 'owner_uid': 'owner_01', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'employee', 'permissions': user_data['permissions'], 'company': company_doc}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None):

        # Blocked routes (403)
        res_quotations = client.get("/quotations")
        assert res_quotations.status_code == 403

        res_items = client.get("/items")
        assert res_items.status_code == 403

        res_inventory = client.get("/inventory")
        assert res_inventory.status_code == 403

        res_kardex = client.get("/inventory/kardex")
        assert res_kardex.status_code == 403

        res_receipts = client.get("/inventory/receipts")
        assert res_receipts.status_code == 403

        res_transfers = client.get("/inventory/transfers")
        assert res_transfers.status_code == 403

        res_counts = client.get("/inventory/physical-counts")
        assert res_counts.status_code == 403

        res_lots = client.get("/inventory/lots")
        assert res_lots.status_code == 403

        res_warehouses = client.get("/inventory/warehouses")
        assert res_warehouses.status_code == 403

        res_transactions = client.get("/inventory/transactions")
        assert res_transactions.status_code == 403


def test_user_with_only_inventory_counts_redirects_to_counts_page(app, client):
    """Verifica que un usuario que sólo tiene permiso de conteo físico no reciba 403 al entrar al dashboard,
    sino que sea redirigido automáticamente a /inventory/physical-counts."""
    from unittest.mock import patch
    from app.utils.decorators import get_user_landing_url

    user_data = {
        "uid": "collab_counts_only",
        "ownerUID": "owner_01",
        "role": "employee",
        "email": "counts@example.com",
        "name": "Counts Only",
        "permissions": {
            "canViewDashboard": False,
            "canInvoice": False,
            "canManagePOS": False,
            "canClients": False,
            "canManageInventory": False,
            "canExpenses": False,
            "canInventoryCounts": True,
        }
    }
    company_doc = {
        'id': 'comp_test',
        'status': 'Activo',
        'owner_uid': 'owner_01',
        'configured': True,
        'planId': 'test_plan',
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["selected_company_id"] = "comp_test"
        sess["is_sandbox_mode"] = True
        sess["company_modules"] = {'inventario': {'enabled': True}}

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'modules': {'inventario': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value={'status': 'active', 'role': 'employee', 'permissions': user_data['permissions']}), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value={'company_id': 'comp_test', 'owner_uid': 'owner_01', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'employee', 'permissions': user_data['permissions'], 'company': company_doc}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.physical_count_service.PhysicalCountService.get_counts", return_value=[]):

        # 1. get_user_landing_url() debe retornar la ruta de conteos físicos
        with app.test_request_context():
            session["user"] = user_data
            session["company_modules"] = {'inventario': {'enabled': True}}
            landing = get_user_landing_url()
            assert landing == "/inventory/physical-counts"

        # 2. Acceder al dashboard no debe dar 403, sino redirigir (302) a /inventory/physical-counts
        res_dash = client.get("/dashboard")
        assert res_dash.status_code == 302
        assert res_dash.headers["Location"].endswith("/inventory/physical-counts")

        # 3. Acceder a /inventory/physical-counts debe responder 200 OK
        res_counts = client.get("/inventory/physical-counts")
        assert res_counts.status_code == 200

