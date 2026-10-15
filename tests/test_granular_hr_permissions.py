import pytest
from flask import session, render_template
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
from app import create_app
from app.utils.decorators import check_permission, get_user_landing_url
from app.web.invoices import ALL_PERMISSION_KEYS, ROLES_PRESETS, PERMISSION_GROUPS
from app.web.rrhh import _sanitize_for_role, _can_view_salary, _is_hr_role


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
        "uid": "test_subuser_hr",
        "email": "hr_user@example.com",
        "ownerUID": "owner_hr123",
        "company_id": "comp_hr123",
        "role": role,
        "permissions": perms,
    }


def _setup_company_modules():
    return {
        "nomina": {"enabled": True},
        "cxc": {"enabled": True},
        "banks": {"enabled": True},
    }


def test_granular_hr_permissions_logic(app):
    """Test check_permission logic, overrides, and fallbacks for HR permissions."""
    with app.test_request_context("/"):
        # 1. Owner always has all HR permissions
        session["user"] = _setup_session({}, role="owner")
        for key in (
            "canHR",
            "canHRDashboard",
            "canHREmployees",
            "canHRAttendance",
            "canHRVacations",
            "canHRPayroll",
            "canHROffboarding",
            "canHRAuthorizations",
            "canHRDevelopment",
            "canHRSettings",
        ):
            assert check_permission(key) is True

        # 2. Explicit grants with legacy parent False
        session["user"] = _setup_session({"canHR": False, "canHRDashboard": True})
        assert check_permission("canHRDashboard") is True
        assert check_permission("canHR") is False

        session["user"] = _setup_session({"canHR": False, "canHRPayroll": True})
        assert check_permission("canHRPayroll") is True
        assert check_permission("canHREmployees") is False

        # 3. Explicit denies take precedence over legacy parent True
        session["user"] = _setup_session({"canHR": True, "canHRPayroll": False, "canHRSettings": False})
        assert check_permission("canHRPayroll") is False
        assert check_permission("canHRSettings") is False
        assert check_permission("canHREmployees") is True
        assert check_permission("canHR") is True

        # 4. Fallback inheritance from canHR: True
        session["user"] = _setup_session({"canHR": True})
        for key in (
            "canHRDashboard",
            "canHREmployees",
            "canHRAttendance",
            "canHRVacations",
            "canHRPayroll",
            "canHROffboarding",
            "canHRAuthorizations",
            "canHRDevelopment",
            "canHRSettings",
        ):
            assert check_permission(key) is True

        # 5. Explicit deny of canHR denies all child permissions
        session["user"] = _setup_session({"canHR": False})
        for key in (
            "canHR",
            "canHRDashboard",
            "canHREmployees",
            "canHRAttendance",
            "canHRVacations",
            "canHRPayroll",
            "canHROffboarding",
            "canHRAuthorizations",
            "canHRDevelopment",
            "canHRSettings",
        ):
            assert check_permission(key) is False


def test_roles_presets_and_permission_groups():
    """Verify registration in ALL_PERMISSION_KEYS, ROLES_PRESETS, and PERMISSION_GROUPS."""
    hr_keys = [
        "canHR",
        "canHRDashboard",
        "canHREmployees",
        "canHRAttendance",
        "canHRVacations",
        "canHRPayroll",
        "canHROffboarding",
        "canHRAuthorizations",
        "canHRDevelopment",
        "canHRSettings",
    ]
    for k in hr_keys:
        assert k in ALL_PERMISSION_KEYS

    # Contador preset should have specific HR permissions
    contador_perms = ROLES_PRESETS["contador"]
    assert contador_perms.get("canHRDashboard") is True
    assert contador_perms.get("canHREmployees") is True
    assert contador_perms.get("canHRPayroll") is True
    assert contador_perms.get("canHROffboarding") is True
    assert contador_perms.get("canHRSettings") is True
    assert contador_perms.get("canHRAttendance") is False
    assert contador_perms.get("canHRVacations") is False
    assert contador_perms.get("canHRAuthorizations") is False

    # Vendedor preset should have all HR permissions False
    vendedor_perms = ROLES_PRESETS["vendedor"]
    for k in hr_keys:
        assert vendedor_perms.get(k) is False

    # Check PERMISSION_GROUPS structure
    hr_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Nómina y Recursos Humanos"), None)
    assert hr_group is not None
    group_perms = hr_group.get("perms", [])
    for k in hr_keys:
        assert k in group_perms

    # canHR should NOT be in Administración group
    admin_group = next((g for g in PERMISSION_GROUPS if g.get("name") == "Administración"), None)
    if admin_group:
        admin_perms = admin_group.get("perms", [])
        assert "canHR" not in admin_perms


def test_salary_and_bank_confidentiality_enmasking(app):
    """Verify that users without canHRPayroll or canHR see masked salary/bank info."""
    raw_employee = {
        "id": "emp_123",
        "firstName": "Juan",
        "lastName": "Pérez",
        "baseSalary": 50000.0,
        "salary": 50000.0,
        "hourlyRate": 312.5,
        "accountNumber": "1234567890",
        "bank": "Banco BHD",
        "accountType": "ahorros",
        "salaryType": "mensual",
        "afpProvider": "AFP Crecer",
        "afpSalaryCap": 350000.0,
        "sfsSalaryCap": 175000.0,
        "tssRegistrationNumber": "001-2345678-9",
    }

    with app.test_request_context("/"):
        # 1. User with canHRPayroll: False and canHR: False -> MASKED
        session["user"] = _setup_session({"canHR": False, "canHREmployees": True, "canHRPayroll": False})
        assert _can_view_salary() is False
        sanitized = _sanitize_for_role(raw_employee)
        assert sanitized["firstName"] == "Juan"
        assert sanitized["baseSalary"] == "***"
        assert sanitized["salary"] == "***"
        assert sanitized["hourlyRate"] == "***"
        assert sanitized["accountNumber"] == "***"
        assert sanitized["bank"] == "***"
        assert sanitized["afpProvider"] == "***"

        # 2. User with canHRPayroll: True -> UNMASKED
        session["user"] = _setup_session({"canHR": False, "canHRPayroll": True})
        assert _can_view_salary() is True
        sanitized = _sanitize_for_role(raw_employee)
        assert sanitized["baseSalary"] == 50000.0
        assert sanitized["accountNumber"] == "1234567890"

        # 3. User with legacy canHR: True -> UNMASKED
        session["user"] = _setup_session({"canHR": True})
        assert _can_view_salary() is True
        sanitized = _sanitize_for_role(raw_employee)
        assert sanitized["baseSalary"] == 50000.0

        # 4. Owner -> UNMASKED
        session["user"] = _setup_session({}, role="owner")
        assert _can_view_salary() is True
        sanitized = _sanitize_for_role(raw_employee)
        assert sanitized["baseSalary"] == 50000.0


def test_landing_routing(app):
    """Verify landing URL routing prioritizes HR granular permissions."""
    base_negative = {
        "canViewDashboard": False,
        "canInvoice": False,
        "canManageFiscalNotes": False,
        "canManageReceivedECF": False,
        "canManagePOS": False,
        "canManageRUI": False,
        "canManageQuotations": False,
        "canCRM": False,
        "canCRMReports": False,
        "canCRMOpportunities": False,
        "canCRMActivities": False,
        "canCRMContacts": False,
        "canClients": False,
        "canManageCatalog": False,
        "canViewInventoryDashboard": False,
        "canInventoryCounts": False,
        "canInventoryReceipts": False,
        "canInventoryTransfers": False,
        "canInventoryLots": False,
        "canInventoryKardex": False,
        "canManageWarehouses": False,
        "canInventoryAdjustments": False,
        "canManageInventory": False,
        "canManagePriceLists": False,
        "canExpenses": False,
        "canManageMinorExpenses": False,
        "canManageRecurringExpenses": False,
        "canManagePurchaseCXP": False,
        "canManagePurchaseOrders": False,
        "canManagePurchaseCreditNotes": False,
        "canManageSuppliers": False,
        "canCreateSupplier": False,
        "canManageCXP": False,
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
        "canHR": False,
        "canHRDashboard": False,
    }

    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", return_value=True):
            # Only Attendance
            p = dict(base_negative)
            p["canHRAttendance"] = True
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/rrhh/attendance"

            # Only Vacations
            p = dict(base_negative)
            p["canHRVacations"] = True
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/rrhh/vacations"

            # Only Employees
            p = dict(base_negative)
            p["canHREmployees"] = True
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/rrhh/employees"

            # Only Payroll
            p = dict(base_negative)
            p["canHRPayroll"] = True
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/rrhh/payroll/new"

            # Only Settings
            p = dict(base_negative)
            p["canHRSettings"] = True
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/rrhh/positions"


def test_hr_endpoints_fail_closed(client):
    """Verify fail-closed security across all granular HR routes."""
    company_doc = {
        "id": "comp_hr123",
        "status": "Activo",
        "planId": "plan_test",
        "plan_id": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_hr123",
        "country": "DO",
        "configured": True,
        "pos_enabled": False,
        "production_enabled": True,
        "sandbox_enabled": True,
        "companyName": "HR Test SRL",
        "companyRNC": "131880681",
    }

    with ExitStack() as stack:
        stack.enter_context(patch("app.utils.module_gate.module_enabled", return_value=True))
        stack.enter_context(patch("app.services.hr_data_service.get_employees", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_catalog", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_attendance_records", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_vacation_requests", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_leave_requests", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_payroll_periods", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_payroll_groups", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_payroll_config", return_value={}))
        stack.enter_context(patch("app.services.hr_data_service.get_tax_rates", return_value={}))
        stack.enter_context(patch("app.services.hr_data_service.get_legal_parameters", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_evaluations", return_value=[]))
        stack.enter_context(patch("app.services.hr_data_service.get_trainings", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_user_profile", side_effect=lambda uid: session.get("user", {})))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': session.get("user", {}).get("role", "collaborator"), 'permissions': session.get("user", {}).get("permissions", {})}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'nomina': {'enabled': True}}}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_hr123', 'owner_uid': 'owner_hr123', 'role': session.get("user", {}).get("role", "collaborator"), 'permissions': session.get("user", {}).get("permissions", {}), 'company': company_doc}))

        # --- 1. EMPLOYEES ---
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHREmployees": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_plan_id"] = "plan_test"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/employees")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHREmployees": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/employees")
        assert resp.status_code == 200

        # --- 2. ATTENDANCE ---
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRAttendance": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/attendance")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRAttendance": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/attendance")
        assert resp.status_code == 200

        # --- 3. VACATIONS & LEAVES ---
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRVacations": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/vacations")
        assert resp.status_code == 403
        resp = client.get("/rrhh/leaves")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRVacations": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/vacations")
        assert resp.status_code == 200
        resp = client.get("/rrhh/leaves")
        assert resp.status_code == 200

        # --- 4. PAYROLL ---
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRPayroll": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/payroll/new")
        assert resp.status_code == 403
        resp = client.get("/rrhh/payroll/history")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRPayroll": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/payroll/history")
        assert resp.status_code == 200

        # --- 5. OFFBOARDING ---
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHROffboarding": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/offboarding")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHROffboarding": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/offboarding")
        assert resp.status_code == 200

        # --- 6. AUTHORIZATIONS ---
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRAuthorizations": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/authorizations")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRAuthorizations": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/authorizations")
        assert resp.status_code == 200

        # --- 7. DEVELOPMENT (Evaluations & Trainings) ---
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRDevelopment": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/evaluations")
        assert resp.status_code == 403
        resp = client.get("/rrhh/trainings")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRDevelopment": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/evaluations")
        assert resp.status_code == 200
        resp = client.get("/rrhh/trainings")
        assert resp.status_code == 200

        # --- 8. SETTINGS (Positions, Departments, Concepts, Legal Parameters) ---
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRSettings": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/positions")
        assert resp.status_code == 403
        resp = client.get("/rrhh/departments")
        assert resp.status_code == 403
        resp = client.get("/rrhh/payroll/settings")
        assert resp.status_code == 403
        resp = client.get("/rrhh/legal-parameters")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRSettings": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/positions")
        assert resp.status_code == 200
        resp = client.get("/rrhh/departments")
        assert resp.status_code == 200
        resp = client.get("/rrhh/payroll/settings")
        assert resp.status_code == 200
        resp = client.get("/rrhh/legal-parameters")
        assert resp.status_code == 200


def test_dashboard_graceful_redirect(client):
    """Verify that visiting /rrhh/payroll/dashboard gracefully redirects if canHRDashboard is False."""
    company_doc = {
        "id": "comp_hr123",
        "status": "Activo",
        "planId": "plan_test",
        "plan_id": "plan_test",
        "plan_version": 1,
        "owner_uid": "owner_hr123",
        "country": "DO",
        "configured": True,
        "pos_enabled": False,
        "production_enabled": True,
        "sandbox_enabled": True,
        "companyName": "HR Test SRL",
        "companyRNC": "131880681",
    }
    with ExitStack() as stack:
        stack.enter_context(patch("app.utils.module_gate.module_enabled", return_value=True))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_user_profile", side_effect=lambda uid: session.get("user", {})))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {'status': 'active', 'role': session.get("user", {}).get("role", "collaborator"), 'permissions': session.get("user", {}).get("permissions", {})}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'nomina': {'enabled': True}}}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_hr123', 'owner_uid': 'owner_hr123', 'role': session.get("user", {}).get("role", "collaborator"), 'permissions': session.get("user", {}).get("permissions", {}), 'company': company_doc}))

        # User has canHRDashboard: False, but canHREmployees: True -> redirects to /rrhh/employees
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRDashboard": False, "canHREmployees": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/payroll/dashboard")
        assert resp.status_code == 302
        assert "/rrhh/employees" in resp.headers["Location"]

        # User has canHRDashboard: False, but canHRAttendance: True -> redirects to /rrhh/attendance
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRDashboard": False, "canHRAttendance": True})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/payroll/dashboard")
        assert resp.status_code == 302
        assert "/rrhh/attendance" in resp.headers["Location"]

        # User has no HR permissions at all -> redirects to landing URL or 403 restricted
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canHR": False, "canHRDashboard": False})
            sess["selected_company_id"] = "comp_hr123"
            sess["selected_owner_uid"] = "owner_hr123"
            sess["company_modules"] = _setup_company_modules()
        resp = client.get("/rrhh/payroll/dashboard")
        assert resp.status_code in (302, 403)
