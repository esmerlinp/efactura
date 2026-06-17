# app/utils/security.py
from itsdangerous import URLSafeSerializer
from flask import current_app

def get_serializer():
    # Usar la clave secreta de la aplicación
    secret_key = current_app.config.get('SECRET_KEY', 'default-fallback-key-change-me')
    return URLSafeSerializer(secret_key, salt='portal-access')

def generate_portal_token(owner_uid, client_id, sandbox=True):
    """Genera un token firmado y serializado seguro para URL conteniendo los parámetros."""
    s = get_serializer()
    data = {
        'owner_uid': owner_uid,
        'client_id': client_id,
        'sandbox': bool(sandbox)
    }
    return s.dumps(data)

def decode_portal_token(token):
    """Descifra y valida el token. Retorna los parámetros o None si es inválido o manipulado."""
    s = get_serializer()
    try:
        data = s.loads(token)
        return {
            'owner_uid': data.get('owner_uid'),
            'client_id': data.get('client_id'),
            'sandbox': data.get('sandbox', True)
        }
    except Exception as e:
        print(f"Error decodificando token de portal: {e}")
        return None
