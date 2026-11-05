"""Regression tests for the declarative navigation registry and resolver."""

from flask import render_template

from app.navigation.constants import (
    WORKSPACE_ACCOUNTING,
    WORKSPACE_GLOBAL,
    WORKSPACE_RRHH,
)
from app.navigation.registry import NAVIGATION_ITEMS
from app.navigation.resolver import resolve_navigation
from app.navigation.validators import validate_registry
from app.utils.module_gate import MODULE_MAP


def _all_ids(items=NAVIGATION_ITEMS):
    return [item.id for item in items]


def test_registry_is_structurally_valid():
    assert validate_registry(NAVIGATION_ITEMS, module_keys=set(MODULE_MAP))


def test_registry_endpoints_exist(app):
    assert validate_registry(
        NAVIGATION_ITEMS,
        app=app,
        strict_routes=True,
        module_keys=set(MODULE_MAP),
    )


def test_registry_ids_are_unique():
    ids = _all_ids()
    assert len(ids) == len(set(ids))


def test_groups_are_structural_containers():
    for item in NAVIGATION_ITEMS:
        if item.type == "group":
            assert item.route is None
            assert item.permission is None
            assert item.permission_any == ()
            assert item.module_key is None
            assert item.module_any == ()


def test_every_workspace_has_navigation():
    for workspace in (WORKSPACE_GLOBAL, WORKSPACE_RRHH, WORKSPACE_ACCOUNTING):
        tree = resolve_navigation(
            workspace,
            check_permission_fn=lambda _permission: True,
            module_enabled_fn=lambda _module: True,
        )
        assert tree


def test_hidden_permissions_collapse_empty_groups():
    tree = resolve_navigation(
        WORKSPACE_GLOBAL,
        check_permission_fn=lambda _permission: False,
        module_enabled_fn=lambda _module: True,
    )

    def flatten(nodes):
        for node in nodes:
            yield node
            yield from flatten(node["children"])

    ids = {node["id"] for node in flatten(tree)}
    assert "global.sales.invoices" not in ids
    assert "global.sales_customers" not in ids
    assert "global.settings" in ids
    assert not next(node for node in flatten(tree) if node["id"] == "global.settings")["children"]


def test_active_state_uses_endpoint_and_page():
    tree = resolve_navigation(
        WORKSPACE_ACCOUNTING,
        active_page="acc_balance_sheet",
        active_endpoint="web_accounting.balance_sheet",
        check_permission_fn=lambda _permission: True,
        module_enabled_fn=lambda _module: True,
    )

    def find(nodes, item_id):
        for node in nodes:
            if node["id"] == item_id:
                return node
            found = find(node["children"], item_id)
            if found:
                return found
        return None

    balance = find(tree, "accounting.accounting_reports.balance")
    reports_group = find(tree, "accounting.accounting_reports")
    assert balance["active"] is True
    assert reports_group["active_parent"] is True


def test_environment_restricted_item_is_hidden():
    tree = resolve_navigation(
        WORKSPACE_GLOBAL,
        environment="testecf",
        check_permission_fn=lambda _permission: True,
        module_enabled_fn=lambda _module: True,
    )

    def flatten(nodes):
        for node in nodes:
            yield node
            yield from flatten(node["children"])

    ids = {node["id"] for node in flatten(tree)}
    assert "global.settings.certification" not in ids


def test_sidebar_template_renders_all_workspaces(app):
    with app.test_request_context("/"):
        for workspace in (WORKSPACE_GLOBAL, WORKSPACE_RRHH, WORKSPACE_ACCOUNTING):
            tree = resolve_navigation(
                workspace,
                check_permission_fn=lambda _permission: True,
                module_enabled_fn=lambda _module: True,
                session_data={"company_profile_pos_enabled": True},
            )
            html = render_template("_navigation_sidebar.html", navigation_items=tree)
            assert "data-navigation-id=" in html
            assert "sidebar-section" in html
