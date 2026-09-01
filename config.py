import os
from dotenv import load_dotenv

# Cargar variables de entorno del archivo .env
load_dotenv(override=True)

# ═══════════════════════════════════════════════════════════════════
# APP_ENVIRONMENT — Master switch para modo de despliegue
# Valores: production | staging | sandbox | development
# Establece defaults sensatos para todas las variables dependientes.
# Las variables explícitas en .env o Cloud Run siempre tienen prioridad.
# ═══════════════════════════════════════════════════════════════════
APP_ENVIRONMENT = os.getenv('APP_ENVIRONMENT', 'production').lower()
if APP_ENVIRONMENT not in ('production', 'staging', 'sandbox', 'development'):
    APP_ENVIRONMENT = 'production'

_is_prod = APP_ENVIRONMENT == 'production'


def _apply_env_default(key: str, value: str):
    """Setea la variable de entorno solo si no fue definida explícitamente."""
    if key not in os.environ:
        os.environ[key] = value


_apply_env_default('DGII_ENVIRONMENT', 'ecf' if _is_prod else 'testecf')
_apply_env_default('DGII_SANDBOX_MODE', 'remote' if _is_prod else 'local')
_apply_env_default('DGII_SIGNING_MODE', 'real')
_apply_env_default('DGII_ALLOW_SIMULATION', 'false' if _is_prod else 'true')
_apply_env_default('SESSION_COOKIE_SECURE', 'true' if _is_prod else 'false')
_apply_env_default('RATELIMIT_DEFAULT',
                   '2000/day;500/hour;200/minute' if _is_prod
                   else '10000/day;2000/hour;500/minute')


class Config:
    # ─── Ambiente de despliegue ───────────────────────────────────
    APP_ENVIRONMENT = os.getenv('APP_ENVIRONMENT', 'production').lower()
    DEFAULT_SANDBOX_MODE = os.getenv(
        'DEFAULT_SANDBOX_MODE',
        'false' if APP_ENVIRONMENT == 'production' else 'true'
    ).lower() in ('true', '1', 'yes')

    SECRET_KEY = os.getenv('SECRET_KEY')
    
    # Configuración de Firebase
    _firebase_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', 'firebase-adminsdk.json')
    if not os.path.isabs(_firebase_json) and not os.path.exists(_firebase_json):
        _parent_json = os.path.join('..', _firebase_json)
        if os.path.exists(_parent_json):
            _firebase_json = _parent_json
    FIREBASE_SERVICE_ACCOUNT_JSON = _firebase_json
    FIREBASE_API_KEY = os.getenv('FIREBASE_API_KEY')
    FIREBASE_STORAGE_BUCKET = os.getenv('FIREBASE_STORAGE_BUCKET', 'vykcore.com')
    FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID', 'vykcore')

    
    # Servidor de Correo SMTP
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')

    # Remitentes por tipo de correo (aliases)
    MAIL_FROM_INVOICE = os.getenv('MAIL_FROM_INVOICE', SMTP_USER)
    MAIL_FROM_NOTIFICATION = os.getenv('MAIL_FROM_NOTIFICATION', SMTP_USER)
    MAIL_FROM_NOREPLY = os.getenv('MAIL_FROM_NOREPLY', SMTP_USER)
    MAIL_FROM_SUPPORT = os.getenv('MAIL_FROM_SUPPORT', SMTP_USER)

    # Microsoft Graph API (reemplaza SMTP)
    MAIL_USE_GRAPH_API = os.getenv('MAIL_USE_GRAPH_API', 'false').lower() == 'true'
    MAIL_TENANT_ID = os.getenv('MAIL_TENANT_ID', '')
    MAIL_CLIENT_ID = os.getenv('MAIL_CLIENT_ID', '')
    MAIL_CLIENT_SECRET = os.getenv('MAIL_CLIENT_SECRET', '')
    MAIL_GRAPH_USER = os.getenv('MAIL_GRAPH_USER', SMTP_USER)

    # OpenAI API Key para el Chatbot
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

    # Proveedor de Emisión de e-CF (siempre dgii_direct)
    E_CF_PROVIDER = 'dgii_direct'

    # ─── DGII Ambient Configuration ──────────────────────────────
    # DGII_ENVIRONMENT selects the API subdomain: testecf | certecf | ecf
    DGII_ENVIRONMENT = os.getenv('DGII_ENVIRONMENT', 'testecf').lower()
    _dgii_env = DGII_ENVIRONMENT
    # Production environment override (used when sandbox=False)
    DGII_ENVIRONMENT_PRODUCTION = os.getenv('DGII_ENVIRONMENT_PRODUCTION', 'ecf').lower()
    _dgii_env_prod = DGII_ENVIRONMENT_PRODUCTION

    @classmethod
    def _dgii_ecf_url(cls, path: str, sandbox: bool = True) -> str:
        env = cls.DGII_ENVIRONMENT if sandbox else cls.DGII_ENVIRONMENT_PRODUCTION
        return f"https://ecf.dgii.gov.do/{env}{path}"

    @classmethod
    def _dgii_fc_url(cls, path: str, sandbox: bool = True) -> str:
        env = cls.DGII_ENVIRONMENT if sandbox else cls.DGII_ENVIRONMENT_PRODUCTION
        return f"https://fc.dgii.gov.do/{env}{path}"

    # ─── Autenticación ───────────────────────────────────────────
    DGII_AUTH_SEMILLA_URL = os.getenv(
        'DGII_AUTH_SEMILLA_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/autenticacion/api/autenticacion/semilla"
    )
    DGII_AUTH_VALIDAR_URL = os.getenv(
        'DGII_AUTH_VALIDAR_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/autenticacion/api/autenticacion/validarsemilla"
    )

    # ─── Recepción e-CF ──────────────────────────────────────────
    DGII_RECEPCION_URL = os.getenv(
        'DGII_RECEPCION_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/recepcion/api/facturaselectronicas"
    )

    # ─── RFCE (Resumen Factura Consumo < RD$250K) ───────────────
    DGII_RFCE_RECEPCION_URL = os.getenv(
        'DGII_RFCE_RECEPCION_URL',
        f"https://fc.dgii.gov.do/{_dgii_env}/recepcionfc/api/recepcion/ecf"
    )
    DGII_RFCE_CONSULTA_URL = os.getenv(
        'DGII_RFCE_CONSULTA_URL',
        f"https://fc.dgii.gov.do/{_dgii_env}/consultarfce/api/Consultas/Consulta"
    )

    # ─── Consultas ───────────────────────────────────────────────
    DGII_CONSULTA_RESULTADO_URL = os.getenv(
        'DGII_CONSULTA_RESULTADO_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/consultaresultado/api/consultas/estado"
    )
    DGII_CONSULTA_ESTADO_URL = os.getenv(
        'DGII_CONSULTA_ESTADO_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/consultaestado/api/consultas/estado"
    )
    DGII_CONSULTA_TRACKIDS_URL = os.getenv(
        'DGII_CONSULTA_TRACKIDS_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/consultatrackids/api/trackids/consulta"
    )

    # ─── Aprobación Comercial ────────────────────────────────────
    DGII_APROBACION_COMERCIAL_URL = os.getenv(
        'DGII_APROBACION_COMERCIAL_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/aprobacioncomercial/api/aprobacioncomercial"
    )

    # ─── Anulación de Rangos ─────────────────────────────────────
    DGII_ANULACION_RANGOS_URL = os.getenv(
        'DGII_ANULACION_RANGOS_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/anulacionrangos/api/operaciones/anularrango"
    )

    # ─── Directorio ──────────────────────────────────────────────
    DGII_DIRECTORIO_LISTADO_URL = os.getenv(
        'DGII_DIRECTORIO_LISTADO_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/consultadirectorio/api/consultas/listado"
    )
    DGII_DIRECTORIO_POR_RNC_URL = os.getenv(
        'DGII_DIRECTORIO_POR_RNC_URL',
        f"https://ecf.dgii.gov.do/{_dgii_env}/consultadirectorio/api/consultas/obtenerdirectorioporrnc"
    )

    # ─── Timbre QR ───────────────────────────────────────────────
    DGII_CONSULTA_TIMBRE_URL = f"https://ecf.dgii.gov.do/{_dgii_env}/consultatimbre"
    DGII_CONSULTA_TIMBRE_FC_URL = f"https://fc.dgii.gov.do/{_dgii_env}/consultatimbrefc"

    # ─── Producción URLs (override para sandbox=False) ──────────
    DGII_RECEPCION_URL_PRODUCTION = os.getenv(
        'DGII_RECEPCION_URL_PRODUCTION',
        f"https://ecf.dgii.gov.do/{_dgii_env_prod}/recepcion/api/facturaselectronicas"
    )
    DGII_AUTH_SEMILLA_URL_PRODUCTION = os.getenv(
        'DGII_AUTH_SEMILLA_URL_PRODUCTION',
        f"https://ecf.dgii.gov.do/{_dgii_env_prod}/autenticacion/api/autenticacion/semilla"
    )
    DGII_AUTH_VALIDAR_URL_PRODUCTION = os.getenv(
        'DGII_AUTH_VALIDAR_URL_PRODUCTION',
        f"https://ecf.dgii.gov.do/{_dgii_env_prod}/autenticacion/api/autenticacion/validarsemilla"
    )
    DGII_CONSULTA_RESULTADO_URL_PRODUCTION = os.getenv(
        'DGII_CONSULTA_RESULTADO_URL_PRODUCTION',
        f"https://ecf.dgii.gov.do/{_dgii_env_prod}/consultaresultado/api/consultas/estado"
    )
    DGII_ANULACION_RANGOS_URL_PRODUCTION = os.getenv(
        'DGII_ANULACION_RANGOS_URL_PRODUCTION',
        f"https://ecf.dgii.gov.do/{_dgii_env_prod}/anulacionrangos/api/operaciones/anularrango"
    )
    DGII_RFCE_RECEPCION_URL_PRODUCTION = os.getenv(
        'DGII_RFCE_RECEPCION_URL_PRODUCTION',
        f"https://fc.dgii.gov.do/{_dgii_env_prod}/recepcionfc/api/recepcion/ecf"
    )
    DGII_RFCE_CONSULTA_URL_PRODUCTION = os.getenv(
        'DGII_RFCE_CONSULTA_URL_PRODUCTION',
        f"https://fc.dgii.gov.do/{_dgii_env_prod}/consultarfce/api/Consultas/Consulta"
    )

    DGII_HTTP_TIMEOUT = int(os.getenv('DGII_HTTP_TIMEOUT', '20'))
    DGII_SIGNING_MODE = os.getenv('DGII_SIGNING_MODE', 'mock')
    DGII_ALLOW_SIMULATION = os.getenv('DGII_ALLOW_SIMULATION', 'true').lower() == 'true'
    DGII_SANDBOX_MODE = os.getenv('DGII_SANDBOX_MODE', 'local').lower()
    DGII_USER_AGENT = os.getenv('DGII_USER_AGENT', 'VykOne/1.0')

    # --- Receptor e-CF (URLs registradas ante la DGII: /fe/...) ---
    RECEPTOR_AUTH_ENABLED = os.getenv('RECEPTOR_AUTH_ENABLED', 'true').lower() == 'true'
    RECEPTOR_TOKEN_EXPIRY_MINUTES = int(os.getenv('RECEPTOR_TOKEN_EXPIRY_MINUTES', '30'))
    RECEPTOR_SEED_TTL_SECONDS = int(os.getenv('RECEPTOR_SEED_TTL_SECONDS', '900'))
    RECEPTOR_REQUIRE_SIGNATURE = os.getenv('RECEPTOR_REQUIRE_SIGNATURE', 'false').lower() == 'true'
    # Empresa receptora por defecto del despliegue (el RNC del certificado del
    # emisor no identifica al receptor). Usar el owner_uid de la compañía
    # certificada/receptora de este entorno.
    RECEPTOR_DEFAULT_OWNER_UID = os.getenv('RECEPTOR_DEFAULT_OWNER_UID', '')

    # Nombre del producto (marca)
    PRODUCT_NAME = os.getenv('PRODUCT_NAME', 'VykOne')

    # --- Gunicorn / Memoria (usado desde Dockerfile) ---
    WEB_CONCURRENCY = int(os.getenv('WEB_CONCURRENCY', '2'))
    THREADS = int(os.getenv('THREADS', '4'))
    GUNICORN_TIMEOUT = int(os.getenv('GUNICORN_TIMEOUT', '30'))
    MAX_REQUESTS = int(os.getenv('MAX_REQUESTS', '1000'))
    MAX_REQUESTS_JITTER = int(os.getenv('MAX_REQUESTS_JITTER', '100'))

    # Flask-Caching
    CACHE_TYPE = os.getenv('CACHE_TYPE', 'SimpleCache')
    CACHE_DEFAULT_TIMEOUT = int(os.getenv('CACHE_DEFAULT_TIMEOUT', '300'))
    CACHE_THRESHOLD = int(os.getenv('CACHE_THRESHOLD', '200'))

    # Límites de consultas Firestore (previene cargas masivas en memoria)
    FIRESTORE_MAX_INVOICES = int(os.getenv('FIRESTORE_MAX_INVOICES', '500'))
    FIRESTORE_MAX_CLIENTS = int(os.getenv('FIRESTORE_MAX_CLIENTS', '500'))
    FIRESTORE_MAX_EXPENSES = int(os.getenv('FIRESTORE_MAX_EXPENSES', '500'))

    # Uploads fuera de static/ (seguridad: no servir directamente sin auth)
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER',
                              os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'))

    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 28800  # 8 horas (coincide con sesión)
    WTF_CSRF_SSL_STRICT = False  # En desarrollo, puede no haber HTTPS
    WTF_CSRF_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE']

    # CORS — restrict to specific origins in production; never use wildcard * as default
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '')

    # Rate Limiting
    RATELIMIT_ENABLED = os.getenv('RATELIMIT_ENABLED', 'true').lower() in ('true', '1', 'yes')
    RATELIMIT_STORAGE_URL = os.getenv('RATELIMIT_STORAGE_URL', 'memory://')
    RATELIMIT_STRATEGY = 'moving-window'
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_DEFAULT = os.getenv('RATELIMIT_DEFAULT', '2000/day;500/hour;200/minute')
    RATELIMIT_SWALLOW_ERRORS = True

    # Seguridad de Sesión
    # Clave de cifrado para campos sensibles en Firestore (Fernet)
    FIELD_ENCRYPTION_KEY = os.getenv('FIELD_ENCRYPTION_KEY')

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'true').lower() in ('true', '1', 'yes')
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = 28800  # 8 horas en segundos

    # Templates — recargar automáticamente sin necesidad de reiniciar el servidor
    TEMPLATES_AUTO_RELOAD = True

    # ─── Generación PDF (WeasyPrint) ─────────────────────────────
    # Controla el peso de los PDFs generados. Si el portal de la DGII
    # exige que la suma de documentos no exceda un límite (ej. 10MB),
    # baja PDF_DPI y PDF_JPEG_QUALITY para obtener archivos más livianos.
    PDF_OPTIMIZE_IMAGES = os.getenv('PDF_OPTIMIZE_IMAGES', 'true').lower() in ('true', '1', 'yes')
    PDF_DPI = int(os.getenv('PDF_DPI', '150'))
    PDF_JPEG_QUALITY = int(os.getenv('PDF_JPEG_QUALITY', '80'))


