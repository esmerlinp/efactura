"""Control de acceso del Reporte 609 — module-gate e_cf + permiso + aislamiento.

Regla de negocio: 609 exige obligatoriamente el módulo e_cf (como 607/608/623/
IR-17). Tener gastos o cxp_compras sin e_cf NO habilita el reporte. Además exige
el permiso canReportsFiscal y el país DO. Aplica igual a /reports/609 y a
/reports/609/export (navegación normal y URL directa).
"""

from unittest.mock import patch

import pytest

from app import create_app
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


@pytest.fixture(autouse=True)
def _mock_before_request_reads(app):
    """Evita que el before_request global redirija por usuario sin perfil en Firestore."""
    from flask import session as flask_session

    def _profile(uid):
        user = flask_session.get("user") or {}
        p = {
            "uid": uid or user.get("uid", ""),
            "ownerUID": user.get("ownerUID", "") or user.get("uid", ""),
            "email": user.get("email", ""),
            "role": user.get("role", "employee"),
            "permissions": dict(user.get("permissions") or {}),
        }
        cid = flask_session.get("selected_company_id") or user.get("company_id")
        if cid:
            p["default_company_id"] = cid
        return p

    def _membership(uid, company_id):
        user = flask_session.get("user") or {}
        return {
            "uid": uid,
            "company_id": company_id,
            "role": user.get("role", "employee"),
            "permissions": dict(user.get("permissions") or {}),
            "status": "active",
        }

    def _company(company_id):
        return {
            "id": company_id,
            "owner_uid": "o1",
            "status": "active",
            "plan_id": "plan-test",
            "plan_version": 1,
            "rnc": "132109122",
            "company_name": "Test Co",
            "country": "DO",
            "configured": True,
        }

    def _ctx(uid, company_id):
        user = flask_session.get("user") or {}
        return {
            "company_id": company_id,
            "owner_uid": user.get("ownerUID", "") or user.get("uid", ""),
            "role": user.get("role", "employee"),
            "permissions": dict(user.get("permissions") or {}),
            "company_name": "Test Co",
            "rnc": "132109122",
            "plan_name": "Plan Activo",
            "billing_type": "Pago por uso",
        }

    import app as app_package
    from app.services import company_context as company_context_module

    with patch.object(app_package, "get_current_company", return_value=None), \
         patch.object(company_context_module, "get_current_company", return_value=None), \
         patch.object(DatabaseService, "get_user_profile", side_effect=_profile), \
         patch.object(DatabaseService, "get_membership", side_effect=_membership), \
         patch.object(DatabaseService, "get_company", side_effect=_company), \
         patch.object(DatabaseService, "get_company_context", side_effect=_ctx), \
         patch.object(DatabaseService, "get_company_profile", return_value={"companyRnc": "132109122"}), \
         patch.object(DatabaseService, "get_plan", return_value={"name": "Plan Activo", "plan_version": 1}), \
         patch.object(DatabaseService, "get_branches", return_value=[]), \
         patch.object(DatabaseService, "get_default_branch", return_value=None), \
         patch.object(DatabaseService, "get_projects", return_value=[]), \
         patch.object(DatabaseService, "get_user_companies", return_value=[]):
        yield


def _login(client, *, can_reports_fiscal, modules, company_id="comp-a"):
    with client.session_transaction() as sess:
        sess["user"] = {
            "uid": "u1",
            "ownerUID": "o1",
            "role": "employee",
            "email": "u@x.com",
            "permissions": {"canReportsFiscal": can_reports_fiscal},
        }
        sess["selected_company_id"] = company_id
        sess["selected_owner_uid"] = "o1"
        sess["company_country"] = "DO"
        sess["is_sandbox_mode"] = True
        sess["company_modules"] = modules
        sess["company_report_groups"] = {}
        # Evita que el before_request rederive company_modules desde el plan
        sess["company_plan_id"] = "plan-test"
        sess["company_plan_version"] = 1


def _mod(module_key, enabled):
    return {module_key: {"enabled": enabled}}


class TestModuleGate:
    def test_allowed_with_fiscal_group_via_e_cf(self, client):
        _login(client, can_reports_fiscal=True, modules=_mod("e_cf", True))
        assert client.get("/reports/609").status_code == 200

    def test_export_allowed_with_e_cf(self, client):
        _login(client, can_reports_fiscal=True, modules=_mod("e_cf", True))
        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", return_value=[]):
            resp = client.get("/reports/609/export")
        # Pasa el gate (no 403); sin documentos redirige con aviso.
        assert resp.status_code != 403

    def test_denied_without_any_module(self, client):
        _login(client, can_reports_fiscal=True, modules={})
        assert client.get("/reports/609").status_code == 403
        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", return_value=[]):
            assert client.get("/reports/609/export").status_code == 403

    def test_denied_without_permission(self, client):
        _login(client, can_reports_fiscal=False, modules=_mod("e_cf", True))
        assert client.get("/reports/609").status_code == 403
        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", return_value=[]):
            assert client.get("/reports/609/export").status_code == 403

    def test_gastos_without_e_cf_denied(self, client):
        # Decisión de negocio: 609 exige e_cf (gastos sin e_cf NO habilita).
        _login(client, can_reports_fiscal=True, modules=_mod("gastos", True))
        assert client.get("/reports/609").status_code == 403

    def test_cxp_without_e_cf_denied(self, client):
        _login(client, can_reports_fiscal=True, modules=_mod("cxp_compras", True))
        assert client.get("/reports/609").status_code == 403
        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", return_value=[]):
            assert client.get("/reports/609/export").status_code == 403


class TestCompanyIsolation:
    def test_export_scopes_to_session_company(self, client):
        _login(client, can_reports_fiscal=True, modules=_mod("e_cf", True), company_id="comp-a")
        captured = {}

        def _fake_get_all(owner_uid=None, sandbox=True, company_id=None, **kwargs):
            captured["company_id"] = company_id
            return []

        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", side_effect=_fake_get_all):
            client.get("/reports/609/export")

        assert captured["company_id"] == "comp-a"

    def test_status_and_export_same_restriction(self, client):
        # Sin módulo, ambas rutas responden 403 (misma restricción).
        _login(client, can_reports_fiscal=True, modules={})
        assert client.get("/reports/609").status_code == 403
        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", return_value=[]):
            assert client.get("/reports/609/export").status_code == 403
