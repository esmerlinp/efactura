# app/extensions.py
from app.services.db_service import DatabaseService

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
    """Inicializa base de datos local y registra filtros globales de Jinja2."""
    # Inicializar Base de Datos SQLite local y tablas de Firebase Auth
    DatabaseService.init_local_db()

    # Registrar filtros personalizados
    app.template_filter('formatted')(formatted_filter)
    app.template_filter('format_date')(format_date_filter)
    
    # Registrar funciones matemáticas y utilidades en Jinja2
    from datetime import datetime
    app.jinja_env.globals.update(min=min, max=max, datetime=datetime)
