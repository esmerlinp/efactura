import pytest


def test_import_web_accounting_and_render_rules_template(app):
    import app.web.accounting as wa  # noqa: F401
    from app.services.accounting_rules_service import AccountingRulesService

    accounts = [
        {"id": "a1", "code": "1.1.01", "name": "CxC", "usage": "cxc", "group": "activos",
         "type": "movimiento", "nature": "deudora", "isActive": True},
        {"id": "a2", "code": "4.1.01", "name": "Ventas", "usage": "ventas", "group": "ingresos",
         "type": "movimiento", "nature": "acreedora", "isActive": True},
        {"id": "a3", "code": "2.1.01", "name": "ITBIS por pagar", "usage": "itbis_pagar", "group": "pasivos",
         "type": "movimiento", "nature": "acreedora", "isActive": True},
        {"id": "a4", "code": "1.1.02", "name": "Caja", "usage": "efectivo", "group": "activos",
         "type": "movimiento", "nature": "deudora", "isActive": True},
        {"id": "a5", "code": "1.1.03", "name": "Banco", "usage": "banco", "group": "activos",
         "type": "movimiento", "nature": "deudora", "isActive": True},
    ]
    catalog = AccountingRulesService.build_catalog_view("company-x", accounts, rules=[])
    with app.test_request_context():
        html = app.jinja_env.get_template("accounting/accounting_rules.html").render(
            catalog=catalog, accounts=accounts, csrf_token=lambda: "tok",
            static_hash=lambda f: "v1", check_permission=lambda p: True,
            module_enabled=lambda m: True, abs=abs)
    assert "Factura de venta" in html
    assert "Nómina" in html
    assert "rule[venta|venta_deudor|pago_efectivo|]" in html


def test_chart_of_accounts_template_renders_with_usage(app):
    from app.services.accounting_rules_service import AccountingRulesService

    accounts = [
        {"id": "a1", "code": "1.1.01", "name": "CxC", "usage": "cxc", "group": "activos",
         "type": "movimiento", "nature": "deudora", "isActive": True},
    ]
    usage_labels = {"cxc": "Cuentas por cobrar", "efectivo": "Bancos tipo efectivo"}
    with app.test_request_context():
        html = app.jinja_env.get_template("accounting/chart_of_accounts.html").render(
            tree=[], accounts=accounts, flat_list=[], account_groups={},
            usage_labels=usage_labels, groups_json="{}", csrf_token=lambda: "tok",
            static_hash=lambda f: "v1", check_permission=lambda p: True,
            module_enabled=lambda m: True, abs=abs)
    assert "Uso de la cuenta" in html
    assert 'value="cxc"' in html
