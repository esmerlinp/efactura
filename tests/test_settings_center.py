"""Behavioral coverage for the global administration center."""

from pathlib import Path
from unittest.mock import patch

import pytest
from flask import render_template, session, url_for

from app.navigation.constants import SETTINGS_CATEGORIES
from app.navigation.resolver import resolve_navigation, resolve_settings_center
from app.web.invoices import settings_center
from config import Config


ALL_PERMISSIONS = {
    "canManageCompanySettings",
    "canManageTaxes",
    "canManageSequences",
    "canCertifyDGII",
    "canManageUsers",
    "canViewAuditLog",
    "canManageAPI",
    "canAccountingExport",
    "canModifySettings",
    "canAccounting",
    "canAccountingSettings",
    "canViewSystemJobs",
    "canExportData",
    "canViewSubscription",
}


def _resolve(permissions=ALL_PERMISSIONS, modules=None, environment="certecf"):
    enabled_modules = modules if modules is not None else {
        "certificacion", "auditoria", "api", "exportacion_contable", "contabilidad"
    }
    return resolve_settings_center(
        check_permission_fn=lambda permission: permission in permissions,
        module_enabled_fn=lambda module: module in enabled_modules,
        session_data={"selected_company_id": "company-1", "company_developers_enabled": True},
        environment=environment,
    )


def _items(categories):
    return [item for category in categories for item in category["items"]]


def _ids(categories):
    return {item["id"] for item in _items(categories)}


def test_settings_are_grouped_in_five_categories():
    categories = _resolve()
    assert [category["label"] for category in categories] == [
        category["label"] for category in SETTINGS_CATEGORIES
    ]
    assert len(_items(categories)) == 12


def test_settings_filter_by_commercial_module():
    ids = _ids(_resolve(modules={"contabilidad"}))
    assert "global.settings.alerts" in ids
    assert "global.settings.audit" not in ids
    assert "global.settings.jobs" not in ids
    assert "global.settings.api" not in ids
    assert "global.settings.accounting_export" not in ids
    assert "global.settings.certification" not in ids


def test_api_requires_company_developer_access():
    categories = resolve_settings_center(
        check_permission_fn=lambda permission: permission == "canManageAPI",
        module_enabled_fn=lambda module: module == "api",
        session_data={"selected_company_id": "company-1", "company_developers_enabled": False},
        environment="certecf",
    )
    assert "global.settings.api" not in _ids(categories)


def test_settings_filter_by_permission():
    ids = _ids(_resolve(permissions={"canManageUsers"}, modules=set()))
    assert ids == {"global.settings.users"}


def test_certification_requires_certecf_on_each_resolution():
    assert "global.settings.certification" in _ids(_resolve(environment="certecf"))
    assert "global.settings.certification" not in _ids(_resolve(environment="testecf"))
    assert "global.settings.certification" not in _ids(_resolve(environment="ecf"))


def test_audit_and_jobs_keep_separate_permissions():
    audit_ids = _ids(_resolve(permissions={"canViewAuditLog"}, modules={"auditoria"}))
    jobs_ids = _ids(_resolve(permissions={"canViewSystemJobs"}, modules={"auditoria"}))
    assert audit_ids == {"global.settings.audit"}
    assert jobs_ids == {"global.settings.jobs"}


@pytest.mark.parametrize(
    "permission",
    ("canManageTaxes", "canModifySettings", "canAccounting", "canAccountingSettings"),
)
def test_alerts_accept_all_existing_backend_permissions(permission):
    ids = _ids(_resolve(permissions={permission}, modules={"contabilidad"}))
    assert "global.settings.alerts" in ids


def test_search_text_contains_name_description_category_and_terms():
    company = next(item for item in _items(_resolve()) if item["id"] == "global.settings.company")
    assert "configuracion de empresa" in company["search_text"]
    assert "datos legales" in company["search_text"]
    assert "empresa y fiscalidad" in company["search_text"]
    assert "rnc" in company["search_text"]


def test_every_settings_route_remains_original_and_unique(app):
    categories = _resolve()
    items = _items(categories)
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids))
    with app.test_request_context("/"):
        for item in items:
            if item["route"]:
                assert url_for(item["route"], **item["route_params"])


def test_export_modal_and_subscription_secondary_access_render_once(app):
    with app.test_request_context("/settings"):
        session["user"] = {"role": "owner", "permissions": {}}
        session["selected_company_id"] = "company-1"
        session["company_modules"] = {
            key: {"enabled": True}
            for key in ("certificacion", "auditoria", "api", "exportacion_contable", "contabilidad")
        }
        html = render_template(
            "settings/index.html",
            active_page="settings_center",
            settings_categories=_resolve(),
            global_plan_name="Plan Empresa",
        )
        assert 'data-settings-action="export-data"' in html
        assert html.count('id="global-export-modal"') == 1
        subscription_url = url_for("web_invoices.client_subscription_page")
        assert html.count(f'href="{subscription_url}"') >= 2


def test_global_sidebar_has_one_settings_entry_and_workspaces_keep_specialized_settings():
    allow = lambda _value: True
    global_tree = resolve_navigation(
        "global",
        check_permission_fn=allow,
        module_enabled_fn=allow,
        environment="certecf",
        session_data={"company_developers_enabled": True},
    )
    settings = next(item for item in global_tree if item["id"] == "global.settings")
    assert settings["route"] == "web_invoices.settings_center"
    assert len(settings["children"]) == 12

    rrhh = resolve_navigation("rrhh", check_permission_fn=allow, module_enabled_fn=allow)
    accounting = resolve_navigation("accounting", check_permission_fn=allow, module_enabled_fn=allow)
    assert any(item["id"] == "rrhh.admin" for item in rrhh)
    assert any(item["id"] == "accounting.settings" for item in accounting)

    root = Path(__file__).resolve().parents[1]
    assert '_sidebar_config.html' not in (root / "templates/rrhh/layout_hr.html").read_text()
    assert '_sidebar_config.html' not in (root / "templates/accounting/layout_accounting.html").read_text()


def test_company_module_and_environment_changes_do_not_leak_state():
    first = _ids(_resolve(modules={"api"}, environment="certecf"))
    second = _ids(_resolve(modules={"auditoria"}, environment="ecf"))
    assert "global.settings.api" in first
    assert "global.settings.api" not in second
    assert "global.settings.audit" not in first
    assert "global.settings.audit" in second
    assert "global.settings.certification" not in second


def test_settings_controller_resolves_current_company_and_environment(app):
    with app.test_request_context("/settings"):
        session["user"] = {
            "uid": "owner-1",
            "ownerUID": "owner-1",
            "role": "owner",
            "permissions": {},
        }
        session["selected_company_id"] = "company-1"
        session["is_sandbox_mode"] = False
        with patch("app.web.invoices.resolve_settings_center", return_value=[]) as resolver:
            html = settings_center()

        assert "No hay configuraciones disponibles" in html
        assert resolver.call_args.kwargs["session_data"] is session
        assert resolver.call_args.kwargs["environment"] == Config.DGII_ENVIRONMENT_PRODUCTION


def test_settings_controller_requires_active_company(app):
    with app.test_request_context("/settings"):
        session["user"] = {"uid": "user-1", "role": "member", "permissions": {}}
        response = settings_center()
        assert response.status_code == 302
        assert "/select-company" in response.location
