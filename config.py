import os
from dotenv import load_dotenv

# Cargar variables de entorno del archivo .env
load_dotenv(override=True)

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    
    # Configuración de Firebase
    _firebase_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', 'firebase-adminsdk.json')
    if not os.path.isabs(_firebase_json) and not os.path.exists(_firebase_json):
        _parent_json = os.path.join('..', _firebase_json)
        if os.path.exists(_parent_json):
            _firebase_json = _parent_json
    FIREBASE_SERVICE_ACCOUNT_JSON = _firebase_json
    FIREBASE_API_KEY = os.getenv('FIREBASE_API_KEY')
    FIREBASE_STORAGE_BUCKET = os.getenv('FIREBASE_STORAGE_BUCKET', 'e-factura-c2b78.firebasestorage.app')
    FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID', 'e-factura-c2b78')

    
    # Servidor de Correo SMTP
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')

    # OpenAI API Key para el Chatbot
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

    # Proveedor de Emisión de e-CF (siempre dgii_direct)
    E_CF_PROVIDER = 'dgii_direct'

    # Endpoints oficiales de la DGII (Legacy / compatibilidad)
    DGII_AUTH_URL = os.getenv('DGII_AUTH_URL', 'https://ecf.dgii.gov.do/test/autenticacion/api/Autenticacion/Semilla')
    DGII_RECEPCION_URL = os.getenv('DGII_RECEPCION_URL', 'https://ecf.dgii.gov.do/test/recepcion/api/Recepcion/Enviar')

    # Endpoints DGII por entorno (preferidos)
    DGII_AUTH_URL_SANDBOX = os.getenv('DGII_AUTH_URL_SANDBOX', DGII_AUTH_URL)
    DGII_AUTH_URL_PRODUCTION = os.getenv('DGII_AUTH_URL_PRODUCTION', '')
    DGII_TOKEN_URL_SANDBOX = os.getenv('DGII_TOKEN_URL_SANDBOX', os.getenv('DGII_TOKEN_URL', ''))
    DGII_TOKEN_URL_PRODUCTION = os.getenv('DGII_TOKEN_URL_PRODUCTION', '')
    DGII_RECEPCION_URL_SANDBOX = os.getenv('DGII_RECEPCION_URL_SANDBOX', DGII_RECEPCION_URL)
    DGII_RECEPCION_URL_PRODUCTION = os.getenv('DGII_RECEPCION_URL_PRODUCTION', '')
    DGII_STATUS_URL_SANDBOX = os.getenv('DGII_STATUS_URL_SANDBOX', os.getenv('DGII_STATUS_URL', ''))
    DGII_STATUS_URL_PRODUCTION = os.getenv('DGII_STATUS_URL_PRODUCTION', '')
    DGII_CANCEL_URL_SANDBOX = os.getenv('DGII_CANCEL_URL_SANDBOX', os.getenv('DGII_CANCEL_URL', ''))
    DGII_CANCEL_URL_PRODUCTION = os.getenv('DGII_CANCEL_URL_PRODUCTION', '')

    DGII_HTTP_TIMEOUT = int(os.getenv('DGII_HTTP_TIMEOUT', '20'))
    DGII_TOKEN_CONTENT_TYPE = os.getenv('DGII_TOKEN_CONTENT_TYPE', 'application/json')
    DGII_RECEPCION_CONTENT_TYPE = os.getenv('DGII_RECEPCION_CONTENT_TYPE', 'application/json')
    DGII_STATUS_CONTENT_TYPE = os.getenv('DGII_STATUS_CONTENT_TYPE', 'application/json')
    DGII_CANCEL_CONTENT_TYPE = os.getenv('DGII_CANCEL_CONTENT_TYPE', 'application/json')
    DGII_SIGNING_MODE = os.getenv('DGII_SIGNING_MODE', 'mock')
    DGII_ALLOW_SIMULATION = os.getenv('DGII_ALLOW_SIMULATION', 'true').lower() == 'true'
    DGII_SANDBOX_MODE = os.getenv('DGII_SANDBOX_MODE', 'local').lower()
    DGII_USER_AGENT = os.getenv('DGII_USER_AGENT', 'e-FacturaWeb/1.0')

    # Nombre del producto (marca)
    PRODUCT_NAME = os.getenv('PRODUCT_NAME', 'ZentOne')

    # Flask-Caching
    CACHE_TYPE = os.getenv('CACHE_TYPE', 'SimpleCache')
    CACHE_DEFAULT_TIMEOUT = int(os.getenv('CACHE_DEFAULT_TIMEOUT', '300'))
    CACHE_THRESHOLD = int(os.getenv('CACHE_THRESHOLD', '200'))

    # Uploads fuera de static/ (seguridad: no servir directamente sin auth)
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER',
                              os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'))

    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 28800  # 8 horas (coincide con sesión)
    WTF_CSRF_SSL_STRICT = False  # En desarrollo, puede no haber HTTPS
    WTF_CSRF_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE']

    # CORS
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*')

    # Rate Limiting
    RATELIMIT_ENABLED = os.getenv('RATELIMIT_ENABLED', 'true').lower() in ('true', '1', 'yes')
    RATELIMIT_STORAGE_URL = os.getenv('RATELIMIT_STORAGE_URL', 'memory://')
    RATELIMIT_STRATEGY = 'moving-window'
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_DEFAULT = os.getenv('RATELIMIT_DEFAULT', '200/day;50/hour;10/minute')
    RATELIMIT_SWALLOW_ERRORS = True

    # Seguridad de Sesión
    # Clave de cifrado para campos sensibles en Firestore (Fernet)
    FIELD_ENCRYPTION_KEY = os.getenv('FIELD_ENCRYPTION_KEY')

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() in ('true', '1', 'yes')
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = 28800  # 8 horas en segundos


