"""Control de acceso y entitlements de módulos para VykOne (Fail-Closed)."""

MODULE_DEFS = [
    {"key": "e_cf", "label": "Facturación Electrónica (e-CF)", "category": "core", "perm": "canInvoice"},
    {"key": "dashboard", "label": "Dashboard & KPIs", "category": "core", "perm": None},
    {"key": "catalogo", "label": "Catálogo de Productos", "category": "core", "perm": "canManageInventory"},
    {"key": "cotizaciones", "label": "Cotizaciones", "category": "ventas", "perm": "canCreateQuotation"},
    {"key": "crm", "label": "CRM & Agenda", "category": "ventas", "perm": "canCRM"},
    {"key": "pos", "label": "POS (Punto de Venta)", "category": "ventas", "perm": "canManagePOS"},
    {"key": "price_lists", "label": "Listas de Precios", "category": "ventas", "perm": "canManageInventory"},
    {"key": "inventario", "label": "Inventario & Almacenes", "category": "logistica", "perm": "canManageInventory"},
    {"key": "contratos", "label": "Contratos & Recurrencia", "category": "operaciones", "perm": "canInvoice"},
    {"key": "comisiones", "label": "Comisiones & Metas", "category": "operaciones", "perm": "canManageCommissions"},
    {"key": "cxc", "label": "Cuentas por Cobrar (CxC)", "category": "finanzas", "perm": "canInvoice"},
    {"key": "cxp_compras", "label": "CxP, Proveedores & Compras", "category": "finanzas", "perm": "canCreateSupplier"},
    {"key": "gastos", "label": "Control de Gastos", "category": "finanzas", "perm": "canExpenses"},
    {"key": "banks", "label": "Bancos & Conciliación", "category": "finanzas", "perm": "canExpenses"},
    {"key": "contabilidad", "label": "Contabilidad & Catálogo de Cuentas", "category": "finanzas", "perm": "canAccounting"},
    {"key": "nomina", "label": "Nómina y Recursos Humanos", "category": "rrhh", "perm": "canHR"},
    {"key": "reporte_606", "label": "Reporte 606", "category": "cumplimiento", "perm": "canExpenses"},
    {"key": "certificacion", "label": "Certificación DGII", "category": "cumplimiento", "perm": "canCertifyDGII"},
    {"key": "api", "label": "API REST", "category": "integraciones", "perm": None},
    {"key": "multi_empresa", "label": "Multi-Empresa", "category": "enterprise", "perm": None},
    {"key": "portal_cliente", "label": "Portal del Cliente", "category": "enterprise", "perm": "canClients"},
    {"key": "ia_bi", "label": "IA & Business Intelligence", "category": "enterprise", "perm": "canViewBI"},
    {"key": "auditoria", "label": "Auditoría", "category": "enterprise", "perm": "canViewAuditLog"},
    {"key": "exportacion_contable", "label": "Exportación Contable", "category": "enterprise", "perm": "canAccounting"},
    {"key": "pasarela_azul", "label": "Pasarela de Pago Azul", "category": "enterprise", "perm": "canInvoice"},
]

MAIN_MODULE_KEYS = [
    "e_cf",
    "nomina",
    "contabilidad",
    "inventario",
    "crm",
    "pos",
    "cxc",
    "cxp_compras",
    "gastos",
    "banks",
    "reporte_606",
    "cotizaciones",
]

MODULE_MAP = {m["key"]: m for m in MODULE_DEFS}

BLUEPRINT_MODULE_MAP = {
    'api_accounting': 'contabilidad',
    'api_certificacion': 'certificacion',
    'api_clients': 'crm',
    'api_crm': 'crm',
    'api_dgii': 'e_cf',
    'api_expenses': 'gastos',
    'api_inventory': 'inventario',
    'api_invoices': 'e_cf',
    'api_liquidacion': 'nomina',
    'api_prospects': 'crm',
    'api_supplier_invoices': 'cxp_compras',
    'web_accounting': 'contabilidad',
    'web_api_portal': 'api',
    'web_audit': 'auditoria',
    'web_bank_entities': 'banks',
    'web_banks': 'banks',
    'web_bi': 'ia_bi',
    'web_budgets': 'ia_bi',
    'web_certificacion': 'certificacion',
    'web_clients': 'crm',
    'web_contacts': 'crm',
    'web_crm': 'crm',
    'web_fiscal_notes': 'e_cf',
    'web_inventory': 'inventario',
    'web_notes': 'crm',
    'web_pos': 'pos',
    'web_purchase_orders': 'cxp_compras',
    'web_recepcion': 'e_cf',
    'web_reports_606': 'reporte_606',
    'web_reports_607': 'e_cf',
    'web_reports_608': 'e_cf',
    'web_reports_623': 'e_cf',
    'web_reports_sales': 'e_cf',
    'web_rrhh': 'nomina',
    'web_rui': 'pos',
    'web_suppliers': 'cxp_compras',
}

PUBLIC_AND_GLOBAL_WHITELIST_BLUEPRINTS = {
    'web_auth', 'flasgger', 'metadata', 'api_auth', 'api_receptor',
    'web_company', 'web_dashboard', 'web_herramientas', 'web_i18n',
    'web_import_mapper', 'web_notifications', 'web_system_jobs',
    'web_vykcore', 'web_workflows'
}

PUBLIC_EXEMPT_ENDPOINTS = {
    'static', 'health_check', 'serve_uploaded_file'
}

PUBLIC_EXEMPT_PATHS = (
    '/static', '/uploads', '/health', '/ping', '/terminos', '/privacidad', '/precios',
    '/onboarding', '/settings', '/cambiar-plan', '/cancelar-suscripcion',
    '/reactivar-suscripcion', '/reports', '/reports/backup-export', '/reports/categoria/',
    '/notifications', '/invoices/verify/', '/invoices/qr/', '/invoices/public/',
    '/api/dgii/rnc/', '/api/azul/webhook', '/rrhh/verify/'
)


def resolve_endpoint_module(rule):
    """Determina de forma determinística el módulo requerido para cualquier regla de URL de Flask."""
    ep = rule.endpoint
    path = rule.rule
    bp = ep.split('.')[0] if '.' in ep else '_app'

    if ep in PUBLIC_EXEMPT_ENDPOINTS or bp in PUBLIC_AND_GLOBAL_WHITELIST_BLUEPRINTS:
        return None, 'WHITELIST_BLUEPRINT'

    if bp == 'portal':
        if ep == 'portal.portal_admin':
            return 'portal_cliente', 'PORTAL_ADMIN'
        return None, 'PORTAL_PUBLIC'

    if bp == 'web_invoices':
        if path == '/reports' or path == '/reports/backup-export' or any(path.startswith(p) for p in PUBLIC_EXEMPT_PATHS):
            return None, 'INVOICE_WHITELIST'
        if path.startswith('/inventory'):
            return 'inventario', 'INVENTORY'
        elif path.startswith('/price-lists'):
            return 'price_lists', 'PRICE_LISTS'
        elif path.startswith('/quotations') or path.startswith('/api/quotations'):
            return 'cotizaciones', 'COTIZACIONES'
        elif path.startswith('/cxc') or path.startswith('/api/ai/draft-collection'):
            return 'cxc', 'CXC'
        elif path.startswith('/expenses') or path.startswith('/api/expenses') or path.startswith('/api/ai/classify-expense') or path.startswith('/api/ai/receipt-ocr'):
            return 'gastos', 'GASTOS'
        elif path.startswith('/items') or path.startswith('/api/quick-create-product'):
            return 'catalogo', 'CATALOGO'
        elif path.startswith('/reports/export/accounting'):
            return 'exportacion_contable', 'EXPORT_ACC'
        elif path.startswith('/reports/bi') or path.startswith('/chatbot') or path.startswith('/api/chatbot'):
            return 'ia_bi', 'IA_BI'
        elif path.startswith('/reports/rrhh') or path.startswith('/reports/empleados'):
            return 'nomina', 'NOMINA'
        elif path.startswith('/api/save-chart-of-accounts'):
            return 'contabilidad', 'CONTABILIDAD'
        else:
            return 'e_cf', 'E_CF_DEFAULT'

    if bp == 'web_operations':
        if path.startswith('/operations/commissions'):
            return 'comisiones', 'COMISIONES'
        elif path.startswith('/operations/contracts') or path.startswith('/contracts'):
            return 'contratos', 'CONTRATOS'
        elif '/documents' in path:
            return 'crm', 'CRM_DOCS'
        return 'contratos', 'OPERATIONS_DEFAULT'

    if bp == 'web_rrhh' and path.startswith('/rrhh/verify/'):
        return None, 'RRHH_VERIFY_PUBLIC'

    if bp in BLUEPRINT_MODULE_MAP:
        return BLUEPRINT_MODULE_MAP[bp], bp

    return None, 'UNKNOWN'


def get_main_modules():
    """Retorna los módulos principales (para formularios públicos)."""
    return [m for m in MODULE_DEFS if m["key"] in MAIN_MODULE_KEYS]


def get_enabled_modules():
    """Retorna el dict de módulos habilitados desde la sesión."""
    from flask import session
    return session.get('company_modules') or {}


def module_enabled(module_key):
    """Verifica si un módulo específico está habilitado para la empresa actual.
    
    Política de seguridad: FAIL-CLOSED.
    Si la empresa no tiene el módulo explícitamente contratado con enabled=True,
    o si el módulo no existe en el catálogo canónico (MODULE_MAP),
    el acceso se DENEGA siempre (incluso para el rol 'owner').
    """
    if not module_key or module_key not in MODULE_MAP:
        return False

    from flask import session
    modules = get_enabled_modules()
    if not modules or not isinstance(modules, dict):
        return False

    if module_key not in modules:
        return False

    module_info = modules[module_key]
    if isinstance(module_info, dict):
        is_enabled = bool(module_info.get('enabled', False))
    elif isinstance(module_info, bool):
        is_enabled = module_info
    else:
        is_enabled = False

    if not is_enabled:
        return False

    # Para POS, requiere además que no esté desactivado en la configuración de la empresa
    if module_key == 'pos':
        return bool(session.get('company_profile_pos_enabled', True))

    return True


def get_module_label(module_key):
    """Retorna el nombre legible de un módulo."""
    if module_key in MODULE_MAP:
        return MODULE_MAP[module_key]["label"]
    return module_key


def require_module(module_key, feature_name=None):
    """Decorador para rutas web y endpoints que requieren un módulo habilitado.
    
    Si el módulo no está contratado:
    - Para llamadas JSON / API: retorna 403 Forbidden con JSON estructurado.
    - Para llamadas Web HTML: renderiza auth/restricted.html con código HTTP 403.
    """
    from functools import wraps
    from flask import render_template, request, jsonify

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not module_enabled(module_key):
                label = feature_name or get_module_label(module_key)
                
                # Petición API / JSON
                if (request.is_json or 
                    request.headers.get('Accept') == 'application/json' or 
                    request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "MODULE_DISABLED",
                            "message": f"El módulo '{label}' no está contratado en el plan de tu empresa."
                        }
                    }), 403
                
                # Petición Web HTML
                return render_template('auth/restricted.html',
                    feature_name=label,
                    required_permission=f"module_{module_key}",
                    custom_message=f"El módulo <strong>{label}</strong> no está incluido en tu plan actual. "
                                   "Contacta a soporte para información sobre mejoras de plan."
                ), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def gate_blueprint_module(bp, module_key, feature_name=None, login_endpoint='web_auth.login'):
    """Registra un hook before_request en el Blueprint para forzar module_enabled(module_key) Fail-Closed."""
    @bp.before_request
    def _blueprint_module_guard():
        from flask import session, redirect, url_for, request, jsonify, render_template
        if "user" not in session:
            return redirect(url_for(login_endpoint))
        if not module_enabled(module_key):
            label = feature_name or get_module_label(module_key)
            if (request.is_json or 
                request.headers.get("Accept") == "application/json" or 
                request.headers.get("X-Requested-With") == "XMLHttpRequest"):
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "MODULE_DISABLED",
                        "message": f"El módulo '{label}' no está contratado en tu plan actual."
                    }
                }), 403
            return render_template(
                "auth/restricted.html",
                feature_name=label,
                required_permission=f"module_{module_key}",
                custom_message=f"El módulo <strong>{label}</strong> no está incluido en tu plan actual. "
                               "Contacta a soporte para información sobre mejoras de plan."
            ), 403