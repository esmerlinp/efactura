# app/utils/decorators.py
from flask import session, render_template, flash
from app.utils.module_gate import module_enabled

# ═════════════════════════════════════════════════════════════════════
# MATRIZ DE SEGREGACIÓN DE FUNCIONES (SoD)
# Define conflictos de interés. Un mismo usuario no puede ejecutar
# ambos lados de un conflicto sobre la misma entidad.
# ═════════════════════════════════════════════════════════════════════

SOD_CONFLICT_MATRIX = {
    "canCreateSupplier": {"conflicts": ["canApprovePayments"], "label": "crear proveedores"},
    "canApprovePayments": {"conflicts": ["canCreateSupplier"], "label": "aprobar pagos"},
    "canInvoice": {"conflicts": ["canVoidInvoice"], "label": "emitir facturas"},
    "canVoidInvoice": {"conflicts": ["canInvoice"], "label": "anular facturas"},
    "canHR": {"conflicts": ["canApprovePayroll"], "label": "gestionar nómina"},
    "canApprovePayroll": {"conflicts": ["canHR"], "label": "autorizar pagos de nómina"},
    "canExpenses": {"conflicts": ["canApproveExpenses"], "label": "registrar gastos"},
    "canApproveExpenses": {"conflicts": ["canExpenses"], "label": "aprobar gastos"},
    "canModifySettings": {"conflicts": ["canViewAuditLog"], "label": "modificar configuración"},
    "canViewAuditLog": {"conflicts": ["canModifySettings"], "label": "ver pistas de auditoría"},
}


def check_permission(permission_name):
    if 'user' not in session:
        return False
    if permission_name == 'canManagePOS' and not session.get('company_profile_pos_enabled', True):
        return False
    if permission_name == 'canManagePOS' and not module_enabled('pos'):
        return False
    user = session['user']
    if user.get('role') == 'owner':
        return True

    user_perms = user.get('permissions', {})

    # Permisos granulares de CRM (CRM-07)
    if permission_name in ('canCRM', 'canCRMContacts', 'canCRMOpportunities', 'canCRMActivities', 'canCRMReports'):
        if permission_name in user_perms:
            return bool(user_perms[permission_name])
        # Compatibilidad hacia atrás: si no está definido el permiso CRM específico, consultar canClients
        if 'canClients' in user_perms:
            return bool(user_perms['canClients'])
        return True

    # Permisos granulares de Cotizaciones y Notas Fiscales (Ventas)
    if permission_name in ('canManageQuotations', 'canCreateQuotation'):
        if 'canManageQuotations' in user_perms:
            return bool(user_perms['canManageQuotations'])
        if 'canCreateQuotation' in user_perms:
            return bool(user_perms['canCreateQuotation'])
        # Compatibilidad hacia atrás: si no está definido, consultar canInvoice
        if 'canInvoice' in user_perms:
            return bool(user_perms['canInvoice'])
        return True

    if permission_name in ('canManageFiscalNotes', 'canFiscalNotes', 'canManageCreditNotes'):
        if 'canManageFiscalNotes' in user_perms:
            return bool(user_perms['canManageFiscalNotes'])
        if 'canFiscalNotes' in user_perms:
            return bool(user_perms['canFiscalNotes'])
        if 'canManageCreditNotes' in user_perms:
            return bool(user_perms['canManageCreditNotes'])
        # Compatibilidad hacia atrás: si no está definido, consultar canInvoice
        if 'canInvoice' in user_perms:
            return bool(user_perms['canInvoice'])
        return True

    if permission_name == 'canManageRUI':
        if 'canManageRUI' in user_perms:
            return bool(user_perms['canManageRUI'])
        # Compatibilidad hacia atrás: si no está definido, consultar canManagePOS
        if 'canManagePOS' in user_perms:
            return bool(user_perms['canManagePOS'])
        return True

    # Permisos granulares de Productos e Inventario
    inventory_granular = (
        'canManageCatalog',
        'canViewInventoryDashboard',
        'canInventoryKardex',
        'canInventoryReceipts',
        'canInventoryTransfers',
        'canInventoryCounts',
        'canInventoryLots',
        'canManageWarehouses',
        'canInventoryAdjustments',
        'canManagePriceLists',
    )
    if permission_name in inventory_granular:
        if permission_name in user_perms:
            return bool(user_perms[permission_name])
        # Compatibilidad hacia atrás:
        if permission_name == 'canManageCatalog':
            if 'canManageInventory' in user_perms:
                return bool(user_perms['canManageInventory'])
            if 'canClients' in user_perms:
                return bool(user_perms['canClients'])
            return True
        if permission_name == 'canManagePriceLists':
            if 'canManageInventory' in user_perms:
                return bool(user_perms['canManageInventory'])
            if 'canInvoice' in user_perms:
                return bool(user_perms['canInvoice'])
            return True
        if 'canManageInventory' in user_perms:
            return bool(user_perms['canManageInventory'])
        return True

    default_val = False if permission_name in ('isPosSupervisor', 'canSupervisePOS', 'canUseChatbot', 'canAssignApprovers') else True
    return user_perms.get(permission_name, default_val)


def get_user_landing_url():
    """Calcula y retorna la mejor URL de aterrizaje para el usuario actual según sus permisos y módulos activos.
    
    Si el usuario tiene acceso al Dashboard general, retorna la URL del Dashboard.
    En caso contrario, busca en orden el primer módulo o submódulo al que tenga acceso
    (por ejemplo, conteo de inventario, transferencias, facturación, cotizaciones, etc.).
    Retorna None si el usuario no tiene ningún permiso concedido en el sistema.
    """
    from flask import session, url_for, request
    if 'user' not in session:
        return None

    try:
        from app.utils.module_gate import module_enabled
    except Exception:
        def module_enabled(k):
            return True

    # 1. Dashboard General
    if check_permission('canViewDashboard'):
        return url_for('web_dashboard.dashboard')

    # 2. Facturación e-CF y Notas Fiscales
    if module_enabled('e_cf'):
        if check_permission('canInvoice'):
            return url_for('web_invoices.list_invoices')
        if check_permission('canManageFiscalNotes'):
            return url_for('web_fiscal_notes.list_fiscal_notes')

    # 3. Punto de Venta (POS) y RUI
    if module_enabled('pos'):
        if check_permission('canManagePOS'):
            return url_for('web_pos.pos_dashboard')
        if check_permission('canManageRUI'):
            return url_for('web_rui.rui_list')

    # 4. Cotizaciones
    if module_enabled('cotizaciones') and check_permission('canManageQuotations'):
        return url_for('web_invoices.list_quotations')

    # 5. Clientes / CRM
    if module_enabled('crm'):
        if check_permission('canClients') or check_permission('canCRM') or check_permission('canCRMContacts'):
            return url_for('web_clients.list_clients')
        if check_permission('canCRMOpportunities'):
            return url_for('web_crm.pipeline')

    # 6. Catálogo de Productos
    if module_enabled('catalogo') and check_permission('canManageCatalog'):
        return url_for('web_invoices.list_items')

    # 7. Inventario y Almacenes (Submódulos granulares)
    if module_enabled('inventario'):
        if check_permission('canViewInventoryDashboard'):
            return url_for('web_invoices.inventory_dashboard')
        if check_permission('canInventoryCounts'):
            return url_for('web_inventory.physical_count_list')
        if check_permission('canInventoryReceipts'):
            return url_for('web_inventory.list_receipts')
        if check_permission('canInventoryTransfers'):
            return url_for('web_inventory.transfer_list')
        if check_permission('canInventoryLots'):
            return url_for('web_inventory.lot_list')
        if check_permission('canInventoryKardex'):
            return url_for('web_inventory.kardex_view')
        if check_permission('canManageWarehouses'):
            return url_for('web_invoices.inventory_warehouses')
        if check_permission('canInventoryAdjustments'):
            return url_for('web_invoices.inventory_transactions')
        if check_permission('canManageInventory'):
            return url_for('web_invoices.inventory_dashboard')

    # 8. Listas de Precios
    if module_enabled('price_lists') and check_permission('canManagePriceLists'):
        return url_for('web_invoices.list_price_lists')

    # 9. Control de Gastos
    if module_enabled('gastos') and check_permission('canExpenses'):
        return url_for('web_invoices.list_expenses')

    # 10. CxP / Compras / Proveedores
    if module_enabled('cxp_compras') and (check_permission('canManageSuppliers') or check_permission('canCreateSupplier') or check_permission('canManageCXP') or check_permission('canManagePurchaseCXP')):
        return url_for('web_suppliers.list_suppliers')

    # 11. Cuentas por Cobrar (CxC)
    if module_enabled('cxc') and check_permission('canManageCXC'):
        return url_for('web_invoices.cxc_dashboard')

    # 12. Bancos & Conciliación
    if module_enabled('banks') and (check_permission('canBanks') or check_permission('canExpenses')):
        return url_for('web_banks.banks_dashboard')

    # 13. Contabilidad & Catálogo
    if module_enabled('contabilidad') and check_permission('canAccounting'):
        return url_for('web_accounting.dashboard')

    # 14. Nómina y Recursos Humanos
    if module_enabled('nomina') and check_permission('canHR'):
        return url_for('web_rrhh.employees_list')

    # 15. Contratos & Recurrencia
    if module_enabled('contratos') and check_permission('canManageContracts'):
        return url_for('web_invoices.list_contracts')

    # 16. Comisiones & Metas
    if module_enabled('comisiones') and check_permission('canManageCommissions'):
        return url_for('web_invoices.commissions_dashboard')

    # 17. Business Intelligence / Presupuestos
    if module_enabled('ia_bi') and check_permission('canViewBI'):
        return url_for('web_budgets.budgets_dashboard')

    # 18. Auditoría
    if module_enabled('auditoria') and check_permission('canViewAuditLog'):
        return url_for('web_audit.audit_logs')

    # 19. Reporte 606
    if module_enabled('reporte_606') and check_permission('canExpenses'):
        return url_for('web_reports_606.dashboard_606')

    # 20. Configuración de Empresa (si solo tiene permiso de settings)
    if check_permission('canModifySettings'):
        return url_for('web_invoices.company_profile_page')

    return None


def check_sod(owner_uid, user_uid, permission, entity_id, entity_type, company_id=None):
    conflict_info = SOD_CONFLICT_MATRIX.get(permission)
    if not conflict_info:
        return True, ""
    from app.services.db_service import DatabaseService
    conflicting_perms = conflict_info.get("conflicts", [])
    actions = DatabaseService.get_sod_actions(owner_uid, user_uid, entity_id, entity_type)
    for action in actions:
        if action.get("permission") in conflicting_perms:
            label = conflict_info.get("label", permission)
            return False, f"Conflicto de segregación de funciones: ya ejerció «{label}» sobre esta entidad. Otro miembro del equipo debe ejecutar esta acción."
    return True, ""


def record_sod_action(owner_uid, user_uid, user_email, permission, entity_id, entity_type, company_id=None):
    conflict_info = SOD_CONFLICT_MATRIX.get(permission)
    if not conflict_info:
        return
    from app.services.db_service import DatabaseService
    import uuid
    from datetime import datetime, timezone
    action = {
        "id": str(uuid.uuid4()),
        "ownerUID": owner_uid,
        "userUID": user_uid,
        "userEmail": user_email,
        "permission": permission,
        "entityId": entity_id,
        "entityType": entity_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    DatabaseService.save_sod_action(owner_uid, action)


def record_sod_from_session(permission, entity_id, entity_type):
    """Helper que extrae datos de sesión y registra acción SoD."""
    if 'user' not in session:
        return
    user = session['user']
    owner_uid = user.get('ownerUID', '')
    user_uid = user.get('uid', '')
    user_email = user.get('email', '')
    if owner_uid and user_uid:
        record_sod_action(owner_uid, user_uid, user_email, permission, entity_id, entity_type)


def require_permission(permission_name, feature_name="esta sección"):
    """Decorador para obligar a tener un permiso granular en vistas web Flask."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not check_permission(permission_name):
                return render_template('auth/restricted.html', feature_name=feature_name, required_permission=permission_name), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_country(*allowed_countries):
    """Decorador para restringir un endpoint a países específicos."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get('company_country', 'DO') not in allowed_countries:
                return render_template('auth/restricted.html',
                    feature_name="El recurso solicitado no está disponible para tu país",
                    required_permission=""), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator
