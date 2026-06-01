# app/utils/decorators.py
from flask import session, render_template

def check_permission(permission_name):
    """Retorna True si el usuario tiene el rol de propietario o cuenta con el permiso granular solicitado."""
    if 'user' not in session:
        return False
    user = session['user']
    if user.get('role') == 'owner':
        return True
    return user.get('permissions', {}).get(permission_name, True)

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
