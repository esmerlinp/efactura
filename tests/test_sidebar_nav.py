"""Regresión del rediseño del Sidebar principal (_sidebar_nav.html + _sidebar_config.html).

Verifica que:
1. Un módulo no contratado NO aparezca en el Sidebar.
2. Un usuario sin permiso NO vea la opción correspondiente.
3. No existan enlaces duplicados (dedup de Facturación ↔ Facturas de Venta).
4. Las 25 claves canónicas y el enforcement de entitlement/RBAC permanezcan intactos.
"""
from flask import session, render_template


def test_sidebar_nav_renders_only_entitled_modules(app):
    """Solo e_cf contratado: únicamente deben aparecer los ítems de e_cf + fijos."""
    with app.test_request_context():
        session.clear()
        session['user'] = {'role': 'owner', 'email': 'owner@test.com', 'permissions': {}}
        session['company_modules'] = {
            'e_cf': {'enabled': True},
            'nomina': {'enabled': False},
            'contabilidad': {'enabled': False},
            'pos': {'enabled': False},
            'banks': {'enabled': False},
            'crm': {'enabled': False},
            'cxc': {'enabled': False},
            'inventario': {'enabled': False},
            'catalogo': {'enabled': False},
            'ia_bi': {'enabled': False},
            'portal_cliente': {'enabled': False},
            'certificacion': {'enabled': False},
            'auditoria': {'enabled': False},
            'api': {'enabled': False},
            'exportacion_contable': {'enabled': False},
        }
        session['company_profile_pos_enabled'] = True

        html = render_template('_sidebar_nav.html')

        # e_cf contratado → Facturación Electrónica visible
        assert 'Facturación Electrónica' in html
        assert 'Inicio' in html
        assert 'Reportes y Análisis' in html

        # Módulos no contratados → ocultos
        assert 'Nómina y RRHH' not in html
        assert 'Contabilidad' not in html
        assert 'Punto de Venta (POS)' not in html
        assert 'Portal de Clientes' not in html
        assert 'Inteligencia de Negocio (BI)' not in html
        assert 'Cuentas por Cobrar' not in html
        assert 'Tablero de Inventario' not in html
        assert 'Bancos y Cajas' not in html

        # Configuración de módulos no contratados → ocultas
        assert 'Certificación DGII' not in html
        assert 'API y Desarrolladores' not in html
        assert 'Auditoría' not in html
        assert 'Exportación Contable' not in html


def test_sidebar_nav_user_without_permission_cannot_see_option(app):
    """Miembro sin canInvoice no debe ver Facturación Electrónica aunque e_cf esté contratado."""
    with app.test_request_context():
        session.clear()
        session['user'] = {'role': 'member', 'email': 'm@test.com', 'permissions': {'canInvoice': False}}
        session['company_modules'] = {'e_cf': {'enabled': True}}
        session['company_profile_pos_enabled'] = True

        html = render_template('_sidebar_nav.html')
        assert 'Facturación Electrónica' not in html


def test_sidebar_nav_no_duplicate_links(app):
    """El rediseño no debe producir enlaces duplicados (dedup Facturación)."""
    all_mods = {k: {'enabled': True} for k in [
        'e_cf', 'dashboard', 'catalogo', 'cotizaciones', 'crm', 'pos',
        'price_lists', 'inventario', 'contratos', 'comisiones', 'cxc',
        'cxp_compras', 'gastos', 'banks', 'contabilidad', 'nomina',
        'reporte_606', 'certificacion', 'api', 'multi_empresa',
        'portal_cliente', 'ia_bi', 'auditoria', 'exportacion_contable',
        'pasarela_azul',
    ]}
    with app.test_request_context():
        session.clear()
        session['user'] = {'role': 'owner', 'email': 'owner@test.com', 'permissions': {}}
        session['company_modules'] = all_mods
        session['company_profile_pos_enabled'] = True

        html = render_template('_sidebar_nav.html')

        from flask import url_for as _url_for
        # list_invoices solo debe aparecer una vez (dedup Facturación ↔ Facturas de Venta)
        invoices_url = _url_for('web_invoices.list_invoices')
        assert html.count(f'href="{invoices_url}"') == 1, f"list_invoices duplicado: {invoices_url}"
        company_url = _url_for('web_invoices.company_settings')
        assert html.count(f'href="{company_url}"') == 1, f"company_settings duplicado: {company_url}"
        tax_url = _url_for('web_invoices.tax_settings')
        assert html.count(f'href="{tax_url}"') == 1, f"tax_settings duplicado: {tax_url}"


def test_canonical_catalog_intact(app):
    """Las 25 claves canónicas y su enforcement permanecen intactos."""
    from app.utils.module_gate import MODULE_DEFS, MODULE_MAP
    assert len(MODULE_DEFS) == 25
    assert len(MODULE_MAP) == 25
    expected = {
        "e_cf", "dashboard", "catalogo", "cotizaciones", "crm",
        "pos", "price_lists", "inventario", "contratos", "comisiones",
        "cxc", "cxp_compras", "gastos", "banks", "contabilidad",
        "nomina", "reporte_606", "certificacion", "api", "multi_empresa",
        "portal_cliente", "ia_bi", "auditoria", "exportacion_contable", "pasarela_azul"
    }
    assert set(MODULE_MAP.keys()) == expected
