"""Contrato de Producción — evidencia de aceptación y reconocimiento.

Registra dos niveles independientes de evidencia inmutable:

  - ``accept_company``: aceptación contractual en representación de la compañía,
    exclusiva de ``companies/{company_id}.owner_uid``.
  - ``acknowledge_user``: reconocimiento individual de cada usuario activo.

La evidencia nunca se sobrescribe. Las correcciones se hacen con eventos
adicionales auditables, no editando el registro original.
"""

import uuid
from datetime import datetime, timezone

from app.services.db_service import db_firestore, firebase_initialized
from app.services.production_agreement_service import (
    ProductionAgreementService,
    compute_content_hash,
)

_ACCEPTANCES = "production_agreement_acceptances"
_ACKNOWLEDGEMENTS = "user_agreement_acknowledgements"


def _company_coll(company_id: str, coll_name: str):
    return db_firestore.collection("companies").document(company_id).collection(coll_name)


def _acceptances_coll_name(sandbox: bool) -> str:
    return ("sandbox_" if sandbox else "") + _ACCEPTANCES


def _acknowledgements_coll_name(sandbox: bool) -> str:
    return ("sandbox_" if sandbox else "") + _ACKNOWLEDGEMENTS


def _environment_label(sandbox: bool) -> str:
    return "sandbox" if sandbox else "production"


def _server_timestamp():
    try:
        from firebase_admin import firestore as _fstore
        return _fstore.SERVER_TIMESTAMP
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _ack_id(user_id: str, version_id: str) -> str:
    return f"{user_id}__{version_id}"


class ProductionAgreementAcceptanceService:
    """Registro de aceptaciones contractuales y reconocimientos individuales."""

    @classmethod
    def _available(cls) -> bool:
        return bool(firebase_initialized and db_firestore)

    # ── Helpers de identidad ────────────────────────────────────────────────

    @classmethod
    def _is_owner(cls, company_id: str, user_id: str) -> bool:
        if not company_id or not user_id:
            return False
        try:
            doc = db_firestore.collection("companies").document(company_id).get()
            if not doc.exists:
                return False
            return doc.to_dict().get("owner_uid", "") == user_id
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al verificar owner: {e}")
            return False

    @classmethod
    def _active_membership(cls, company_id: str, user_id: str) -> bool:
        try:
            docs = db_firestore.collection("company_memberships") \
                .where(filter=_FieldFilter("uid", "==", user_id)) \
                .where(filter=_FieldFilter("company_id", "==", company_id)) \
                .where(filter=_FieldFilter("status", "==", "active")) \
                .limit(1) \
                .get()
            for _ in docs:
                return True
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al verificar membresía: {e}")
            return False
        return False

    # ── Aceptación empresarial ──────────────────────────────────────────────

    @classmethod
    def accept_company(cls, company_id: str, user_id: str, user_name: str,
                       user_email: str, ip_address: str = "",
                       user_agent: str = "", sandbox: bool = False) -> dict:
        """Registra la aceptación contractual de la compañía por su propietario.

        Idempotente por (company_id, active_version_id, sandbox). Nunca confía en
        datos del navegador para el propietario, hash, versión o fecha. La
        evidencia de sandbox se guarda en una colección separada de producción.
        """
        if not cls._available() or not company_id or not user_id:
            return {"ok": False, "reason": "unavailable"}

        if not cls._is_owner(company_id, user_id):
            return {"ok": False, "reason": "not_owner"}

        if not cls._active_membership(company_id, user_id):
            return {"ok": False, "reason": "no_active_membership"}

        active = ProductionAgreementService.get_active_version()
        if not active:
            return {"ok": False, "reason": "no_active_version"}

        version_id = active.get("id", "")
        content_hash = active.get("contentHash", "")
        if not version_id or not content_hash:
            return {"ok": False, "reason": "invalid_active_version"}

        ref = _company_coll(company_id, _acceptances_coll_name(sandbox)).document(version_id)

        from firebase_admin import firestore as _fstore

        transaction = db_firestore.transaction()

        @_fstore.transactional
        def _write(tx):
            existing = ref.get(transaction=tx)
            if existing.exists:
                # Idempotente: si coincide el hash, no se reescribe la evidencia.
                stored = existing.to_dict()
                if stored.get("contentHash") == content_hash and stored.get("acceptedBy") == user_id:
                    return "already"
                raise ValueError("Evidencia previa con hash distinto; no se sobrescribe.")

            tx.set(ref, {
                "companyId": company_id,
                "agreementVersion": active.get("version", 0),
                "versionId": version_id,
                "contentHash": content_hash,
                "acceptedBy": user_id,
                "acceptedByName": user_name or "",
                "acceptedByEmail": user_email or "",
                "acceptedAt": _fstore.SERVER_TIMESTAMP,
                "acceptanceType": "company_contract",
                "acceptanceMethod": "electronic",
                "ipAddress": ip_address or "",
                "userAgent": (user_agent or "")[:300],
                "environment": _environment_label(sandbox),
            })

        try:
            _write(transaction)
            cls._invalidate(company_id, sandbox=sandbox)
            return {"ok": True, "version_id": version_id, "content_hash": content_hash}
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al aceptar por compañía: {e}")
            return {"ok": False, "reason": "write_error"}

    # ── Reconocimiento individual ───────────────────────────────────────────

    @classmethod
    def acknowledge_user(cls, company_id: str, user_id: str, user_name: str,
                         user_email: str, ip_address: str = "",
                         user_agent: str = "", sandbox: bool = False) -> dict:
        if not cls._available() or not company_id or not user_id:
            return {"ok": False, "reason": "unavailable"}

        if not cls._active_membership(company_id, user_id):
            return {"ok": False, "reason": "no_active_membership"}

        active = ProductionAgreementService.get_active_version()
        if not active:
            return {"ok": False, "reason": "no_active_version"}

        version_id = active.get("id", "")
        content_hash = active.get("contentHash", "")
        if not version_id or not content_hash:
            return {"ok": False, "reason": "invalid_active_version"}

        doc_id = _ack_id(user_id, version_id)
        ref = _company_coll(company_id, _acknowledgements_coll_name(sandbox)).document(doc_id)

        from firebase_admin import firestore as _fstore

        transaction = db_firestore.transaction()

        @_fstore.transactional
        def _write(tx):
            existing = ref.get(transaction=tx)
            if existing.exists:
                stored = existing.to_dict()
                if stored.get("contentHash") == content_hash and stored.get("userId") == user_id:
                    return "already"
                raise ValueError("Reconocimiento previo con hash distinto; no se sobrescribe.")

            tx.set(ref, {
                "id": doc_id,
                "companyId": company_id,
                "userId": user_id,
                "agreementVersion": active.get("version", 0),
                "versionId": version_id,
                "contentHash": content_hash,
                "acknowledgedAt": _fstore.SERVER_TIMESTAMP,
                "acceptanceType": "user_acknowledgement",
                "acceptanceMethod": "electronic",
                "ipAddress": ip_address or "",
                "userAgent": (user_agent or "")[:300],
                "environment": _environment_label(sandbox),
            })

        try:
            _write(transaction)
            cls._invalidate(company_id, user_id, sandbox=sandbox)
            return {"ok": True, "version_id": version_id, "content_hash": content_hash}
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al reconocer usuario: {e}")
            return {"ok": False, "reason": "write_error"}

    # ── Lectura de evidencia ────────────────────────────────────────────────

    @classmethod
    def get_company_acceptance(cls, company_id: str, version_id: str,
                               sandbox: bool = False) -> dict | None:
        if not cls._available() or not company_id or not version_id:
            return None
        try:
            doc = _company_coll(company_id, _acceptances_coll_name(sandbox)).document(version_id).get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al leer aceptación: {e}")
        return None

    @classmethod
    def get_user_acknowledgement(cls, company_id: str, user_id: str,
                                 version_id: str, sandbox: bool = False) -> dict | None:
        if not cls._available() or not company_id or not user_id or not version_id:
            return None
        try:
            doc = _company_coll(company_id, _acknowledgements_coll_name(sandbox)) \
                .document(_ack_id(user_id, version_id)).get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al leer reconocimiento: {e}")
        return None

    # ── Evidencia agregada (administración) ─────────────────────────────────

    @classmethod
    def list_company_acceptances(cls, company_id: str = None, limit: int = 200,
                                 sandbox: bool = False) -> list:
        if not cls._available():
            return []
        coll_name = _acceptances_coll_name(sandbox)
        try:
            if company_id:
                docs = _company_coll(company_id, coll_name).limit(limit).get()
            else:
                docs = db_firestore.collection_group(coll_name).limit(limit).get()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al listar aceptaciones: {e}")
            return []

    @classmethod
    def list_user_acknowledgements(cls, company_id: str = None, user_id: str = None,
                                   limit: int = 200, sandbox: bool = False) -> list:
        if not cls._available():
            return []
        coll_name = _acknowledgements_coll_name(sandbox)
        try:
            if company_id:
                query = _company_coll(company_id, coll_name)
                if user_id:
                    query = query.where(filter=_FieldFilter("userId", "==", user_id))
                docs = query.limit(limit).get()
            else:
                query = db_firestore.collection_group(coll_name)
                if user_id:
                    query = query.where(filter=_FieldFilter("userId", "==", user_id))
                docs = query.limit(limit).get()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al listar reconocimientos: {e}")
            return []

    # ── Caché ───────────────────────────────────────────────────────────────

    @classmethod
    def _invalidate(cls, company_id: str, user_id: str = None, sandbox: bool = False):
        try:
            from app.services.cache_service import CacheService
            CacheService.invalidate_production_agreement(company_id, user_id=user_id, sandbox=sandbox)
        except Exception:
            pass


def _FieldFilter(field, op, value):
    try:
        from firebase_admin import firestore as _fstore
        return _fstore.FieldFilter(field, op, value)
    except Exception:
        # Fallback para entornos mock en tests.
        return (field, op, value)
