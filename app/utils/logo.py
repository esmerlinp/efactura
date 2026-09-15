"""Resolución del logo de empresa a una data URI lista para <img>.

Prioridad:
1. ``logoBase64`` (crudo o ya prefijado ``data:``).
2. ``logoStoragePath`` → descarga con el SDK de Firebase Storage (usa la cuenta de
   servicio, por lo que no depende del ACL público del bucket).
3. ``logoUrl`` http(s) → descarga con ``urllib``.
4. ``logoUrl`` ``/uploads/...`` → lee el archivo local (fallback de desarrollo).
5. Nada → ``""`` (el template omite el <img>).
"""

import base64
import os
from functools import lru_cache

_DATA_MIMES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
}


def _get(company, *keys):
    for key in keys:
        value = None
        try:
            value = company.get(key)
        except AttributeError:
            value = getattr(company, key, None)
        if value:
            return value
    return ""


def _to_data_uri(raw, mime):
    return f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"


def _mime_from_path(path):
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    return _DATA_MIMES.get(ext, "image/png")


@lru_cache(maxsize=256)
def _download_from_storage(path):
    try:
        from app.services.db_service import firebase_initialized, firebase_storage_bucket
        if not firebase_initialized or not firebase_storage_bucket:
            return None
        blob = firebase_storage_bucket.blob(path)
        return blob.download_as_bytes(timeout=30)
    except Exception:
        return None


def _download_url(url):
    try:
        from urllib.request import Request, urlopen
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=8) as resp:
            raw = resp.read()
            mime = (resp.headers.get("Content-Type", "") or "").split(";")[0].strip()
            if mime not in _DATA_MIMES.values():
                mime = "image/png"
            return _to_data_uri(raw, mime)
    except Exception:
        return None


def _read_local_uploads(url):
    try:
        from flask import current_app
        rel = url[len("/uploads/"):] if url.startswith("/uploads/") else url.lstrip("/")
        uploads_dir = current_app.config.get("UPLOAD_FOLDER", "")
        if not uploads_dir:
            from config import Config
            uploads_dir = Config.UPLOAD_FOLDER
        full = os.path.normpath(os.path.join(uploads_dir, rel))
        if not full.startswith(os.path.normpath(uploads_dir)):
            return None
        if not os.path.isfile(full):
            return None
        with open(full, "rb") as f:
            raw = f.read()
        return _to_data_uri(raw, _mime_from_path(full))
    except Exception:
        return None


def _storage_path_from_url(url):
    """Deriva el blob path de Firebase Storage a partir de su URL pública.

    Maneja la forma ``https://storage.googleapis.com/{bucket}/{path}`` y la
    forma media ``https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{path}``.
    """
    try:
        from urllib.parse import unquote
        from app.services.db_service import firebase_storage_bucket
        if not firebase_storage_bucket:
            return None
        bucket = firebase_storage_bucket.name
        marker = f"storage.googleapis.com/{bucket}/"
        if marker in url:
            return unquote(url.split(marker, 1)[1].split("?", 1)[0])
        marker2 = f"/v0/b/{bucket}/o/"
        if marker2 in url:
            return unquote(url.split(marker2, 1)[1].split("?", 1)[0])
    except Exception:
        return None
    return None


def resolve_image_data_uri(url, storage_path=None, base64_data=None):
    """Devuelve un ``src`` listo para <img> (data URI) a partir de una imagen.

    Sirve para firmas, sellos y cualquier imagen remota o local que WeasyPrint
    deba incrustar. Resuelve en capas (de más a menos confiable):

    1. ``base64_data`` embebido.
    2. ``storage_path`` → descarga por SDK de Firebase (cuenta de servicio).
    3. Blob path derivado de la URL pública → SDK.
    4. Descarga HTTP de la URL.
    5. Archivo local ``/uploads/...``.
    6. La URL original como fallback.
    """
    url = (url or "").strip()
    storage_path = (storage_path or "").strip()
    base64_data = (base64_data or "").strip()

    if base64_data:
        return base64_data if base64_data.startswith("data:") else "data:image/png;base64," + base64_data
    if url.startswith("data:"):
        return url
    if storage_path:
        raw = _download_from_storage(storage_path)
        if raw:
            return _to_data_uri(raw, _mime_from_path(storage_path))
    if url:
        derived = _storage_path_from_url(url)
        if derived:
            raw = _download_from_storage(derived)
            if raw:
                return _to_data_uri(raw, _mime_from_path(derived))
    if url.startswith("http://") or url.startswith("https://"):
        return _download_url(url) or url
    if url.startswith("/uploads/"):
        return _read_local_uploads(url) or url
    return url


def resolve_logo_data_uri(company):
    """Devuelve un ``src`` listo para <img> o ``""`` si no hay logo usable."""
    company = company or {}

    b64 = _get(company, "logoBase64", "logo_base64")
    if b64:
        return b64 if b64.startswith("data:") else "data:image/png;base64," + b64

    path = _get(company, "logoStoragePath", "logo_storage_path")
    if path:
        raw = _download_from_storage(path)
        if raw:
            return _to_data_uri(raw, _mime_from_path(path))

    url = _get(company, "logoUrl", "logo_url")
    if url:
        if url.startswith("http://") or url.startswith("https://"):
            data_uri = _download_url(url)
            if data_uri:
                return data_uri
            return url
        if url.startswith("/uploads/"):
            data_uri = _read_local_uploads(url)
            if data_uri:
                return data_uri
        return url

    return ""
