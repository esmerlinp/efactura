# app/extensions.py
import os
from app.cache import cache
from app.services.db_service import DatabaseService
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)

# Filtro Jinja2 personalizado para formatear montos monetarios (ej. 1,000.00)
def formatted_filter(value):
    try:
        return f"{float(value):,.2f}"
    except (ValueError, TypeError):
        return value

def format_date_filter(value):
    if not value or not isinstance(value, str):
        return value
    try:
        parts = value[:10].split('-')
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except Exception:
        pass
    return value

def init_extensions(app):
    """Inicializa base de datos local, caché, CSRF, rate limiter y registra filtros globales de Jinja2."""
    # Inicializar Flask-Caching
    cache.init_app(app)

    # Inicializar Base de Datos SQLite local y tablas de Firebase Auth
    DatabaseService.init_local_db()

    # Inicializar CSRF Protection (excluye rutas API y el portal de autogestión de clientes)
    csrf.init_app(app)

    # Eximir el blueprint del portal de clientes de validación CSRF
    from app.web.portal import portal_bp
    csrf.exempt(portal_bp)

    # Configurar CORS para APIs
    CORS(app, resources={r"/api/*": {"origins": os.getenv('CORS_ORIGINS', '*')}})

    # Registrar filtros personalizados
    app.template_filter('formatted')(formatted_filter)
    app.template_filter('money')(formatted_filter)
    app.template_filter('format_date')(format_date_filter)
    
    # Registrar funciones matemáticas y utilidades en Jinja2
    from datetime import datetime
    app.jinja_env.globals.update(min=min, max=max, datetime=datetime)
