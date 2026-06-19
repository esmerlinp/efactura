# app/utils/security.py
import os
import hashlib
import logging
from itsdangerous import URLSafeSerializer
from flask import current_app
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet

# Extensiones permitidas para subida de archivos
ALLOWED_EXTENSIONS = {
    'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp',
    'csv', 'xlsx', 'xls',
    'p12', 'pfx',
    'xml',
}

# Tamaño máximo de archivo: 16 MB
MAX_FILE_SIZE = 16 * 1024 * 1024

def validate_uploaded_file(file_storage, allowed_extensions=None):
    """Valida un archivo subido: extensión, tipo MIME y tamaño."""
    if allowed_extensions is None:
        allowed_extensions = ALLOWED_EXTENSIONS

    if not file_storage or not file_storage.filename:
        return False, "No se proporcionó ningún archivo."

    ext = os.path.splitext(file_storage.filename)[1].lower().lstrip('.')
    if not ext or ext not in allowed_extensions:
        return False, f"Tipo de archivo .{ext} no permitido."

    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_FILE_SIZE:
        return False, f"El archivo excede el tamaño máximo de {MAX_FILE_SIZE // (1024*1024)} MB."

    return True, ""

def sanitize_filename(filename):
    """Retorna un nombre de archivo seguro usando werkzeug."""
    name, ext = os.path.splitext(filename)
    safe_name = secure_filename(name)
    safe_ext = secure_filename(ext).lstrip('.')
    if safe_ext:
        return f"{safe_name}.{safe_ext}"
    return safe_name

def get_serializer():
    secret_key = current_app.config['SECRET_KEY']
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


def get_field_cipher():
    """Retorna una instancia Fernet desde FIELD_ENCRYPTION_KEY o None si no está configurada."""
    try:
        key = current_app.config.get('FIELD_ENCRYPTION_KEY')
    except RuntimeError:
        return None
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        logging.warning(f"FIELD_ENCRYPTION_KEY inválida: {e}")
        return None


def encrypt_field(plaintext):
    """Cifra un string con Fernet. Retorna texto plano si no hay clave configurada."""
    if not plaintext:
        return plaintext
    cipher = get_field_cipher()
    if not cipher:
        return plaintext
    return cipher.encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext):
    """Descifra un string con Fernet. Retorna texto plano si no está cifrado o no hay clave."""
    if not ciphertext:
        return ciphertext
    try:
        cipher = get_field_cipher()
        if not cipher:
            return ciphertext
        return cipher.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext


def sha256_hash(value):
    """Retorna SHA-256 hex digest de un string."""
    return hashlib.sha256(value.encode()).hexdigest()
