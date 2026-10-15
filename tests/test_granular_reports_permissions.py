import pytest
from flask import session
from unittest.mock import patch
from app import create_app
from app.utils.decorators import check_permission, get_user_landing_url


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


def _setup_session(app, permissions_dict=None, role="collaborator"):
    perms = permissions_dict if permissions_dict is not None else {}
    return {
        "uid": "test_user_123",
        "email": "user@example.com",
        "ownerUID": "owner_123",
        "role": role,
        "permissions": perms,
    }


def test_granular_reports_permissions_logic(app):
    with app.test_request_context("/"):
        # 1. Owner always has all reports and admin permissions
        session["user"] = _setup_session(app, {}, role="owner")
        for key in (
            "canReportsSales",
            "canReportsAdmin",
            "canReportsFinancial",
            "canReportsAccounting",
            "canReportsFiscal",
            "canReportsHR",
            "canReports",
            "canAccountingExport",
            "canManageAPI",
        ):
            assert check_permission(key) is True

        # 2. Explicit grants
        session["user"] = _setup_session(app, {"canReportsSales": True})
        assert check_permission("canReportsSales") is True
        assert check_permission("canReports") is True

        session["user"] = _setup_session(app, {"canReportsFiscal": True})
        assert check_permission("canReportsFiscal") is True
        assert check_permission("canReports") is True

        session["user"] = _setup_session(app, {"canAccountingExport": True})
        assert check_permission("canAccountingExport") is True
        assert check_permission("canManageAPI") is False

        session["user"] = _setup_session(app, {"canManageAPI": True})
        assert check_permission("canManageAPI") is True
        assert check_permission("canAccountingExport") is False

        # 3. Explicit denies take precedence
        session["user"] = _setup_session(app, {"canInvoice": True, "canReportsSales": False})
        assert check_permission("canReportsSales") is False

        session["user"] = _setup_session(app, {"canAccounting": True, "canReportsAccounting": False})
        assert check_permission("canReportsAccounting") is False

        session["user"] = _setup_session(app, {"canHR": True, "canReportsHR": False})
        assert check_permission("canReportsHR") is False

        # 4. User with ONLY canInvoice and canInventoryCounts CANNOT access reports, accounting export, or API
        session["user"] = _setup_session(app, {"canInvoice": True, "canInventoryCounts": True})
        assert check_permission("canReportsSales") is False
        assert check_permission("canReportsAdmin") is False
        assert check_permission("canReportsFinancial") is False
        assert check_permission("canReportsAccounting") is False
        assert check_permission("canReportsFiscal") is False
        assert check_permission("canReportsHR") is False
        assert check_permission("canReports") is False
        assert check_permission("canAccountingExport") is False
        assert check_permission("canManageAPI") is False

        # 5. Backward compatibility for legacy profiles with explicit canReports=True
        session["user"] = _setup_session(app, {"canReports": True})
        assert check_permission("canReports") is True
        assert check_permission("canReportsSales") is True
        assert check_permission("canReportsFiscal") is True


def test_reports_presets_matrix_and_permission_groups():
    from app.web.invoices import ALL_PERMISSION_KEYS, ROLES_PRESETS, PERMISSION_GROUPS

    new_keys = [
        "canReportsSales",
        "canReportsAdmin",
        "canReportsFinancial",
        "canReportsAccounting",
        "canReportsFiscal",
        "canReportsHR",
        "canAccountingExport",
        "canManageAPI",
    ]

    for key in new_keys:
        assert key in ALL_PERMISSION_KEYS, f"{key} should be in ALL_PERMISSION_KEYS"

    # Presets check
    for key in ("canReportsSales", "canReportsAdmin", "canReportsFinancial", "canReportsAccounting", "canReportsFiscal", "canReportsHR"):
        assert ROLES_PRESETS["administrador"][key] is True
        assert ROLES_PRESETS["contador"][key] is True

    assert ROLES_PRESETS["administrador"]["canAccountingExport"] is True
    assert ROLES_PRESETS["administrador"]["canManageAPI"] is True
    assert ROLES_PRESETS["contador"]["canAccountingExport"] is True
    assert ROLES_PRESETS["contador"]["canManageAPI"] is False

    assert ROLES_PRESETS["vendedor"]["canReportsSales"] is True
    assert ROLES_PRESETS["vendedor"]["canReportsAccounting"] is False
    assert ROLES_PRESETS["vendedor"]["canAccountingExport"] is False
    assert ROLES_PRESETS["vendedor"]["canManageAPI"] is False

    assert ROLES_PRESETS["consulta"]["canReportsSales"] is True
    assert ROLES_PRESETS["consulta"]["canReportsAccounting"] is False
    assert ROLES_PRESETS["consulta"]["canAccountingExport"] is False
    assert ROLES_PRESETS["consulta"]["canManageAPI"] is False

    # Permission groups check
    report_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Reportes y Análisis"), None)
    assert report_group is not None, "PERMISSION_GROUPS must have 'Reportes y Análisis'"
    group_perms = report_group.get("perms", [])
    for key in ("canReportsSales", "canReportsAdmin", "canReportsFinancial", "canReportsAccounting", "canReportsFiscal", "canReportsHR", "canAccountingExport"):
        assert key in group_perms, f"{key} must be in Reportes y Análisis permission group"
    assert "canViewBI" in group_perms

    admin_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Administración"), None)
    assert admin_group is not None, "PERMISSION_GROUPS must have 'Administración'"
    assert "canManageAPI" in admin_group.get("perms", [])


def test_reports_dashboard_filtering_by_category(app, client):
    from app.web.invoices import get_report_categories

    with app.test_request_context("/reports"):
        # User with only sales permission
        session["user"] = _setup_session(app, {
            "canReportsSales": True,
            "canReportsAdmin": False,
            "canReportsFinancial": False,
            "canReportsAccounting": False,
            "canReportsFiscal": False,
            "canReportsHR": False,
        })
        cats = get_report_categories()
        cat_keys = [c["key"] for c in cats]
        assert "ventas" in cat_keys
        assert "administrativos" not in cat_keys
        assert "financieros" not in cat_keys
        assert "contables" not in cat_keys
        assert "fiscales" not in cat_keys
        assert "nomina" not in cat_keys
        assert "empleados" not in cat_keys

        # User with only fiscal permission
        session["user"] = _setup_session(app, {
            "canReportsSales": False,
            "canReportsAdmin": False,
            "canReportsFinancial": False,
            "canReportsAccounting": False,
            "canReportsFiscal": True,
            "canReportsHR": False,
        })
        cats = get_report_categories()
        cat_keys = [c["key"] for c in cats]
        assert "fiscales" in cat_keys
        assert "ventas" not in cat_keys
        assert "contables" not in cat_keys


def test_reports_category_access_control(app, client):
    user_data = _setup_session(app, {
        "canReportsSales": True,
        "canReportsAdmin": False,
        "canReportsFiscal": False,
    })
    company_doc = {
        "id": "comp_123",
        "status": "Activo",
        "planId": "plan_test",
        "companyPlanId": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_123",
        "country": "DO",
        "companyName": "Test Co",
        "companyRNC": "123456789",
        "configured": True,
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["selected_company_id"] = "comp_123"
        sess["selected_owner_uid"] = "owner_123"
        sess["company_country"] = "DO"
        sess["company_plan_id"] = "plan_test"
        sess["company_plan_version"] = 1
        sess["is_sandbox_mode"] = True
        sess["company_modules"] = {'e_cf': {'enabled': True}}

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value={'status': 'active', 'role': 'collaborator', 'permissions': user_data['permissions']}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'e_cf': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value={'company_id': 'comp_123', 'owner_uid': 'owner_123', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'collaborator', 'permissions': user_data['permissions'], 'company': company_doc}):

        # Accessing sales category should succeed (200)
        resp = client.get("/reports/categoria/ventas")
        assert resp.status_code == 200

        # Accessing fiscal category should be blocked (403)
        resp = client.get("/reports/categoria/fiscales")
        assert resp.status_code == 403


def test_http_route_protection_for_reports(app, client):
    user_data = _setup_session(app, {
        "canReportsSales": False,
        "canReportsAdmin": False,
        "canReportsFinancial": False,
        "canReportsAccounting": False,
        "canReportsFiscal": False,
        "canReportsHR": False,
        "canInvoice": False,
        "canExpenses": False,
        "canAccounting": False,
    })
    company_doc = {
        "id": "comp_123",
        "status": "Activo",
        "planId": "plan_test",
        "companyPlanId": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_123",
        "country": "DO",
        "companyName": "Test Co",
        "companyRNC": "123456789",
        "configured": True,
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["selected_company_id"] = "comp_123"
        sess["selected_owner_uid"] = "owner_123"
        sess["company_country"] = "DO"
        sess["company_plan_id"] = "plan_test"
        sess["company_plan_version"] = 1
        sess["is_sandbox_mode"] = True
        sess["company_modules"] = {'e_cf': {'enabled': True}}

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': 'collaborator', 'permissions': user_data.get('permissions', {})}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'e_cf': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_123', 'owner_uid': 'owner_123', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'collaborator', 'permissions': user_data.get('permissions', {}), 'company': company_doc}):

        assert client.get("/reports/ventas").status_code == 403
        assert client.get("/reports/admin/ingresos-compras").status_code == 403
        assert client.get("/reports/financial/cash-flow").status_code == 403
        assert client.get("/reports/fiscal/it1").status_code == 403
        assert client.get("/reports/606").status_code == 403
        assert client.get("/reports/607").status_code == 403
        assert client.get("/reports/608").status_code == 403
        assert client.get("/reports/623").status_code == 403

        # Now grant only canReportsSales
        user_data["permissions"]["canReportsSales"] = True
        with client.session_transaction() as sess:
            sess["user"] = user_data

        with patch("app.services.db_service.DatabaseService.get_invoices", return_value=[]):
            res_v = client.get("/reports/ventas")
            assert res_v.status_code == 200
            assert client.get("/reports/606").status_code == 403


def test_user_with_only_report_permission_landing(app):
    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", return_value=True):
            base_denied = {
                "canViewDashboard": False,
                "canInvoice": False,
                "canManageFiscalNotes": False,
                "canManagePOS": False,
                "canManageRUI": False,
                "canManageQuotations": False,
                "canClients": False,
                "canCRM": False,
                "canCRMContacts": False,
                "canCRMOpportunities": False,
                "canManageCatalog": False,
                "canViewInventoryDashboard": False,
                "canManageInventory": False,
                "canManagePriceLists": False,
                "canExpenses": False,
                "canManageSuppliers": False,
                "canCreateSupplier": False,
                "canManageCXP": False,
                "canManagePurchaseCXP": False,
                "canManageCXC": False,
                "canBanks": False,
                "canAccounting": False,
                "canHR": False,
                "canManageContracts": False,
                "canManageCommissions": False,
                "canViewBI": False,
                "canViewAuditLog": False,
                "canReportsSales": False,
                "canReportsAdmin": False,
                "canReportsFinancial": False,
                "canReportsAccounting": False,
                "canReportsFiscal": False,
                "canReportsHR": False,
                "canReports": False,
                "canModifySettings": False,
                "canAccountingExport": False,
                "canManageAPI": False,
            }

            sales_only = dict(base_denied)
            del sales_only["canReports"]
            sales_only["canReportsSales"] = True
            session["user"] = _setup_session(app, sales_only)
            landing = get_user_landing_url()
            assert landing == "/reports"

            export_only = dict(base_denied)
            export_only["canAccountingExport"] = True
            session["user"] = _setup_session(app, export_only)
            assert get_user_landing_url() == "/reports/export/accounting"

            api_only = dict(base_denied)
            api_only["canManageAPI"] = True
            session["user"] = _setup_session(app, api_only)
            assert get_user_landing_url() == "/desarrolladores"


def test_user_with_only_invoicing_and_inventory_counts_has_no_reports_access(app, client):
    """Verifica que un usuario que sólo tiene cotejado Facturación Electrónica (canInvoice)
    y Conteo de Inventario (canInventoryCounts) NO pueda acceder a ningún reporte ni ver Reportes en sidebar."""
    user_data = _setup_session(app, {
        "canInvoice": True,
        "canInventoryCounts": True,
        "canManageInventory": False,
        "canReportsSales": False,
        "canReportsAdmin": False,
        "canReportsFinancial": False,
        "canReportsAccounting": False,
        "canReportsFiscal": False,
        "canReportsHR": False,
        "canViewBI": False,
    })
    company_doc = {
        "id": "comp_123",
        "status": "Activo",
        "planId": "plan_test",
        "companyPlanId": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_123",
        "country": "DO",
        "companyName": "Test Co",
        "companyRNC": "123456789",
        "configured": True,
    }

    with client.session_transaction() as sess:
        sess["user"] = user_data
        sess["selected_company_id"] = "comp_123"
        sess["selected_owner_uid"] = "owner_123"
        sess["company_country"] = "DO"
        sess["company_plan_id"] = "plan_test"
        sess["company_plan_version"] = 1
        sess["is_sandbox_mode"] = True
        sess["company_modules"] = {'e_cf': {'enabled': True}, 'inventario': {'enabled': True}}

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_data), \
         patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': 'collaborator', 'permissions': user_data.get('permissions', {})}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'e_cf': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_123', 'owner_uid': 'owner_123', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'collaborator', 'permissions': user_data.get('permissions', {}), 'company': company_doc}):

        # Sidebar no debe mostrar la sección de Reportes
        res_dash = client.get("/dashboard")
        assert res_dash.status_code == 200
        assert b'id="sidebar-section-reports"' not in res_dash.data

        # Todas las rutas de reportes deben retornar 403 Forbidden
        assert client.get("/reports").status_code == 403
        assert client.get("/reports/categoria/ventas").status_code == 403
        assert client.get("/reports/categoria/fiscales").status_code == 403
        assert client.get("/reports/ventas").status_code == 403
        assert client.get("/reports/admin/ingresos-compras").status_code == 403
        assert client.get("/reports/financial/cash-flow").status_code == 403
        assert client.get("/reports/fiscal/it1").status_code == 403
        assert client.get("/reports/606").status_code == 403
        assert client.get("/reports/607").status_code == 403
        assert client.get("/reports/608").status_code == 403
        assert client.get("/reports/623").status_code == 403


def test_accounting_export_and_api_granular_permissions(app, client):
    """Verifica que canAccountingExport y canManageAPI protejan efectivamente
    sus rutas HTTP, tarjetas en dashboard de reportes y enlaces en sidebar."""
    company_doc = {
        "id": "comp_123",
        "status": "Activo",
        "planId": "plan_test",
        "companyPlanId": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_123",
        "country": "DO",
        "companyName": "Test Co",
        "companyRNC": "123456789",
        "configured": True,
        "developersEnabled": True,
    }

    # 1. Usuario SIN permisos
    user_no_perms = _setup_session(app, {
        "canAccountingExport": False,
        "canManageAPI": False,
        "canReportsAccounting": True,  # Tiene contables pero NO exportacion
    })

    with client.session_transaction() as sess:
        sess["user"] = user_no_perms
        sess["selected_company_id"] = "comp_123"
        sess["selected_owner_uid"] = "owner_123"
        sess["company_country"] = "DO"
        sess["company_plan_id"] = "plan_test"
        sess["company_plan_version"] = 1
        sess["is_sandbox_mode"] = True
        sess["company_modules"] = {
            'exportacion_contable': {'enabled': True},
            'api': {'enabled': True},
            'contabilidad': {'enabled': True},
        }

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_no_perms), \
         patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': 'collaborator', 'permissions': user_no_perms.get('permissions', {})}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'exportacion_contable': {'enabled': True}, 'api': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_123', 'owner_uid': 'owner_123', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'collaborator', 'permissions': user_no_perms.get('permissions', {}), 'company': company_doc}):

        # Accounting export denegado
        assert client.get("/reports/export/accounting").status_code == 403
        assert client.post("/reports/export/accounting/download").status_code == 403

        # API denegada
        assert client.get("/desarrolladores").status_code == 403
        assert client.get("/desarrolladores/docs").status_code == 403

        # En categoria contables no debe salir el link habilitado de Exportación contable
        res_cat = client.get("/reports/categoria/contables")
        assert res_cat.status_code == 200
        assert b'href="/reports/export/accounting"' not in res_cat.data

        # En sidebar no deben salir
        res_dash = client.get("/dashboard")
        assert res_dash.status_code == 200
        assert b'data-tooltip="Exportaci\xc3\xb3n Contable"' not in res_dash.data
        assert b'data-tooltip="API y Desarrolladores"' not in res_dash.data

    # 2. Usuario CON canAccountingExport y canManageAPI
    user_with_perms = _setup_session(app, {
        "canAccountingExport": True,
        "canManageAPI": True,
        "canReportsAccounting": True,
    })

    with client.session_transaction() as sess:
        sess["user"] = user_with_perms
        sess["selected_company_id"] = "comp_123"
        sess["selected_owner_uid"] = "owner_123"
        sess["company_country"] = "DO"
        sess["company_plan_id"] = "plan_test"
        sess["company_plan_version"] = 1
        sess["is_sandbox_mode"] = True
        sess["company_modules"] = {
            'exportacion_contable': {'enabled': True},
            'api': {'enabled': True},
            'contabilidad': {'enabled': True},
        }

    with patch("app.utils.module_gate.module_enabled", return_value=True), \
         patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_with_perms), \
         patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': 'collaborator', 'permissions': user_with_perms.get('permissions', {})}), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'exportacion_contable': {'enabled': True}, 'api': {'enabled': True}}}), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_default_branch", return_value=None), \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_123', 'owner_uid': 'owner_123', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'collaborator', 'permissions': user_with_perms.get('permissions', {}), 'company': company_doc}):

        # Rutas accesibles con 200
        assert client.get("/reports/export/accounting").status_code == 200
        assert client.get("/desarrolladores").status_code == 200
        assert client.get("/desarrolladores/docs").status_code == 200

        # En categoria contables sí aparece la tarjeta
        res_cat = client.get("/reports/categoria/contables")
        assert res_cat.status_code == 200
        assert b"Exportaci\xc3\xb3n contable" in res_cat.data

        # En sidebar sí aparecen los links
        res_dash = client.get("/dashboard")
        assert res_dash.status_code == 200
        assert b'data-tooltip="Exportaci\xc3\xb3n Contable"' in res_dash.data
        assert b'data-tooltip="API y Desarrolladores"' in res_dash.data

