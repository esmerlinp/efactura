MODULE_DEFS = [
    {"key": "e_cf", "label": "Facturación Electrónica (e-CF)", "category": "core"},
    {"key": "dashboard", "label": "Dashboard & KPIs", "category": "core"},
    {"key": "catalogo", "label": "Catálogo de Productos", "category": "core"},
    {"key": "cotizaciones", "label": "Cotizaciones", "category": "ventas"},
    {"key": "crm", "label": "CRM & Agenda", "category": "ventas"},
    {"key": "pos", "label": "POS (Punto de Venta)", "category": "ventas"},
    {"key": "inventario", "label": "Inventario & Almacenes", "category": "logistica"},
    {"key": "cxc", "label": "Cuentas por Cobrar (CxC)", "category": "finanzas"},
    {"key": "cxp_compras", "label": "CxP, Proveedores & Compras", "category": "finanzas"},
    {"key": "gastos", "label": "Control de Gastos", "category": "finanzas"},
    {"key": "contratos", "label": "Contratos & Recurrencia", "category": "operaciones"},
    {"key": "comisiones", "label": "Comisiones & Metas", "category": "operaciones"},
    {"key": "reporte_606", "label": "Reporte 606", "category": "cumplimiento"},
    {"key": "api", "label": "API REST", "category": "integraciones"},
    {"key": "multi_empresa", "label": "Multi-Empresa", "category": "enterprise"},
    {"key": "portal_cliente", "label": "Portal del Cliente", "category": "enterprise"},
    {"key": "ia_bi", "label": "IA & Business Intelligence", "category": "enterprise"},
    {"key": "auditoria", "label": "Auditoría", "category": "enterprise"},
    {"key": "exportacion_contable", "label": "Exportación Contable", "category": "enterprise"},
    {"key": "pasarela_azul", "label": "Pasarela de Pago Azul", "category": "enterprise"},
    {"key": "price_lists", "label": "Listas de Precios", "category": "ventas"},
    {"key": "banks", "label": "Bancos & Conciliación", "category": "finanzas"},
]

def get_enabled_modules():
    """Retorna el dict de módulos habilitados desde la sesión."""
    from flask import session
    return session.get('company_modules', {})

def module_enabled(module_key):
    """Verifica si un módulo específico está habilitado para la empresa actual."""
    from flask import session
    modules = get_enabled_modules()
    if module_key in modules:
        return modules[module_key].get('enabled', False)
    if module_key == 'pos' and module_key not in modules:
        return session.get('company_profile_pos_enabled', True)
    if modules:
        return False
    return True

def require_module(module_key, feature_name=None):
    """Decorador para rutas que requieren un módulo habilitado."""
    from functools import wraps
    from flask import render_template

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not module_enabled(module_key):
                label = feature_name
                if not label:
                    for mod in MODULE_DEFS:
                        if mod["key"] == module_key:
                            label = mod["label"]
                            break
                    if not label:
                        label = module_key
                return render_template('auth/restricted.html',
                    feature_name=label,
                    required_permission=f"module_{module_key}",
                    custom_message=f"El módulo <strong>{label}</strong> no está incluido en tu plan actual. "
                                   "Contacta a soporte para información sobre mejoras de plan."
                )
            return f(*args, **kwargs)
        return decorated_function
    return decorator