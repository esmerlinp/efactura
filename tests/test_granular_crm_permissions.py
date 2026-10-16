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
        "uid": "test_subuser_crm",
        "email": "crm_user@example.com",
        "ownerUID": "owner_crm123",
        "company_id": "comp_crm123",
        "role": role,
        "permissions": perms,
    }


def _setup_company_modules():
    return {
        "crm": {"enabled": True},
        "comisiones": {"enabled": True},
    }


def test_granular_crm_permissions_logic(app):
    """Test check_permission logic, overrides, and fallbacks for CRM permissions."""
    with app.test_request_context("/"):
        # 1. Owner always has all CRM permissions
        session["user"] = _setup_session({}, role="owner")
        for key in (
            "canClients",
            "canCRM",
            "canCRMContacts",
            "canCRMOpportunities",
            "canCRMActivities",
            "canCRMReports",
            "canManageCommissions",
        ):
            assert check_permission(key) is True

        # 2. Explicit grants with legacy canClients=False
        session["user"] = _setup_session({"canClients": False, "canCRMOpportunities": True})
        assert check_permission("canCRMOpportunities") is True
        assert check_permission("canClients") is False

        session["user"] = _setup_session({"canClients": False, "canCRMActivities": True})
        assert check_permission("canCRMActivities") is True
        assert check_permission("canClients") is False

        session["user"] = _setup_session({"canClients": False, "canCRMContacts": True})
        assert check_permission("canCRMContacts") is True
        assert check_permission("canClients") is False

        session["user"] = _setup_session({"canClients": False, "canCRMReports": True})
        assert check_permission("canCRMReports") is True
        assert check_permission("canClients") is False

        # 3. Explicit denies take precedence over legacy canClients=True
        session["user"] = _setup_session({"canClients": True, "canCRMOpportunities": False})
        assert check_permission("canCRMOpportunities") is False
        assert check_permission("canClients") is True

        session["user"] = _setup_session({"canClients": True, "canCRMActivities": False})
        assert check_permission("canCRMActivities") is False

        session["user"] = _setup_session({"canClients": True, "canCRMContacts": False})
        assert check_permission("canCRMContacts") is False

        session["user"] = _setup_session({"canClients": True, "canCRMReports": False})
        assert check_permission("canCRMReports") is False

        # 4. Backward compatibility: fallback to canClients when granular keys absent
        session["user"] = _setup_session({"canClients": True})
        assert check_permission("canCRM") is True
        assert check_permission("canCRMContacts") is True
        assert check_permission("canCRMOpportunities") is True
        assert check_permission("canCRMActivities") is True
        assert check_permission("canCRMReports") is True

        session["user"] = _setup_session({"canClients": False})
        assert check_permission("canCRM") is False
        assert check_permission("canCRMContacts") is False
        assert check_permission("canCRMOpportunities") is False
        assert check_permission("canCRMActivities") is False
        assert check_permission("canCRMReports") is False


def test_crm_presets_matrix_and_permission_groups():
    """Verify ALL_PERMISSION_KEYS, PERMISSION_GROUPS, and ROLES_PRESETS for CRM y Contactos."""
    crm_keys = [
        "canCRM",
        "canCRMContacts",
        "canCRMOpportunities",
        "canCRMActivities",
        "canCRMReports",
    ]
    for key in crm_keys:
        assert key in ALL_PERMISSION_KEYS, f"{key} must be in ALL_PERMISSION_KEYS"

    # Dedicated "CRM y Contactos" group exists
    crm_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "CRM y Contactos"), None)
    assert crm_group is not None, "PERMISSION_GROUPS must have 'CRM y Contactos' group"
    group_perms = crm_group.get("perms", [])
    expected_group_perms = [
        "canCRM",
        "canCRMContacts",
        "canCRMOpportunities",
        "canCRMActivities",
        "canCRMReports",
        "canManageCommissions",
    ]
    for p in expected_group_perms:
        assert p in group_perms, f"{p} must be in 'CRM y Contactos' group"

    # Verify Ventas y Facturación contains canClients, canCreateClient, canDeleteClient
    ventas_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Ventas y Facturación"), None)
    assert ventas_group is not None
    assert "canClients" in ventas_group.get("perms", [])
    assert "canCreateClient" in ventas_group.get("perms", [])
    assert "canDeleteClient" in ventas_group.get("perms", [])
    assert "canClients" not in group_perms, "canClients should be in Ventas y Facturación, decoupled from CRM"

    # Verify Módulos Principales does NOT contain canClients
    main_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Módulos Principales"), None)
    assert main_group is not None
    assert "canClients" not in main_group.get("perms", [])

    # Verify Financiero / Finanzas y Tesorería does NOT contain canManageCommissions
    financiero_group = next((g for g in PERMISSION_GROUPS if g.get("name") in ("Financiero", "Finanzas y Tesorería")), None)
    assert financiero_group is not None
    assert "canManageCommissions" not in financiero_group.get("perms", [])

    # Role presets check
    for key in crm_keys:
        assert ROLES_PRESETS["administrador"][key] is True
        assert ROLES_PRESETS["consulta"][key] is False

    assert ROLES_PRESETS["vendedor"]["canCRM"] is True
    assert ROLES_PRESETS["vendedor"]["canCRMContacts"] is True
    assert ROLES_PRESETS["vendedor"]["canCRMOpportunities"] is True
    assert ROLES_PRESETS["vendedor"]["canCRMActivities"] is True
    assert ROLES_PRESETS["vendedor"]["canCRMReports"] is False
    assert ROLES_PRESETS["vendedor"]["canManageCommissions"] is True

    assert ROLES_PRESETS["contador"]["canCRM"] is False
    assert ROLES_PRESETS["contador"]["canCRMContacts"] is True
    assert ROLES_PRESETS["contador"]["canCRMOpportunities"] is False
    assert ROLES_PRESETS["contador"]["canCRMActivities"] is False
    assert ROLES_PRESETS["contador"]["canCRMReports"] is False
    assert ROLES_PRESETS["contador"]["canManageCommissions"] is False


def test_landing_url_for_granular_crm_permissions(app):
    """Verify get_user_landing_url lands on the specific active CRM sub-permission."""
    with app.test_request_context("/"):
        session["company_modules"] = _setup_company_modules()

        base_denied = {
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
            "canClients": False,
            "canCRM": False,
            "canCRMReports": False,
            "canCRMOpportunities": False,
            "canCRMActivities": False,
            "canCRMContacts": False,
            "canManageCommissions": False,
        }

        # 1. User with only canCRM or canCRMReports
        session["user"] = _setup_session({**base_denied, "canCRM": True})
        assert get_user_landing_url() == "/crm"

        session["user"] = _setup_session({**base_denied, "canCRMReports": True})
        assert get_user_landing_url() == "/crm"

        # 2. User with only canCRMOpportunities
        session["user"] = _setup_session({**base_denied, "canCRMOpportunities": True})
        assert get_user_landing_url() == "/crm/pipeline"

        # 3. User with only canCRMActivities
        session["user"] = _setup_session({**base_denied, "canCRMActivities": True})
        assert get_user_landing_url() == "/crm/activities"

        # 4. User with only canCRMContacts
        session["user"] = _setup_session({**base_denied, "canCRMContacts": True})
        assert get_user_landing_url() == "/contacts"

        # 5. User with only canManageCommissions
        session["user"] = _setup_session({**base_denied, "canManageCommissions": True})
        assert get_user_landing_url() == "/operations/commissions"


def test_sidebar_nav_crm_granular_rendering(app):
    """Test that sidebar hides the CRM section or renders only permitted items."""
    with app.test_request_context("/"):
        session["company_modules"] = _setup_company_modules()

        # User with NO CRM permissions -> CRM section NOT rendered
        session["user"] = _setup_session({
            "canClients": False,
            "canCRM": False,
            "canCRMReports": False,
            "canCRMOpportunities": False,
            "canCRMActivities": False,
            "canCRMContacts": False,
            "canManageCommissions": False,
        })
        rendered = render_template("_sidebar_nav.html")
        assert "sidebar-section-crm" not in rendered

        # User with ONLY canCRMOpportunities -> CRM section rendered, ONLY Pipeline visible
        session["user"] = _setup_session({
            "canClients": False,
            "canCRM": False,
            "canCRMReports": False,
            "canCRMOpportunities": True,
            "canCRMActivities": False,
            "canCRMContacts": False,
            "canManageCommissions": False,
        })
        rendered = render_template("_sidebar_nav.html")
        assert "sidebar-section-crm" in rendered
        assert "/crm/pipeline" in rendered
        assert "/crm/activities" not in rendered
        assert 'href="/contacts"' not in rendered
        assert "/operations/commissions" not in rendered

        # User with ONLY canCRMActivities -> ONLY Agenda visible
        session["user"] = _setup_session({
            "canClients": False,
            "canCRM": False,
            "canCRMReports": False,
            "canCRMOpportunities": False,
            "canCRMActivities": True,
            "canCRMContacts": False,
            "canManageCommissions": False,
        })
        rendered = render_template("_sidebar_nav.html")
        assert "sidebar-section-crm" in rendered
        assert "/crm/activities" in rendered
        assert "/crm/pipeline" not in rendered
        assert 'href="/contacts"' not in rendered

        # User with ONLY canManageCommissions -> ONLY Comisiones visible
        session["user"] = _setup_session({
            "canClients": False,
            "canCRM": False,
            "canCRMReports": False,
            "canCRMOpportunities": False,
            "canCRMActivities": False,
            "canCRMContacts": False,
            "canManageCommissions": True,
        })
        rendered = render_template("_sidebar_nav.html")
        assert "sidebar-section-crm" in rendered
        assert "/operations/commissions" in rendered
        assert "/crm/pipeline" not in rendered
        assert "/crm/activities" not in rendered


def test_endpoints_granular_http_guards(app, client):
    """Verify that HTTP endpoints fail closed (403) when lacking granular permissions, and succeed (200) when granted."""
    company_doc = {
        "id": "comp_crm123",
        "status": "Activo",
        "planId": "plan_test",
        "plan_id": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_crm123",
        "country": "DO",
        "configured": True,
        "pos_enabled": False,
        "production_enabled": True,
        "sandbox_enabled": True,
        "companyName": "CRM Test SRL",
        "companyRNC": "131880681",
    }
    user_data = _setup_session({
        "canClients": False,
        "canCRM": False,
        "canCRMReports": False,
        "canCRMOpportunities": False,
        "canCRMActivities": False,
        "canCRMContacts": False,
        "canManageCommissions": False,
        "canManageSuppliers": False,
    })

    crm_dashboard_mock = {
        'metrics': {},
        'salesMetrics': {
            'funnel': {},
            'conversionRates': {'prospect_to_contacted': 0, 'contacted_to_qualified': 0, 'qualified_to_proposal': 0, 'proposal_to_negotiation': 0, 'negotiation_to_won': 0},
            'pipelineVelocity': {},
            'revenueByRep': [],
            'winRate': 0,
            'avgDealSize': 0,
            'totalPipeline': 0,
            'wonPipeline': 0,
            'lostPipeline': 0,
            'wonCount': 0,
            'lostCount': 0,
        },
        'activities': []
    }

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': 'collaborator', 'permissions': user_data.get('permissions', {})}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'crm': {'enabled': True}, 'comisiones': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_crm123', 'owner_uid': 'owner_crm123', 'company_name': 'CRM Test SRL', 'rnc': '131880681', 'role': 'collaborator', 'permissions': user_data.get('permissions', {}), 'company': company_doc}), \
         patch("app.services.crm_service.CRMService.get_dashboard", return_value=crm_dashboard_mock), \
         patch("app.services.contact_service.ContactService.get_contacts", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_team_members", return_value=[]), \
         patch("app.services.crm_service.CRMService.get_opportunities", return_value=[]), \
         patch("app.services.crm_service.CRMService.get_activities", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_invoices", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_expenses", return_value=[]):

        # Initial session with all granular denied
        with client.session_transaction() as sess:
            sess["user"] = user_data
            sess["company_modules"] = _setup_company_modules()
            sess["selected_company_id"] = "comp_crm123"
            sess["selected_owner_uid"] = "owner_crm123"

        # 1. Dashboard CRM endpoint (/crm)
        assert client.get("/crm").status_code == 403
        user_data["permissions"]["canCRM"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/crm").status_code == 200

        # 2. Pipeline endpoint (/crm/pipeline)
        user_data["permissions"]["canCRM"] = False
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/crm/pipeline").status_code == 403
        user_data["permissions"]["canCRMOpportunities"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/crm/pipeline").status_code == 200

        # 3. Activities endpoint (/crm/activities)
        assert client.get("/crm/activities").status_code == 403
        user_data["permissions"]["canCRMActivities"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/crm/activities").status_code == 200

        # 4. Contacts endpoint (/contacts)
        assert client.get("/contacts").status_code == 403
        user_data["permissions"]["canCRMContacts"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/contacts").status_code == 200

        # 5. Contacts tab proveedores bypass with canManageSuppliers
        user_data["permissions"]["canCRMContacts"] = False
        user_data["permissions"]["canManageSuppliers"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/contacts?tab=proveedores").status_code == 200
        # But base /contacts is still 403
        assert client.get("/contacts").status_code == 403

        # 6. Commissions endpoint (/operations/commissions)
        assert client.get("/operations/commissions").status_code == 403
        user_data["permissions"]["canManageCommissions"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data
        assert client.get("/operations/commissions").status_code == 200
