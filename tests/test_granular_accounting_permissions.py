import pytest
from flask import session, render_template
from contextlib import ExitStack
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
        "uid": "test_subuser_accounting",
        "email": "accounting_user@example.com",
        "ownerUID": "owner_acc123",
        "company_id": "comp_acc123",
        "role": role,
        "permissions": perms,
    }


def _setup_company_modules():
    return {
        "cxc": {"enabled": True},
        "banks": {"enabled": True},
        "contabilidad": {"enabled": True},
    }


def test_granular_accounting_permissions_logic(app):
    """Test check_permission logic, overrides, and fallbacks for Accounting permissions."""
    with app.test_request_context("/"):
        # 1. Owner always has all accounting permissions
        session["user"] = _setup_session({}, role="owner")
        for key in (
            "canAccounting",
            "canAccountingDashboard",
            "canAccountingChart",
            "canAccountingJournal",
            "canAccountingReports",
            "canAccountingFixedAssets",
            "canAccountingFiscalPeriods",
            "canAccountingSettings",
        ):
            assert check_permission(key) is True

        # 2. Explicit grants with legacy parent False
        session["user"] = _setup_session({"canAccounting": False, "canAccountingDashboard": True})
        assert check_permission("canAccountingDashboard") is True
        assert check_permission("canAccounting") is False

        session["user"] = _setup_session({"canAccounting": False, "canAccountingReports": True})
        assert check_permission("canAccountingReports") is True
        assert check_permission("canAccounting") is False

        # 3. Explicit denies take precedence over legacy parent True
        session["user"] = _setup_session({"canAccounting": True, "canAccountingFiscalPeriods": False})
        assert check_permission("canAccountingFiscalPeriods") is False
        assert check_permission("canAccounting") is True

        session["user"] = _setup_session({"canAccounting": True, "canAccountingSettings": False})
        assert check_permission("canAccountingSettings") is False
        assert check_permission("canAccounting") is True

        # 4. Backward compatibility: fallback when granular keys absent
        session["user"] = _setup_session({"canAccounting": True})
        for key in (
            "canAccountingDashboard",
            "canAccountingChart",
            "canAccountingJournal",
            "canAccountingReports",
            "canAccountingFixedAssets",
            "canAccountingFiscalPeriods",
            "canAccountingSettings",
        ):
            assert check_permission(key) is True

        session["user"] = _setup_session({"canAccounting": False})
        for key in (
            "canAccountingDashboard",
            "canAccountingChart",
            "canAccountingJournal",
            "canAccountingReports",
            "canAccountingFixedAssets",
            "canAccountingFiscalPeriods",
            "canAccountingSettings",
        ):
            assert check_permission(key) is False

        # 5. Synergy with canReportsAccounting fallback
        session["user"] = _setup_session({"canAccounting": False, "canReportsAccounting": True})
        assert check_permission("canAccountingReports") is True


def test_accounting_presets_matrix_and_permission_groups():
    """Verify ALL_PERMISSION_KEYS, PERMISSION_GROUPS, and ROLES_PRESETS for Contabilidad."""
    acc_keys = [
        "canAccountingDashboard",
        "canAccountingChart",
        "canAccountingJournal",
        "canAccountingReports",
        "canAccountingFixedAssets",
        "canAccountingFiscalPeriods",
        "canAccountingSettings",
    ]
    for key in acc_keys:
        assert key in ALL_PERMISSION_KEYS, f"{key} must be in ALL_PERMISSION_KEYS"

    # Dedicated "Contabilidad" group exists
    acc_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Contabilidad"), None)
    assert acc_group is not None, "PERMISSION_GROUPS must have 'Contabilidad' group"
    group_perms = acc_group.get("perms", [])
    assert "canAccounting" in group_perms
    for key in acc_keys:
        assert key in group_perms, f"{key} must be in Contabilidad perms"

    # Presets verification
    admin = ROLES_PRESETS["administrador"]
    for key in acc_keys:
        assert admin[key] is True

    vendedor = ROLES_PRESETS["vendedor"]
    for key in acc_keys:
        assert vendedor[key] is False

    contador = ROLES_PRESETS["contador"]
    for key in acc_keys:
        assert contador[key] is True

    consulta = ROLES_PRESETS["consulta"]
    assert consulta["canAccountingDashboard"] is True
    assert consulta["canAccountingReports"] is True
    assert consulta["canAccountingChart"] is False
    assert consulta["canAccountingJournal"] is False
    assert consulta["canAccountingFixedAssets"] is False
    assert consulta["canAccountingFiscalPeriods"] is False
    assert consulta["canAccountingSettings"] is False


def test_accounting_routes_protection(client):
    """Verify route access control for all granular accounting sub-modules."""
    user_data = _setup_session({
        "canAccounting": False,
        "canAccountingDashboard": False,
        "canAccountingChart": False,
        "canAccountingJournal": False,
        "canAccountingReports": False,
        "canAccountingFixedAssets": False,
        "canAccountingFiscalPeriods": False,
        "canAccountingSettings": False,
    })
    company_doc = {
        "id": "comp_acc123",
        "status": "Activo",
        "planId": "plan_test",
        "plan_id": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_acc123",
        "country": "DO",
        "configured": True,
        "pos_enabled": False,
        "production_enabled": True,
        "sandbox_enabled": True,
        "companyName": "Accounting Test SRL",
        "companyRNC": "131880681",
    }

    dummy_tree = []
    dummy_accounts = []
    dummy_balance = {"activos": {"total": 0.0}, "pasivos": {"total": 0.0}, "patrimonio": {"total": 0.0}}
    dummy_income = {"netIncome": 0.0}
    dummy_trial = {"rows": [], "totalDebit": 0.0, "totalCredit": 0.0}

    with ExitStack() as stack:
        stack.enter_context(patch("app.utils.module_gate.module_enabled", return_value=True))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': 'collaborator', 'permissions': user_data.get('permissions', {})}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'contabilidad': {'enabled': True}}}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_branches", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_projects", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_acc123', 'owner_uid': 'owner_acc123', 'company_name': 'Accounting Test SRL', 'rnc': '131880681', 'role': 'collaborator', 'permissions': user_data.get('permissions', {}), 'company': company_doc}))
        stack.enter_context(patch("app.services.accounting_service.AccountingService.seed_default_accounts", return_value=None))
        stack.enter_context(patch("app.services.accounting_service.AccountingService.seed_default_entry_types", return_value=None))
        stack.enter_context(patch("app.services.accounting_service.AccountingService.get_accounts_tree", return_value=(dummy_tree, dummy_accounts)))
        stack.enter_context(patch("app.services.accounting_service.AccountingService.get_balance_sheet", return_value=dummy_balance))
        stack.enter_context(patch("app.services.accounting_service.AccountingService.get_income_statement", return_value=dummy_income))
        stack.enter_context(patch("app.services.accounting_service.AccountingService.get_trial_balance", return_value=dummy_trial))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_accounting_entries", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_chart_of_accounts", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_entry_types", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_fixed_assets", return_value=[]))
        stack.enter_context(patch("app.services.fixed_asset_service.FixedAssetService.get_assets_summary", return_value={"totalCost": 0.0, "totalDepreciation": 0.0, "netBookValue": 0.0, "totalCurrentValue": 0.0, "count": 0}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_cost_centers", return_value=[]))
        stack.enter_context(patch("app.services.fiscal_period_service.FiscalPeriodService.list_periods", return_value=[]))

        with client.session_transaction() as sess:
            sess["user"] = user_data
            sess["company_modules"] = _setup_company_modules()
            sess["selected_company_id"] = "comp_acc123"
            sess["selected_owner_uid"] = "owner_acc123"
            sess["company_plan_id"] = "plan_test"

        # 1. Dashboard (/accounting)
        assert client.get("/accounting").status_code == 403
        user_data["permissions"]["canAccountingDashboard"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/accounting").status_code == 200

        # Graceful redirect: user has canAccountingDashboard=False but canAccountingReports=True
        user_data["permissions"]["canAccountingDashboard"] = False
        user_data["permissions"]["canAccountingReports"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        resp = client.get("/accounting")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/accounting/balance-sheet")

        # 2. Chart of Accounts (/accounting/chart-of-accounts)
        user_data["permissions"]["canAccountingReports"] = False
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/accounting/chart-of-accounts").status_code == 403
        user_data["permissions"]["canAccountingChart"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/accounting/chart-of-accounts").status_code == 200

        # 3. Journal Entries (/accounting/journal-entries)
        assert client.get("/accounting/journal-entries").status_code == 403
        user_data["permissions"]["canAccountingJournal"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/accounting/journal-entries").status_code == 200

        # 4. Reports (/accounting/balance-sheet)
        assert client.get("/accounting/balance-sheet").status_code == 403
        user_data["permissions"]["canAccountingReports"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/accounting/balance-sheet").status_code == 200

        # 5. Fixed Assets (/accounting/fixed-assets)
        assert client.get("/accounting/fixed-assets").status_code == 403
        user_data["permissions"]["canAccountingFixedAssets"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/accounting/fixed-assets").status_code == 200

        # 6. Fiscal Periods (/accounting/fiscal-periods)
        assert client.get("/accounting/fiscal-periods").status_code == 403
        user_data["permissions"]["canAccountingFiscalPeriods"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/accounting/fiscal-periods").status_code == 200

        # 7. Cost Centers (/accounting/cost-centers)
        assert client.get("/accounting/cost-centers").status_code == 403
        user_data["permissions"]["canAccountingSettings"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/accounting/cost-centers").status_code == 200


def test_accounting_sidebar_gating(app):
    """Test that workspace sidebar sections render according to granular permissions."""
    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", return_value=True):
            # 1. Main sidebar (_sidebar_nav.html): Hidden when all accounting perms are False
            session["user"] = _setup_session({
                "canManageCXC": False,
                "canManageCXCAdvances": False,
                "canManageBanks": False,
                "canBankReconciliation": False,
                "canAccounting": False,
                "canAccountingDashboard": False,
                "canAccountingChart": False,
                "canAccountingJournal": False,
                "canAccountingReports": False,
                "canAccountingFixedAssets": False,
                "canAccountingFiscalPeriods": False,
                "canAccountingSettings": False,
            })
            session["company_modules"] = _setup_company_modules()
            rendered_main = render_template("_sidebar_nav.html")
            assert 'href="/accounting"' not in rendered_main

            # 2. Main sidebar (_sidebar_nav.html): Visible when ANY granular accounting perm is True
            session["user"] = _setup_session({
                "canManageCXC": False,
                "canManageCXCAdvances": False,
                "canManageBanks": False,
                "canBankReconciliation": False,
                "canAccounting": False,
                "canAccountingReports": True,
            })
            rendered_main = render_template("_sidebar_nav.html")
            assert 'href="/accounting"' in rendered_main

            # 3. Workspace sidebar (layout_accounting.html): Section gating
            session["user"] = _setup_session({
                "canAccounting": False,
                "canAccountingDashboard": False,
                "canAccountingChart": True,
                "canAccountingJournal": False,
                "canAccountingReports": False,
                "canAccountingFixedAssets": False,
                "canAccountingFiscalPeriods": False,
                "canAccountingSettings": False,
            })
            rendered_ws = render_template("accounting/layout_accounting.html")
            assert 'id="sidebar-section-acc-chart"' in rendered_ws
            assert 'id="sidebar-section-acc-dashboard"' not in rendered_ws
            assert 'id="sidebar-section-acc-reports"' not in rendered_ws
            assert 'id="sidebar-section-acc-assets"' not in rendered_ws
            assert 'id="sidebar-section-acc-fiscal"' not in rendered_ws
            assert 'id="sidebar-section-acc-settings"' not in rendered_ws


def test_accounting_landing_url_routing(app):
    """Test get_user_landing_url routing priority for each granular accounting permission."""
    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", side_effect=lambda mod: mod in ("contabilidad",)):
            session["company_modules"] = _setup_company_modules()

            base_perms = {
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
                "canBankReconciliation": False,
                "canAccounting": False,
                "canAccountingDashboard": False,
                "canAccountingChart": False,
                "canAccountingJournal": False,
                "canAccountingReports": False,
                "canAccountingFixedAssets": False,
                "canAccountingFiscalPeriods": False,
                "canAccountingSettings": False,
            }

            # 1. Dashboard
            p = dict(base_perms, canAccountingDashboard=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/accounting"

            # 2. Chart
            p = dict(base_perms, canAccountingChart=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/accounting/chart-of-accounts"

            # 3. Journal
            p = dict(base_perms, canAccountingJournal=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/accounting/journal-entries"

            # 4. Reports
            p = dict(base_perms, canAccountingReports=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/accounting/balance-sheet"

            # 5. Fixed Assets
            p = dict(base_perms, canAccountingFixedAssets=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/accounting/fixed-assets"

            # 6. Fiscal Periods
            p = dict(base_perms, canAccountingFiscalPeriods=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/accounting/fiscal-periods"

            # 7. Settings
            p = dict(base_perms, canAccountingSettings=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/accounting/cost-centers"
