"""Contrato de Producción — gestión de versiones, sanitización y publicación.

Este módulo es el único propietario del contenido contractual de producción.

Responsabilidades:
  - Sanitizar el HTML del contrato antes de almacenarlo.
  - Calcular el hash SHA-256 sobre una representación canónica y definida.
  - Crear y actualizar borradores.
  - Publicar versiones de forma atómica (una única versión activa).
  - Impedir la edición o eliminación de versiones publicadas.
  - Consultar la versión activa y el historial.

El contenido renderizado debe ser exactamente el contenido sanitizado cuyo hash
quedó registrado; por eso ``sanitize_html`` es el punto de entrada obligatorio
para todo contenido que entre al sistema.
"""

import re
import uuid
import hashlib
from html.parser import HTMLParser

from app.services.db_service import db_firestore, firebase_initialized


# ─────────────────────────────────────────────────────────────────────────────
# Sanitización de HTML (allowlist estricta, sin dependencias externas)
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_TAGS = {
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "strong", "b", "em", "i", "u", "s",
    "a",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "blockquote", "span", "div", "section",
    "sup", "sub",
}

_VOID_TAGS = {"br", "hr"}

# Elementos cuyo contenido debe descartarse por completo (raw text / embebidos).
_RAW_TEXT_TAGS = {
    "script", "style", "iframe", "noscript", "template",
    "textarea", "title", "object", "embed", "svg", "math", "head",
}

_ALLOWED_A_TAG_ATTRS = {"href", "title", "target"}

_SAFE_URL_SCHEMES = ("http:", "https:", "mailto:", "tel:")

_ENTITY_REF = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
    "nbsp": "\u00a0",
}


def _safe_url(value: str) -> str:
    """Retorna la URL si su esquema es permitido, de lo contrario una cadena vacía."""
    if not value:
        return ""
    stripped = value.strip().lower()
    for scheme in _SAFE_URL_SCHEMES:
        if stripped.startswith(scheme):
            return value.strip()
    # Permitir URLs relativas (anclas internas) pero sin javascript: ni data:
    if stripped.startswith(("javascript:", "data:", "vbscript:")):
        return ""
    return value.strip()


class _Sanitizer(HTMLParser):
    """Reconstruye HTML permitiendo únicamente etiquetas y atributos de la allowlist."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out = []
        self._depth = 0
        self._skip_raw = None

    def _tag_allowed(self, tag: str) -> bool:
        return tag.lower() in _ALLOWED_TAGS

    def handle_starttag(self, tag, attrs):
        if self._skip_raw:
            return
        if tag.lower() in _RAW_TEXT_TAGS:
            self._skip_raw = tag.lower()
            return
        if not self._tag_allowed(tag):
            return
        tag_l = tag.lower()
        attr_parts = []
        if tag_l == "a":
            for key, val in attrs:
                key_l = key.lower()
                if key_l not in _ALLOWED_A_TAG_ATTRS:
                    continue
                if val is None:
                    val = ""
                if key_l == "href":
                    val = _safe_url(val)
                    if not val:
                        continue
                elif key_l == "target":
                    if val.lower() != "_blank":
                        continue
                attr_parts.append(f' {key_l}="{val}"')
        self._out.append(f"<{tag_l}{''.join(attr_parts)}>")
        if tag_l not in _VOID_TAGS:
            self._depth += 1

    def handle_startendtag(self, tag, attrs):
        if self._tag_allowed(tag):
            self.handle_starttag(tag, attrs)
            if tag.lower() not in _VOID_TAGS:
                self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self._skip_raw:
            if tag.lower() == self._skip_raw:
                self._skip_raw = None
            return
        if not self._tag_allowed(tag):
            return
        tag_l = tag.lower()
        if tag_l in _VOID_TAGS:
            return
        if self._depth > 0:
            self._depth -= 1
        self._out.append(f"</{tag_l}>")

    def handle_data(self, data):
        if self._skip_raw:
            return
        if data:
            self._out.append(data)

    def handle_entityref(self, name):
        if self._skip_raw:
            return
        self._out.append(_ENTITY_REF.get(name, f"&{name};"))

    def handle_charref(self, name):
        if self._skip_raw:
            return
        try:
            if name.lower().startswith("x"):
                self._out.append(chr(int(name[1:], 16)))
            else:
                self._out.append(chr(int(name)))
        except (ValueError, OverflowError):
            pass

    def handle_comment(self, data):
        # Los comentarios se descartan por seguridad.
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def result(self) -> str:
        return "".join(self._out)


def sanitize_html(html_text: str) -> str:
    """Sanitiza el HTML del contrato con una allowlist estricta.

    Devuelve el contenido sanitizado (texto plano si la entrada no es HTML).
    """
    if not html_text:
        return ""
    parser = _Sanitizer()
    try:
        parser.feed(html_text)
        parser.close()
        return parser.result()
    except Exception:
        # Fallback seguro: devolver texto sin etiquetas.
        parser = _Sanitizer()
        parser.feed(html_text)
        return parser.result()


def canonicalize(html_text: str) -> str:
    """Representación canónica sobre la que se calcula el hash."""
    sanitized = sanitize_html(html_text)
    normalized = sanitized.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip()


def compute_content_hash(html_text: str) -> str:
    """SHA-256 hex de la representación canónica del contenido."""
    canonical = canonicalize(html_text)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Paths Firestore
# ─────────────────────────────────────────────────────────────────────────────

_VERSIONS_COLLECTION = "production_agreement_versions"
_SYSTEM_CONFIG_COLLECTION = "system_config"
_ACTIVE_POINTER_DOC = "production_agreement"


def _versions_ref():
    return db_firestore.collection(_VERSIONS_COLLECTION)


def _active_pointer_ref():
    return db_firestore.collection(_SYSTEM_CONFIG_COLLECTION).document(_ACTIVE_POINTER_DOC)


def _to_iso(value):
    """Convierte timestamps de Firestore (DatetimeWithNanoseconds) a ISO string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "to_datetime"):
        try:
            return value.to_datetime().isoformat()
        except Exception:
            pass
    return str(value)


class ProductionAgreementService:
    """Gestión de versiones del contrato de producción."""

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_SUPERSEDED = "superseded"
    ENVIRONMENT = "production"

    # ── Lectura ─────────────────────────────────────────────────────────────

    @classmethod
    def _available(cls) -> bool:
        return bool(firebase_initialized and db_firestore)

    @classmethod
    def get_version(cls, version_id: str) -> dict | None:
        if not cls._available() or not version_id:
            return None
        try:
            doc = _versions_ref().document(version_id).get()
            if doc.exists:
                return cls._normalize_version(doc.to_dict())
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al leer versión {version_id}: {e}")
        return None

    @classmethod
    def _normalize_version(cls, data: dict) -> dict:
        for field in ("createdAt", "updatedAt", "publishedAt"):
            if field in data:
                data[field] = _to_iso(data[field])
        return data

    @classmethod
    def get_active_version(cls) -> dict | None:
        if not cls._available():
            return None
        try:
            from app.services.cache_service import CacheService
            from app.cache import cache as _cache
            cache_key = CacheService.domain_key(
                "production_agreement_global", "__global__", False, "active_version"
            )
            cached = _cache.get(cache_key)
            if cached is not None:
                if cached.get("__none__"):
                    return None
                return cached

            pointer = _active_pointer_ref().get()
            active_id = ""
            if pointer.exists:
                active_id = pointer.to_dict().get("active_version_id", "")

            version = cls.get_version(active_id) if active_id else None
            if version and version.get("status") == cls.STATUS_ACTIVE:
                _cache.set(cache_key, version, timeout=30)
                return version

            _cache.set(cache_key, {"__none__": True}, timeout=30)
            return None
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al leer versión activa: {e}")
            return None

    @classmethod
    def list_versions(cls) -> list:
        if not cls._available():
            return []
        try:
            docs = _versions_ref().order_by("version", direction="DESCENDING").get()
            return [cls._normalize_version(doc.to_dict()) for doc in docs]
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al listar versiones: {e}")
            return []

    @classmethod
    def next_version_number(cls) -> int:
        versions = cls.list_versions()
        if not versions:
            return 1
        numbers = []
        for v in versions:
            try:
                numbers.append(int(v.get("version", 0)))
            except (TypeError, ValueError):
                continue
        return max(numbers, default=0) + 1

    # ── Escritura de borradores ─────────────────────────────────────────────

    @classmethod
    def create_draft(cls, title: str, content: str, created_by: str) -> dict | None:
        if not cls._available():
            return None
        sanitized = canonicalize(content)
        if not sanitized:
            return None
        version_id = str(uuid.uuid4())
        doc = {
            "id": version_id,
            "version": cls.next_version_number(),
            "title": (title or "").strip()[:200],
            "content": sanitized,
            "contentHash": compute_content_hash(sanitized),
            "status": cls.STATUS_DRAFT,
            "environment": cls.ENVIRONMENT,
            "createdBy": created_by or "",
            "createdAt": _server_timestamp(),
            "publishedAt": "",
            "publishedBy": "",
        }
        try:
            _versions_ref().document(version_id).set(doc)
            return doc
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al crear borrador: {e}")
            return None

    @classmethod
    def update_draft(cls, version_id: str, title: str, content: str, updated_by: str) -> dict | None:
        existing = cls.get_version(version_id)
        if not existing or existing.get("status") != cls.STATUS_DRAFT:
            return None
        sanitized = canonicalize(content)
        if not sanitized:
            return None
        update = {
            "title": (title or "").strip()[:200],
            "content": sanitized,
            "contentHash": compute_content_hash(sanitized),
            "updatedBy": updated_by or "",
            "updatedAt": _server_timestamp(),
        }
        try:
            _versions_ref().document(version_id).set(update, merge=True)
            updated = cls.get_version(version_id)
            return updated
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al actualizar borrador: {e}")
            return None

    # ── Publicación ─────────────────────────────────────────────────────────

    @classmethod
    def publish(cls, version_id: str, published_by: str) -> dict | None:
        """Publica una versión de forma atómica.

        La transacción:
          1. Verifica que la versión existe y está en estado draft.
          2. Recalcula el hash desde el contenido almacenado.
          3. Marca la versión activa anterior como superseded.
          4. Marca la nueva versión como activa.
          5. Actualiza el puntero global.
        """
        if not cls._available() or not version_id:
            return None

        from firebase_admin import firestore as _fstore

        transaction = db_firestore.transaction()

        @_fstore.transactional
        def _do_publish(tx):
            version_ref = _versions_ref().document(version_id)
            version_snap = version_ref.get(transaction=tx)
            if not version_snap.exists:
                raise ValueError("La versión no existe.")

            version = version_snap.to_dict()
            if version.get("status") != cls.STATUS_DRAFT:
                raise ValueError("Solo se pueden publicar borradores.")

            content = version.get("content", "")
            content_hash = compute_content_hash(content)

            pointer_ref = _active_pointer_ref()
            pointer_snap = pointer_ref.get(transaction=tx)
            previous_id = ""
            if pointer_snap.exists:
                previous_id = pointer_snap.to_dict().get("active_version_id", "")

            if previous_id and previous_id != version_id:
                prev_ref = _versions_ref().document(previous_id)
                prev_snap = prev_ref.get(transaction=tx)
                if prev_snap.exists:
                    tx.set(prev_ref, {"status": cls.STATUS_SUPERSEDED}, merge=True)

            tx.set(version_ref, {
                "status": cls.STATUS_ACTIVE,
                "contentHash": content_hash,
                "publishedBy": published_by or "",
                "publishedAt": _fstore.SERVER_TIMESTAMP,
            }, merge=True)

            tx.set(pointer_ref, {
                "active_version_id": version_id,
                "updated_by": published_by or "",
                "updated_at": _fstore.SERVER_TIMESTAMP,
            }, merge=True)

        try:
            _do_publish(transaction)
            cls._invalidate_global()
            return cls.get_version(version_id)
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al publicar versión: {e}")
            return None

    # ── Integridad ──────────────────────────────────────────────────────────

    @classmethod
    def verify_integrity(cls, version_id: str) -> bool:
        version = cls.get_version(version_id)
        if not version:
            return False
        expected = compute_content_hash(version.get("content", ""))
        return expected == version.get("contentHash", "")

    @classmethod
    def hash_matches(cls, version_id: str, content_hash: str) -> bool:
        version = cls.get_version(version_id)
        if not version or not content_hash:
            return False
        return version.get("contentHash", "") == content_hash

    @classmethod
    def _invalidate_global(cls):
        try:
            from app.services.cache_service import CacheService
            CacheService.invalidate_production_agreement_global()
        except Exception:
            pass


def _server_timestamp():
    """Retorna SERVER_TIMESTAMP de Firestore, o una marca ISO local en modo test."""
    try:
        from firebase_admin import firestore as _fstore
        return _fstore.SERVER_TIMESTAMP
    except Exception:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
