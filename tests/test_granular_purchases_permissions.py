import pytest
from flask import session, render_template
from unittest.mock import patch
from app import create_app
from app.utils.decorators import check_permission, get_user_landing_url
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


def _setup_session(user_perms=None, role="collaborator"):
    perms = user_perms if user_perms is not None else {}
    return {
        "uid": "test_subuser_purchases",
        "email": "purchases@example.com",
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


def test_granular_purchases_permission_logic(app):
    """Test check_permission logic, overrides, and fallbacks for purchase permissions."""
    with app.test_request_context("/"):
        # 1. Owner always has all purchase permissions
        session["user"] = _setup_session({}, role="owner")
        for key in (
            "canManagePurchaseCXP",
            "canManagePurchaseOrders",
            "canManagePurchaseCreditNotes",
            "canManageSuppliers",
            "canCreateSupplier",
            "canExpenses",
            "canManageMinorExpenses",
            "canManageRecurringExpenses",
            "canManageReceivedECF",
        ):
            assert check_permission(key) is True

        # 2. Explicit grants with legacy=False
        session["user"] = _setup_session({"canExpenses": False, "canManagePurchaseOrders": True})
        assert check_permission("canManagePurchaseOrders") is True
        assert check_permission("canExpenses") is False

        session["user"] = _setup_session({"canExpenses": False, "canManageMinorExpenses": True})
        assert check_permission("canManageMinorExpenses") is True
        assert check_permission("canExpenses") is False

        session["user"] = _setup_session({"canExpenses": False, "canManageRecurringExpenses": True})
        assert check_permission("canManageRecurringExpenses") is True
        assert check_permission("canExpenses") is False

        session["user"] = _setup_session({"canExpenses": False, "canManageReceivedECF": True})
        assert check_permission("canManageReceivedECF") is True
        assert check_permission("canExpenses") is False

        session["user"] = _setup_session({"canManagePurchaseCXP": False, "canManagePurchaseCreditNotes": True})
        assert check_permission("canManagePurchaseCreditNotes") is True
        assert check_permission("canManagePurchaseCXP") is False

        # 3. Explicit denies take precedence over legacy=True
        session["user"] = _setup_session({"canExpenses": True, "canManagePurchaseOrders": False})
        assert check_permission("canManagePurchaseOrders") is False
        assert check_permission("canExpenses") is True

        session["user"] = _setup_session({"canExpenses": True, "canManageMinorExpenses": False})
        assert check_permission("canManageMinorExpenses") is False

        session["user"] = _setup_session({"canExpenses": True, "canManageRecurringExpenses": False})
        assert check_permission("canManageRecurringExpenses") is False

        session["user"] = _setup_session({"canExpenses": True, "canManageReceivedECF": False})
        assert check_permission("canManageReceivedECF") is False

        session["user"] = _setup_session({"canManagePurchaseCXP": True, "canManagePurchaseCreditNotes": False})
        assert check_permission("canManagePurchaseCreditNotes") is False

        # 4. Backward compatibility: fallback to canExpenses when granular keys absent
        session["user"] = _setup_session({"canExpenses": True})
        assert check_permission("canManagePurchaseOrders") is True
        assert check_permission("canManageMinorExpenses") is True
        assert check_permission("canManageRecurringExpenses") is True
        assert check_permission("canManageReceivedECF") is True

        session["user"] = _setup_session({"canExpenses": False})
        assert check_permission("canManagePurchaseOrders") is False
        assert check_permission("canManageMinorExpenses") is False
        assert check_permission("canManageRecurringExpenses") is False
        assert check_permission("canManageReceivedECF") is False

        # 5. Backward compatibility: fallback to canManagePurchaseCXP when canManagePurchaseCreditNotes absent
        session["user"] = _setup_session({"canManagePurchaseCXP": True})
        assert check_permission("canManagePurchaseCreditNotes") is True

        session["user"] = _setup_session({"canManagePurchaseCXP": False})
        assert check_permission("canManagePurchaseCreditNotes") is False


def test_purchases_presets_matrix_and_permission_groups():
    """Verify ALL_PERMISSION_KEYS, PERMISSION_GROUPS, and ROLES_PRESETS for Compras y Proveedores."""
    new_keys = [
        "canManagePurchaseOrders",
        "canManagePurchaseCreditNotes",
        "canManageMinorExpenses",
        "canManageRecurringExpenses",
        "canManageReceivedECF",
    ]
    for key in new_keys:
        assert key in ALL_PERMISSION_KEYS, f"{key} must be registered in ALL_PERMISSION_KEYS"

    # Dedicated "Compras y Proveedores" group exists
    compras_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Compras y Proveedores"), None)
    assert compras_group is not None, "PERMISSION_GROUPS must have 'Compras y Proveedores' group"
    group_perms = compras_group.get("perms", [])
    expected_group_perms = [
        "canManagePurchaseCXP",
        "canManagePurchaseOrders",
        "canManagePurchaseCreditNotes",
        "canManageSuppliers",
        "canCreateSupplier",
        "canExpenses",
        "canManageMinorExpenses",
        "canManageRecurringExpenses",
        "canManageReceivedECF",
    ]
    for p in expected_group_perms:
        assert p in group_perms, f"{p} must be in 'Compras y Proveedores' group"

    # Verify Financiero / Finanzas y Tesorería does NOT contain canExpenses or canManagePurchaseCXP
    financiero_group = next((g for g in PERMISSION_GROUPS if g.get("name") in ("Financiero", "Finanzas y Tesorería")), None)
    assert financiero_group is not None
    assert "canExpenses" not in financiero_group.get("perms", [])
    assert "canManagePurchaseCXP" not in financiero_group.get("perms", [])

    # Verify Administración / Configuración / Sistema does NOT contain canManageSuppliers or canCreateSupplier
    admin_group = next((g for g in PERMISSION_GROUPS if g.get("name") in ("Administración", "Configuración y Empresa", "Sistema y Auditoría")), None)
    assert admin_group is not None
    assert "canManageSuppliers" not in admin_group.get("perms", [])
    assert "canCreateSupplier" not in admin_group.get("perms", [])

    # Role presets check
    for key in new_keys:
        assert ROLES_PRESETS["administrador"][key] is True
        assert ROLES_PRESETS["contador"][key] is True
        assert ROLES_PRESETS["vendedor"][key] is False
        assert ROLES_PRESETS["consulta"][key] is False


def test_landing_url_for_granular_purchase_permissions(app):
    """Verify get_user_landing_url lands on the specific active sub-permission."""
    with app.test_request_context("/"):
        session["company_modules"] = _setup_company_modules()

        # User with only canManagePurchaseOrders
        session["user"] = _setup_session({
            "canViewDashboard": False,
            "canInvoice": False,
            "canManageFiscalNotes": False,
            "canExpenses": False,
            "canManagePurchaseCXP": False,
            "canManagePurchaseOrders": True,
            "canManagePurchaseCreditNotes": False,
            "canManageSuppliers": False,
            "canCreateSupplier": False,
            "canManageCXP": False,
        })
        assert get_user_landing_url() == "/purchase-orders"

        # User with only canManagePurchaseCreditNotes
        session["user"] = _setup_session({
            "canViewDashboard": False,
            "canInvoice": False,
            "canManageFiscalNotes": False,
            "canExpenses": False,
            "canManagePurchaseCXP": False,
            "canManagePurchaseOrders": False,
            "canManagePurchaseCreditNotes": True,
            "canManageSuppliers": False,
            "canCreateSupplier": False,
            "canManageCXP": False,
        })
        assert get_user_landing_url() == "/purchase-orders/credit-notes"

        # User with only canManageMinorExpenses
        session["user"] = _setup_session({
            "canViewDashboard": False,
            "canInvoice": False,
            "canManageFiscalNotes": False,
            "canExpenses": False,
            "canManagePurchaseCXP": False,
            "canManagePurchaseOrders": False,
            "canManagePurchaseCreditNotes": False,
            "canManageSuppliers": False,
            "canCreateSupplier": False,
            "canManageCXP": False,
            "canManageMinorExpenses": True,
        })
        assert get_user_landing_url() == "/expenses/minor"

        # User with only canManageRecurringExpenses
        session["user"] = _setup_session({
            "canViewDashboard": False,
            "canInvoice": False,
            "canManageFiscalNotes": False,
            "canExpenses": False,
            "canManagePurchaseCXP": False,
            "canManagePurchaseOrders": False,
            "canManagePurchaseCreditNotes": False,
            "canManageSuppliers": False,
            "canCreateSupplier": False,
            "canManageCXP": False,
            "canManageRecurringExpenses": True,
        })
        assert get_user_landing_url() == "/expenses/recurring"

        # User with only canManageReceivedECF
        session["user"] = _setup_session({
            "canViewDashboard": False,
            "canInvoice": False,
            "canManageFiscalNotes": False,
            "canExpenses": False,
            "canManagePurchaseCXP": False,
            "canManagePurchaseOrders": False,
            "canManagePurchaseCreditNotes": False,
            "canManageSuppliers": False,
            "canCreateSupplier": False,
            "canManageCXP": False,
            "canManageReceivedECF": True,
        })
        assert get_user_landing_url() == "/recepcion/ecf"


def test_sidebar_nav_compras_granular_rendering(app):
    """Test that sidebar hides the Compras section or renders only permitted items."""
    with app.test_request_context("/"):
        session["company_modules"] = _setup_company_modules()

        # User with NO purchase permissions -> Compras section NOT rendered
        session["user"] = _setup_session({
            "canManagePurchaseCXP": False,
            "canManagePurchaseOrders": False,
            "canManagePurchaseCreditNotes": False,
            "canManageSuppliers": False,
            "canExpenses": False,
            "canManageMinorExpenses": False,
            "canManageRecurringExpenses": False,
            "canManageReceivedECF": False,
        })
        rendered = render_template("_sidebar_nav.html")
        assert "sidebar-section-compras" not in rendered

        # User with ONLY canManageMinorExpenses -> Compras section rendered, ONLY minor expenses visible
        session["user"] = _setup_session({
            "canManagePurchaseCXP": False,
            "canManagePurchaseOrders": False,
            "canManagePurchaseCreditNotes": False,
            "canManageSuppliers": False,
            "canExpenses": False,
            "canManageMinorExpenses": True,
            "canManageRecurringExpenses": False,
            "canManageReceivedECF": False,
        })
        rendered = render_template("_sidebar_nav.html")
        assert "sidebar-section-compras" in rendered
        assert "Gastos menores" in rendered
        assert "Facturas de proveedores" not in rendered
        assert "Órdenes de compra" not in rendered
        assert "Notas de crédito en compras" not in rendered
        assert "Pagos recurrentes" not in rendered
        assert "e-CF Recibidos" not in rendered


def test_endpoints_granular_http_guards(app, client):
    """Verify that HTTP endpoints fail closed (403) when lacking granular permissions, and succeed (200) when granted."""
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
    user_data = _setup_session({
        "canManagePurchaseOrders": False,
        "canManagePurchaseCreditNotes": False,
        "canManageMinorExpenses": False,
        "canManageRecurringExpenses": False,
        "canManageReceivedECF": False,
    })

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': 'collaborator', 'permissions': user_data.get('permissions', {})}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'cxp_compras': {'enabled': True}, 'gastos': {'enabled': True}, 'e_cf': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_p123', 'owner_uid': 'owner_p123', 'company_name': 'Compras Test SRL', 'rnc': '131880681', 'role': 'collaborator', 'permissions': user_data.get('permissions', {}), 'company': company_doc}), \
         patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_orders", return_value=[]), \
         patch("app.services.purchase_credit_note_service.PurchaseCreditNoteService.get_all", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_expenses", return_value=[]), \
         patch("app.repositories.receptor_repository.ReceptorRepository.list_received_ecf_merged", return_value=[]):

        # Initial session with all granular denied
        with client.session_transaction() as sess:
            sess["user"] = user_data
            sess["company_modules"] = _setup_company_modules()
            sess["selected_company_id"] = "comp_p123"
            sess["selected_owner_uid"] = "owner_p123"

        # 1. Purchase Orders endpoint (/purchase-orders)
        assert client.get("/purchase-orders").status_code == 403
        user_data["permissions"]["canManagePurchaseOrders"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/purchase-orders").status_code == 200

        # 2. Purchase Credit Notes endpoint (/purchase-orders/credit-notes)
        assert client.get("/purchase-orders/credit-notes").status_code == 403
        user_data["permissions"]["canManagePurchaseCreditNotes"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/purchase-orders/credit-notes").status_code == 200

        # 3. Minor Expenses endpoint (/expenses/minor)
        assert client.get("/expenses/minor").status_code == 403
        user_data["permissions"]["canManageMinorExpenses"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/expenses/minor").status_code == 200

        # 4. Recurring Expenses endpoint (/expenses/recurring)
        assert client.get("/expenses/recurring").status_code == 403
        user_data["permissions"]["canManageRecurringExpenses"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/expenses/recurring").status_code == 200

        # 5. Received e-CF endpoint (/recepcion/ecf)
        assert client.get("/recepcion/ecf").status_code == 403
        user_data["permissions"]["canManageReceivedECF"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/recepcion/ecf").status_code == 200
