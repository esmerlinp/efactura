import pytest
from flask import session, render_template
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
from app import create_app
from app.utils.decorators import check_permission, get_user_landing_url
from app.web.invoices import ALL_PERMISSION_KEYS, ROLES_PRESETS, PERMISSION_GROUPS, resolve_permissions
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
        "uid": "test_subuser_ops",
        "email": "ops_user@example.com",
        "ownerUID": "owner_ops123",
        "company_id": "comp_ops123",
        "role": role,
        "permissions": perms,
    }


def test_permission_registry_and_presets():
    """Verify registration, presets, and groups for Operaciones y Portal."""
    assert "canManageContracts" in ALL_PERMISSION_KEYS
    assert "canManageClientPortal" in ALL_PERMISSION_KEYS

    # Presets
    for role in ("vendedor", "contador", "consulta"):
        assert role in ROLES_PRESETS
        assert ROLES_PRESETS[role].get("canManageContracts") is False
        assert ROLES_PRESETS[role].get("canManageClientPortal") is False

    # Dedicated group
    group = next((g for g in PERMISSION_GROUPS if g["name"] == "Operaciones y Portal"), None)
    assert group is not None, "Operaciones y Portal group must exist in PERMISSION_GROUPS"
    assert "canManageContracts" in group["perms"]
    assert "canManageClientPortal" in group["perms"]
    assert "canManageContracts" in group["labels"]
    assert "canManageClientPortal" in group["labels"]

    # Verify not present in Finanzas y Tesorería
    fin_group = next((g for g in PERMISSION_GROUPS if g["name"] == "Finanzas y Tesorería"), None)
    assert fin_group is not None
    assert "canManageContracts" not in fin_group["perms"]


def test_permission_resolution_and_fallbacks(app):
    """Test check_permission logic, overrides, and fallbacks for Operaciones y Portal."""
    with app.test_request_context("/"):
        # 1. Owner always has permissions
        session["user"] = _setup_session({}, role="owner")
        assert check_permission("canManageContracts") is True
        assert check_permission("canManageClientPortal") is True

        # 2. Explicit grants
        session["user"] = _setup_session({"canManageContracts": True, "canManageClientPortal": False})
        assert check_permission("canManageContracts") is True
        assert check_permission("canManageClientPortal") is False

        session["user"] = _setup_session({"canManageContracts": False, "canManageClientPortal": True})
        assert check_permission("canManageContracts") is False
        assert check_permission("canManageClientPortal") is True

        # 3. Explicit deny takes precedence over legacy parents
        session["user"] = _setup_session({
            "canClients": True,
            "canModifySettings": True,
            "canManageClientPortal": False
        })
        assert check_permission("canManageClientPortal") is False

        # 4. Fallback inheritance from canClients
        session["user"] = _setup_session({"canClients": True})
        assert check_permission("canManageClientPortal") is True

        session["user"] = _setup_session({"canClients": False})
        assert check_permission("canManageClientPortal") is False

        # 5. Fallback inheritance from canModifySettings when canClients not provided
        session["user"] = _setup_session({"canModifySettings": True})
        assert check_permission("canManageClientPortal") is True

        session["user"] = _setup_session({"canModifySettings": False})
        assert check_permission("canManageClientPortal") is False


def test_resolve_permissions_with_overrides():
    """Verify resolve_permissions applies presets and overrides for new keys."""
    # Vendedor preset has False by default
    perms_vendedor = resolve_permissions("vendedor")
    assert perms_vendedor["canManageContracts"] is False
    assert perms_vendedor["canManageClientPortal"] is False

    # Overrides work
    overrides = {"canManageContracts": True, "canManageClientPortal": True}
    perms_custom = resolve_permissions("vendedor", overrides)
    assert perms_custom["canManageContracts"] is True
    assert perms_custom["canManageClientPortal"] is True


def test_landing_routing(app):
    """Verify landing URL routing for Contracts and Client Portal."""
    base_negative = {k: False for k in ALL_PERMISSION_KEYS}

    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", return_value=True):
            # 1. Contracts permission only
            p = dict(base_negative)
            p["canManageContracts"] = True
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/operations/contracts"

            # 2. Portal permission only
            p = dict(base_negative)
            p["canManageClientPortal"] = True
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/portal/admin"

            # 3. Both enabled: Contracts has priority over Portal in the sequence
            p = dict(base_negative)
            p["canManageContracts"] = True
            p["canManageClientPortal"] = True
            session["user"] = _setup_session(p)
            assert get_user_landing_url() == "/operations/contracts"


def test_contracts_endpoints_fail_closed(client):
    """Verify fail-closed security across contract endpoints."""
    company_doc = {
        "id": "comp_ops123",
        "status": "Activo",
        "planId": "plan_test",
        "owner_uid": "owner_ops123",
        "country": "DO",
        "configured": True,
        "production_enabled": True,
        "sandbox_enabled": True,
        "companyName": "Ops Test SRL",
        "companyRNC": "131880681",
    }

    with ExitStack() as stack:
        stack.enter_context(patch("app.utils.module_gate.module_enabled", return_value=True))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_user_profile", side_effect=lambda uid: session.get("user", {})))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {
            'status': 'active',
            'role': session.get("user", {}).get("role", "collaborator"),
            'permissions': session.get("user", {}).get("permissions", {})
        }))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_plan", return_value={"id": "pro", "modules": {"contratos": True, "portal_cliente": True}}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_contracts", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_clients", return_value=[]))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_items", return_value=[]))

        endpoints = [
            ("/operations/contracts", "GET"),
            ("/operations/contracts/new", "GET"),
        ]

        # Case 1: Without permission -> 403 Forbidden
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageContracts": False})
            sess["selected_company_id"] = "comp_ops123"

        for url, method in endpoints:
            if method == "GET":
                resp = client.get(url)
            assert resp.status_code == 403, f"Expected 403 for {url} without canManageContracts, got {resp.status_code}"

        # Case 2: With permission -> 200 OK
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageContracts": True})
            sess["selected_company_id"] = "comp_ops123"

        for url, method in endpoints:
            if method == "GET":
                resp = client.get(url)
            assert resp.status_code == 200, f"Expected 200 for {url} with canManageContracts, got {resp.status_code}"


def test_portal_admin_endpoint_fail_closed(client):
    """Verify fail-closed security for /portal/admin."""
    company_doc = {
        "id": "comp_ops123",
        "status": "Activo",
        "planId": "plan_test",
        "owner_uid": "owner_ops123",
        "country": "DO",
        "configured": True,
        "production_enabled": True,
        "sandbox_enabled": True,
        "companyName": "Ops Test SRL",
        "companyRNC": "131880681",
    }

    with ExitStack() as stack:
        stack.enter_context(patch("app.utils.module_gate.module_enabled", return_value=True))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_user_profile", side_effect=lambda uid: session.get("user", {})))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_membership", side_effect=lambda uid, cid: {
            'status': 'active',
            'role': session.get("user", {}).get("role", "collaborator"),
            'permissions': session.get("user", {}).get("permissions", {})
        }))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_plan", return_value={"id": "pro", "modules": {"portal_cliente": True}}))
        stack.enter_context(patch("app.services.db_service.DatabaseService.get_clients", return_value=[]))

        # 1. Without permission -> 403
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageClientPortal": False})
            sess["selected_company_id"] = "comp_ops123"

        resp = client.get("/portal/admin")
        assert resp.status_code == 403

        # 2. With explicit permission -> 200
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canManageClientPortal": True})
            sess["selected_company_id"] = "comp_ops123"

        resp = client.get("/portal/admin")
        assert resp.status_code == 200

        # 3. Fallback to canClients: True when canManageClientPortal omitted -> 200
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canClients": True})
            sess["selected_company_id"] = "comp_ops123"

        resp = client.get("/portal/admin")
        assert resp.status_code == 200

        # 4. Fallback to canClients: False when canManageClientPortal omitted -> 403
        with client.session_transaction() as sess:
            sess["user"] = _setup_session({"canClients": False})
            sess["selected_company_id"] = "comp_ops123"

        resp = client.get("/portal/admin")
        assert resp.status_code == 403


def test_sidebar_gating(app):
    """Verify contracts and portal sidebar sections are gated properly."""
    with app.test_request_context("/"):
        with patch("app.utils.module_gate.module_enabled", return_value=True):
            # Neither permission
            session["user"] = _setup_session({"canManageContracts": False, "canManageClientPortal": False})
            html = render_template("_sidebar_nav.html", active_page="dashboard")
            assert 'id="sidebar-section-contratos"' not in html
            assert 'id="sidebar-section-portal"' not in html

            # Only Contracts
            session["user"] = _setup_session({"canManageContracts": True, "canManageClientPortal": False})
            html = render_template("_sidebar_nav.html", active_page="dashboard")
            assert 'id="sidebar-section-contratos"' in html
            assert 'id="sidebar-section-portal"' not in html

            # Only Portal
            session["user"] = _setup_session({"canManageContracts": False, "canManageClientPortal": True})
            html = render_template("_sidebar_nav.html", active_page="dashboard")
            assert 'id="sidebar-section-contratos"' not in html
            assert 'id="sidebar-section-portal"' in html

            # Both
            session["user"] = _setup_session({"canManageContracts": True, "canManageClientPortal": True})
            html = render_template("_sidebar_nav.html", active_page="dashboard")
            assert 'id="sidebar-section-contratos"' in html
            assert 'id="sidebar-section-portal"' in html
