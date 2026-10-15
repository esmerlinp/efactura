import pytest
from flask import session, render_template
from unittest.mock import patch, MagicMock
from app import create_app
from app.utils.decorators import check_permission, get_user_landing_url
from app.web.invoices import ALL_PERMISSION_KEYS, ROLES_PRESETS, PERMISSION_GROUPS
from app.services.db_service import DatabaseService


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
        "uid": "test_subuser_sys",
        "name": "Sys User",
        "email": "sys_user@example.com",
        "ownerUID": "owner_sys123",
        "company_id": "comp_sys123",
        "role": role,
        "permissions": perms,
    }


def test_permission_registry_and_presets():
    """Verify registration, presets, and groups for Configuración y Sistema (Fase 5)."""
    expected_keys = [
        "canManageCompanySettings",
        "canManageTaxes",
        "canManageUsers",
        "canManageSequences",
        "canCertifyDGII",
        "canViewSystemJobs",
        "canExportData",
    ]
    for k in expected_keys:
        assert k in ALL_PERMISSION_KEYS, f"{k} must be in ALL_PERMISSION_KEYS"

    # Presets
    for role in ("vendedor", "contador", "consulta"):
        assert role in ROLES_PRESETS

    # Vendedor
    assert ROLES_PRESETS["vendedor"].get("canManageCompanySettings") is False
    assert ROLES_PRESETS["vendedor"].get("canManageTaxes") is False
    assert ROLES_PRESETS["vendedor"].get("canManageUsers") is False
    assert ROLES_PRESETS["vendedor"].get("canManageSequences") is False
    assert ROLES_PRESETS["vendedor"].get("canCertifyDGII") is False
    assert ROLES_PRESETS["vendedor"].get("canViewSystemJobs") is False
    assert ROLES_PRESETS["vendedor"].get("canExportData") is False

    # Contador
    assert ROLES_PRESETS["contador"].get("canManageCompanySettings") is False
    assert ROLES_PRESETS["contador"].get("canManageTaxes") is True
    assert ROLES_PRESETS["contador"].get("canManageUsers") is False
    assert ROLES_PRESETS["contador"].get("canManageSequences") is True
    assert ROLES_PRESETS["contador"].get("canCertifyDGII") is False
    assert ROLES_PRESETS["contador"].get("canViewSystemJobs") is False
    assert ROLES_PRESETS["contador"].get("canExportData") is True

    # Consulta
    assert ROLES_PRESETS["consulta"].get("canManageCompanySettings") is False
    assert ROLES_PRESETS["consulta"].get("canManageTaxes") is False
    assert ROLES_PRESETS["consulta"].get("canManageUsers") is False
    assert ROLES_PRESETS["consulta"].get("canManageSequences") is False
    assert ROLES_PRESETS["consulta"].get("canCertifyDGII") is False
    assert ROLES_PRESETS["consulta"].get("canViewSystemJobs") is False
    assert ROLES_PRESETS["consulta"].get("canExportData") is False

    # Dedicated groups
    group_cfg = next((g for g in PERMISSION_GROUPS if g["name"] == "Configuración y Empresa"), None)
    assert group_cfg is not None, "Configuración y Empresa group must exist"
    assert "canManageCompanySettings" in group_cfg["perms"]
    assert "canManageTaxes" in group_cfg["perms"]
    assert "canManageUsers" in group_cfg["perms"]
    assert "canManageSequences" in group_cfg["perms"]
    assert "canCertifyDGII" in group_cfg["perms"]
    assert "canExportData" in group_cfg["perms"]
    assert "canViewSubscription" in group_cfg["perms"]

    group_sys = next((g for g in PERMISSION_GROUPS if g["name"] == "Sistema y Auditoría"), None)
    assert group_sys is not None, "Sistema y Auditoría group must exist"
    assert "canViewAuditLog" in group_sys["perms"]
    assert "canViewSystemJobs" in group_sys["perms"]


def test_permission_resolution_and_fallbacks(app):
    """Test check_permission logic, overrides, and fallbacks for Fase 5."""
    with app.test_request_context("/"):
        # 1. Owner always has permissions
        session["user"] = _setup_session({}, role="owner")
        assert check_permission("canManageCompanySettings") is True
        assert check_permission("canManageTaxes") is True
        assert check_permission("canManageUsers") is True
        assert check_permission("canManageSequences") is True
        assert check_permission("canCertifyDGII") is True
        assert check_permission("canViewSystemJobs") is True
        assert check_permission("canExportData") is True

        # 2. Explicit grants
        session["user"] = _setup_session({
            "canManageCompanySettings": True,
            "canManageTaxes": True,
            "canManageUsers": False,
            "canManageSequences": False,
            "canCertifyDGII": True,
            "canViewSystemJobs": True,
            "canExportData": False,
        })
        assert check_permission("canManageCompanySettings") is True
        assert check_permission("canManageTaxes") is True
        assert check_permission("canManageUsers") is False
        assert check_permission("canManageSequences") is False
        assert check_permission("canCertifyDGII") is True
        assert check_permission("canViewSystemJobs") is True
        assert check_permission("canExportData") is False

        # 3. Explicit deny overrides legacy canModifySettings
        session["user"] = _setup_session({
            "canModifySettings": True,
            "canManageCompanySettings": False,
            "canManageTaxes": False,
            "canManageUsers": False,
            "canManageSequences": False,
            "canCertifyDGII": False,
            "canExportData": False,
        })
        assert check_permission("canManageCompanySettings") is False
        assert check_permission("canManageTaxes") is False
        assert check_permission("canManageUsers") is False
        assert check_permission("canManageSequences") is False
        assert check_permission("canCertifyDGII") is False
        assert check_permission("canExportData") is False

        # 4. Fallback inheritance from canModifySettings
        session["user"] = _setup_session({"canModifySettings": True})
        assert check_permission("canManageCompanySettings") is True
        assert check_permission("canManageTaxes") is True
        assert check_permission("canManageUsers") is True
        assert check_permission("canManageSequences") is True
        assert check_permission("canCertifyDGII") is True
        assert check_permission("canExportData") is True
        assert check_permission("canViewSystemJobs") is True

        session["user"] = _setup_session({"canModifySettings": False})
        assert check_permission("canManageCompanySettings") is False
        assert check_permission("canManageTaxes") is False
        assert check_permission("canManageUsers") is False
        assert check_permission("canManageSequences") is False
        assert check_permission("canCertifyDGII") is False
        assert check_permission("canExportData") is False
        assert check_permission("canViewSystemJobs") is False

        # 5. Default resolution when empty (fail-closed for users/jobs/audit)
        session["user"] = _setup_session({})
        assert check_permission("canManageUsers") is False
        assert check_permission("canViewSystemJobs") is False
        assert check_permission("canViewAuditLog") is False

        # 6. canViewSystemJobs inherits from canViewAuditLog
        session["user"] = _setup_session({"canViewAuditLog": True})
        assert check_permission("canViewSystemJobs") is True


def test_routes_fail_closed_and_granted(client, app):
    """Test route enforcement for Configuración, Impuestos, Secuencias, Usuarios, Jobs, Certificación y Exportación."""
    company_doc = {
        'id': 'comp_sys123',
        'owner_uid': 'owner_sys123',
        'company_name': 'Test Co',
        'companyName': 'Test Co',
        'rnc': '123456789',
        'country': 'DO',
        'plan_id': 'plan_test',
        'planId': 'plan_test',
        'plan_version': 1,
        'status': 'active',
        'configured': True,
    }
    from app.countries.do.tax_rules import DEFAULT_TAX_RULES
    with patch("app.services.db_service.DatabaseService.get_user_profile") as mock_profile, \
         patch("app.services.db_service.DatabaseService.get_membership") as mock_membership, \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc) as mock_company_doc, \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc) as mock_company, \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'e_cf': {'enabled': True}, 'auditoria': {'enabled': True}, 'certificacion': {'enabled': True}}}) as mock_plan, \
         patch("app.services.db_service.DatabaseService.get_company_context", side_effect=lambda uid, cid: {'company_id': 'comp_sys123', 'owner_uid': 'owner_sys123', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'collaborator', 'permissions': session.get('user', {}).get('permissions', {}), 'company': company_doc}) as mock_ctx, \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]) as mock_branches, \
         patch("app.services.db_service.DatabaseService.get_sequences", return_value=[]) as mock_seqs, \
         patch("app.services.db_service.DatabaseService.get_sequence_logs", return_value=[]) as mock_seq_logs, \
         patch("app.services.db_service.DatabaseService.get_cancellations", return_value=[]) as mock_cancels, \
         patch("app.services.db_service.DatabaseService.get_team_members", return_value=[]) as mock_team, \
         patch("app.services.db_service.DatabaseService.get_tax_rules", return_value=DEFAULT_TAX_RULES) as mock_tax_rules, \
         patch("app.services.job_service.JobService.list_runs", return_value=[]) as mock_jobs, \
         patch("app.services.job_service.JobService.scheduler_jobs", return_value=[]) as mock_sched:

        mock_profile.side_effect = lambda uid, **kw: session.get("user", {})
        mock_membership.return_value = {"role": "collaborator", "status": "active"}

        # A. Sequences route (/sequences)
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageSequences": False, "canModifySettings": False})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/sequences")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageSequences": True})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/sequences")
        assert resp.status_code == 200

        # B. Tax Settings route (/settings/taxes)
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageTaxes": False, "canModifySettings": False})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/settings/taxes")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageTaxes": True})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/settings/taxes")
        assert resp.status_code == 200

        # C. Company Settings route (/settings/company)
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageCompanySettings": False, "canModifySettings": False})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/settings/company")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageCompanySettings": True})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/settings/company")
        assert resp.status_code == 200

        # D. Team Settings route (/settings/team)
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageUsers": False, "canModifySettings": False})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/settings/team", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/dashboard")

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageUsers": True})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/settings/team")
        assert resp.status_code == 200

        # E. System Jobs (/admin/jobs)
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canViewSystemJobs": False, "canModifySettings": False, "canViewAuditLog": False})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/admin/jobs")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canViewSystemJobs": True})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/admin/jobs")
        assert resp.status_code == 200

        # F. Certificación DGII (/certificacion)
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canCertifyDGII": False, "canModifySettings": False})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/certificacion")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canCertifyDGII": True})
            sess["selected_company_id"] = "comp_sys123"
        with patch("app.services.dgii_cert_service.DgiiCertService.get_process", return_value={"current_step": 1}):
            resp = client.get("/certificacion", follow_redirects=False)
            assert resp.status_code == 302
            assert "/certificacion/paso/1" in resp.headers["Location"]

        # G. Export company data (/settings/company/export)
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canExportData": False, "canModifySettings": False})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.post("/settings/company/export", data={"sections": ["invoices"]})
        assert resp.status_code == 403

        # H. Audit route (/audit)
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canViewAuditLog": False})
            sess["selected_company_id"] = "comp_sys123"
        resp = client.get("/audit")
        assert resp.status_code == 403

        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canViewAuditLog": True})
            sess["selected_company_id"] = "comp_sys123"
        with patch("app.services.audit_service.AuditService.get_logs", return_value={"logs": [], "total": 0, "pages": 0, "current_page": 1}):
            resp = client.get("/audit")
            assert resp.status_code == 200


def test_landing_url_system_and_config(app):
    """Test get_user_landing_url prioritization for Fase 5 permissions."""
    base_no_perms = {k: False for k in ALL_PERMISSION_KEYS}

    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", return_value=True):
            # Audit Log
            p = dict(base_no_perms, canViewAuditLog=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/audit"

            # System Jobs
            p = dict(base_no_perms, canViewSystemJobs=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/admin/jobs"

            # Certificación DGII
            p = dict(base_no_perms, canCertifyDGII=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/certificacion"

            # Company Settings
            p = dict(base_no_perms, canManageCompanySettings=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/settings/company"

            # Tax Settings
            p = dict(base_no_perms, canManageTaxes=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/settings/taxes"

            # Sequences
            p = dict(base_no_perms, canManageSequences=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/sequences"

            # Team Settings
            p = dict(base_no_perms, canManageUsers=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/settings/team"

            # Subscription
            p = dict(base_no_perms, canViewSubscription=True)
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/suscripcion"


def test_sidebar_config_rendering(app):
    """Test that _sidebar_config.html conditionally renders according to granular permissions."""
    with app.test_request_context("/"):
        # User with ONLY canManageTaxes
        session["user"] = _setup_session({
            "canManageTaxes": True,
            "canManageCompanySettings": False,
            "canManageUsers": False,
            "canManageSequences": False,
            "canCertifyDGII": False,
            "canViewAuditLog": False,
            "canViewSystemJobs": False,
            "canExportData": False,
            "canViewSubscription": False,
            "canAccountingExport": False,
            "canManageAPI": False,
        })
        rendered = render_template("_sidebar_config.html", active_page="", dgii_environment="certecf")
        assert "Impuestos" in rendered
        assert "Configuración de Empresa" not in rendered
        assert "Usuarios y Permisos" not in rendered
        assert "Secuencias Fiscales" not in rendered
        assert "Auditoría" not in rendered
        assert "Jobs y Procesos" not in rendered

        # User with ONLY canManageUsers
        session["user"] = _setup_session({
            "canManageTaxes": False,
            "canManageCompanySettings": False,
            "canManageUsers": True,
            "canManageSequences": False,
            "canCertifyDGII": False,
            "canViewAuditLog": False,
            "canViewSystemJobs": False,
            "canExportData": False,
            "canViewSubscription": False,
            "canAccountingExport": False,
            "canManageAPI": False,
        })
        rendered = render_template("_sidebar_config.html", active_page="", dgii_environment="certecf")
        assert "Usuarios y Permisos" in rendered
        assert "Impuestos" not in rendered
        assert "Configuración de Empresa" not in rendered
        assert "Secuencias Fiscales" not in rendered
