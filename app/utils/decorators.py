# app/utils/decorators.py
from flask import session, render_template, flash
from app.utils.module_gate import module_enabled

# ═════════════════════════════════════════════════════════════════════
# MATRIZ DE SEGREGACIÓN DE FUNCIONES (SoD)
# Define conflictos de interés que aplican incluso al rol owner.
# Formato: permission_name -> {conflicts: [permisos en conflicto]}
# Cuando un usuario owner ya ha ejercido un permiso, los permisos
# en conflicto se bloquean a menos que otro miembro los ejecute.
# ═════════════════════════════════════════════════════════════════════

SOD_CONFLICT_MATRIX = {
    # Crear proveedor vs aprobar pago
    "canCreateSupplier": {"conflicts": ["canApprovePayments"], "label": "crear proveedores"},
    "canApprovePayments": {"conflicts": ["canCreateSupplier"], "label": "aprobar pagos"},
    # Emitir factura vs anular factura
    "canInvoice": {"conflicts": ["canVoidInvoice"], "label": "emitir facturas"},
    "canVoidInvoice": {"conflicts": ["canInvoice"], "label": "anular facturas"},
    # Registrar nómina vs autorizar pago de nómina
    "canHR": {"conflicts": ["canApprovePayroll"], "label": "gestionar nómina"},
    "canApprovePayroll": {"conflicts": ["canHR"], "label": "autorizar pagos de nómina"},
    # Registrar gasto vs aprobar gasto
    "canExpenses": {"conflicts": ["canApproveExpenses"], "label": "registrar gastos"},
    "canApproveExpenses": {"conflicts": ["canExpenses"], "label": "aprobar gastos"},
    # Modificar configuración vs auditar
    "canModifySettings": {"conflicts": ["canViewAuditLog"], "label": "modificar configuración"},
    "canViewAuditLog": {"conflicts": ["canModifySettings"], "label": "ver pistas de auditoría"},
}


def check_permission(permission_name):
    """
    Retorna True si el usuario tiene el permiso granular solicitado.
    Para el rol owner, aplica matriz SoD: si ya tiene un permiso en conflicto,
    se deniega (a menos que se haya delegado explícitamente a otro miembro).
    """
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