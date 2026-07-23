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
    default_val = False if permission_name in ('isPosSupervisor', 'canSupervisePOS', 'canUseChatbot') else True
    return user.get('permissions', {}).get(permission_name, default_val)


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
                return render_template('auth/restricted.html', feature_name=feature_name, required_permission=permission_name)
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
                    required_permission="")
            return f(*args, **kwargs)
        return decorated_function
    return decorator
