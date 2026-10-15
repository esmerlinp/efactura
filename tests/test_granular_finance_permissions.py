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
        "uid": "test_subuser_finance",
        "email": "finance_user@example.com",
        "ownerUID": "owner_finance123",
        "company_id": "comp_finance123",
        "role": role,
        "permissions": perms,
    }


def _setup_company_modules():
    return {
        "cxc": {"enabled": True},
        "banks": {"enabled": True},
        "contabilidad": {"enabled": True},
    }


def test_granular_finance_permissions_logic(app):
    """Test check_permission logic, overrides, and fallbacks for Finance permissions."""
    with app.test_request_context("/"):
        # 1. Owner always has all finance permissions
        session["user"] = _setup_session({}, role="owner")
        for key in (
            "canManageCXC",
            "canManageCXCAdvances",
            "canManageBanks",
            "canBankReconciliation",
            "canAccounting",
        ):
            assert check_permission(key) is True

        # 2. Explicit grants with legacy parents False
        session["user"] = _setup_session({"canManageCXC": False, "canManageCXCAdvances": True})
        assert check_permission("canManageCXCAdvances") is True
        assert check_permission("canManageCXC") is False

        session["user"] = _setup_session({"canExpenses": False, "canManageBanks": True})
        assert check_permission("canManageBanks") is True
        assert check_permission("canExpenses") is False

        session["user"] = _setup_session({"canExpenses": False, "canManageBanks": False, "canBankReconciliation": True})
        assert check_permission("canBankReconciliation") is True
        assert check_permission("canManageBanks") is False

        # 3. Explicit denies take precedence over legacy parent True
        session["user"] = _setup_session({"canManageCXC": True, "canManageCXCAdvances": False})
        assert check_permission("canManageCXCAdvances") is False
        assert check_permission("canManageCXC") is True

        session["user"] = _setup_session({"canExpenses": True, "canManageBanks": False})
        assert check_permission("canManageBanks") is False
        assert check_permission("canExpenses") is True

        session["user"] = _setup_session({"canManageBanks": True, "canBankReconciliation": False})
        assert check_permission("canBankReconciliation") is False
        assert check_permission("canManageBanks") is True

        # 4. Backward compatibility: fallback when granular keys absent
        session["user"] = _setup_session({"canManageCXC": True})
        assert check_permission("canManageCXCAdvances") is True

        session["user"] = _setup_session({"canManageCXC": False})
        assert check_permission("canManageCXCAdvances") is False

        session["user"] = _setup_session({"canExpenses": True})
        assert check_permission("canManageBanks") is True
        assert check_permission("canBankReconciliation") is True

        session["user"] = _setup_session({"canExpenses": False})
        assert check_permission("canManageBanks") is False
        assert check_permission("canBankReconciliation") is False


def test_finance_presets_matrix_and_permission_groups():
    """Verify ALL_PERMISSION_KEYS, PERMISSION_GROUPS, and ROLES_PRESETS for Finanzas y Tesorería."""
    finance_keys = [
        "canManageCXCAdvances",
        "canManageBanks",
        "canBankReconciliation",
    ]
    for key in finance_keys:
        assert key in ALL_PERMISSION_KEYS, f"{key} must be in ALL_PERMISSION_KEYS"

    # Dedicated "Finanzas y Tesorería" group exists
    finance_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Finanzas y Tesorería"), None)
    assert finance_group is not None, "PERMISSION_GROUPS must have 'Finanzas y Tesorería' group"
    group_perms = finance_group.get("perms", [])
    for key in ("canManageCXC", "canManageCXCAdvances", "canManageBanks", "canBankReconciliation"):
        assert key in group_perms, f"{key} must be in Finanzas y Tesorería perms"

    # Presets verification
    admin = ROLES_PRESETS["administrador"]
    for key in finance_keys:
        assert admin[key] is True

    vendedor = ROLES_PRESETS["vendedor"]
    assert vendedor["canManageCXC"] is False
    assert vendedor["canManageCXCAdvances"] is False
    assert vendedor["canManageBanks"] is False
    assert vendedor["canBankReconciliation"] is False

    contador = ROLES_PRESETS["contador"]
    assert contador["canManageCXC"] is True
    assert contador["canManageCXCAdvances"] is True
    assert contador["canManageBanks"] is True
    assert contador["canBankReconciliation"] is True

    consulta = ROLES_PRESETS["consulta"]
    assert consulta["canManageCXC"] is False
    assert consulta["canManageCXCAdvances"] is False
    assert consulta["canManageBanks"] is False
    assert consulta["canBankReconciliation"] is False


def test_finance_routes_protection(client):
    """Verify route access control for advances, banks, and reconcile."""
    user_data = _setup_session({
        "canManageCXC": False,
        "canManageCXCAdvances": False,
        "canManageBanks": False,
        "canBankReconciliation": False,
        "canExpenses": False,
    })
    company_doc = {
        "id": "comp_finance123",
        "status": "Activo",
        "planId": "plan_test",
        "plan_id": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_finance123",
        "country": "DO",
        "configured": True,
        "pos_enabled": False,
        "production_enabled": True,
        "sandbox_enabled": True,
        "companyName": "Finance Test SRL",
        "companyRNC": "131880681",
    }

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': 'collaborator', 'permissions': user_data.get('permissions', {})}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'cxc': {'enabled': True}, 'banks': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_finance123', 'owner_uid': 'owner_finance123', 'company_name': 'Finance Test SRL', 'rnc': '131880681', 'role': 'collaborator', 'permissions': user_data.get('permissions', {}), 'company': company_doc}), \
         patch("app.services.db_service.DatabaseService.get_bank_accounts", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_bank_summary", return_value={"bankCashBalance": 0.0, "creditDebt": 0.0, "totalBalance": 0.0}), \
         patch("app.services.db_service.DatabaseService.get_reconciliations", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_client_advances", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_clients", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_invoices", return_value=[]):

        with client.session_transaction() as sess:
            sess["user"] = user_data
            sess["company_modules"] = _setup_company_modules()
            sess["selected_company_id"] = "comp_finance123"
            sess["selected_owner_uid"] = "owner_finance123"
            sess["company_plan_id"] = "plan_test"

        # 1. Advances route (/cxc/advances)
        assert client.get("/cxc/advances").status_code == 403
        user_data["permissions"]["canManageCXCAdvances"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/cxc/advances").status_code == 200

        # 2. Banks route (/banks)
        assert client.get("/banks").status_code == 403
        user_data["permissions"]["canManageBanks"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/banks").status_code == 200

        # 3. Reconcile route (/banks/reconcile)
        assert client.get("/banks/reconcile").status_code == 403
        user_data["permissions"]["canBankReconciliation"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/banks/reconcile").status_code == 200


def test_finance_sidebar_gating(app):
    """Test that sidebar items and the container render according to granular permissions."""
    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", return_value=True):
            # 1. No permissions -> Section completely hidden
            session["user"] = _setup_session({
                "canManageCXC": False,
                "canManageCXCAdvances": False,
                "canManageBanks": False,
                "canBankReconciliation": False,
                "canAccounting": False,
            })
            session["company_modules"] = _setup_company_modules()
            rendered = render_template("_sidebar_nav.html")
            assert 'id="sidebar-section-finanzas"' not in rendered

            # 2. Only canManageCXCAdvances -> Shows container and advances link, but hides others
            session["user"] = _setup_session({
                "canManageCXC": False,
                "canManageCXCAdvances": True,
                "canManageBanks": False,
                "canBankReconciliation": False,
                "canAccounting": False,
            })
            rendered = render_template("_sidebar_nav.html")
            assert 'id="sidebar-section-finanzas"' in rendered
            assert 'href="/cxc/advances"' in rendered
            assert 'href="/cxc"' not in rendered
            assert 'href="/banks"' not in rendered
            assert 'href="/banks/reconcile"' not in rendered

            # 3. Only canBankReconciliation -> Shows reconcile link, hides banks list
            session["user"] = _setup_session({
                "canManageCXC": False,
                "canManageCXCAdvances": False,
                "canManageBanks": False,
                "canBankReconciliation": True,
                "canAccounting": False,
            })
            rendered = render_template("_sidebar_nav.html")
            assert 'id="sidebar-section-finanzas"' in rendered
            assert 'href="/banks/reconcile"' in rendered
            assert 'href="/banks"' not in rendered
            assert 'href="/cxc"' not in rendered


def test_finance_landing_url_routing(app):
    """Test that get_user_landing_url correctly routes to the highest-priority finance submodule."""
    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", side_effect=lambda mod: mod in ("cxc", "banks", "contabilidad")):
            session["company_modules"] = _setup_company_modules()

            # 1. User with only canManageCXCAdvances -> routes to /cxc/advances
            session["user"] = _setup_session({
                "canViewDashboard": False,
                "canInvoice": False,
                "canManageFiscalNotes": False,
                "canManageQuotations": False,
                "canCRM": False,
                "canClients": False,
                "canManageCatalog": False,
                "canManageInventory": False,
                "canExpenses": False,
                "canManageCXC": False,
                "canManageCXCAdvances": True,
                "canManageBanks": False,
                "canBankReconciliation": False,
                "canAccounting": False,
            })
            assert get_user_landing_url() == "/cxc/advances"

            # 2. User with only canManageBanks -> routes to /banks
            session["user"] = _setup_session({
                "canViewDashboard": False,
                "canInvoice": False,
                "canManageFiscalNotes": False,
                "canManageQuotations": False,
                "canCRM": False,
                "canClients": False,
                "canManageCatalog": False,
                "canManageInventory": False,
                "canExpenses": False,
                "canManageCXC": False,
                "canManageCXCAdvances": False,
                "canManageBanks": True,
                "canBankReconciliation": False,
                "canAccounting": False,
            })
            assert get_user_landing_url() == "/banks"

            # 3. User with only canBankReconciliation -> routes to /banks/reconcile
            session["user"] = _setup_session({
                "canViewDashboard": False,
                "canInvoice": False,
                "canManageFiscalNotes": False,
                "canManageQuotations": False,
                "canCRM": False,
                "canClients": False,
                "canManageCatalog": False,
                "canManageInventory": False,
                "canExpenses": False,
                "canManageCXC": False,
                "canManageCXCAdvances": False,
                "canManageBanks": False,
                "canBankReconciliation": True,
                "canAccounting": False,
            })
            assert get_user_landing_url() == "/banks/reconcile"
