import functools
from flask import request, jsonify, g
from firebase_service import DatabaseService

def require_api_key(f):
    """
    Decorador para autenticar peticiones de API utilizando una clave única de API.
    Espera la cabecera 'X-API-Key'.
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        
        if not api_key:
            return jsonify({
                "success": False,
                "error": "Falta la cabecera de autenticación 'X-API-Key'."
            }), 401
            
        company = DatabaseService.get_company_by_api_key(api_key)
        
        if not company:
            return jsonify({
                "success": False,
                "error": "La API Key provista es inválida o ha expirado."
            }), 401
            
        # Almacenar en el contexto global de Flask 'g' para ser accesible en las rutas
        g.company = company
        g.owner_uid = company.get("ownerUID")
        g.sandbox_mode = request.headers.get('X-Sandbox-Mode', 'true').lower() == 'true'
        
        return f(*args, **kwargs)
    return decorated_function
