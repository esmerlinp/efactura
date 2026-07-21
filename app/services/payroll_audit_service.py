"""PayrollAuditService — Registro de auditoría para todas las acciones del módulo de nómina.
Ahora delegando en AuditService central para trazabilidad unificada con IP, user-agent y snapshots."""

import uuid
from datetime import datetime, timezone
from app.services.db_service import db_firestore, firebase_initialized


def _audit_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_audit_log"


def _get_request_context():
    """Extrae IP y user-agent del contexto Flask si está disponible."""
    try:
        from flask import request, session
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ua = request.headers.get("User-Agent", "")[:200]
        user_session = session.get("user", {})
        return ip, ua, user_session
    except Exception:
        return "", "", {}


def log_action(owner_uid: str, action: str, entity: str, entity_id: str,
               user_email: str, changes: dict = None, comment: str = "",
               sandbox: bool = True, before: dict = None, after: dict = None):
    ip_addr, user_agent, user_session = _get_request_context()

    if firebase_initialized and db_firestore is not None:
        try:
            coll = _audit_collection(owner_uid, sandbox)
            entry = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "userId": user_email,
                "action": action,
                "entity": entity,
                "entityId": entity_id,
                "changes": changes or {},
                "comment": comment,
                "ipAddress": ip_addr,
                "userAgent": user_agent,
                "before": before,
                "after": after,
            }
            db_firestore.collection(coll).document(entry["id"]).set(entry)
        except Exception as e:
            print(f"⚠️ PayrollAuditService.log_action: {e}")

    try:
        from app.services.audit_service import AuditService
        user_session = user_session or {}
        module_label = f"RRHH — {entity}"
        entity_label = f"{action} — {entity} {entity_id}"
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=action,
            module=module_label,
            entity_id=entity_id,
            entity_label=entity_label,
            user_session=user_session if user_session.get("email") else {"email": user_email, "uid": ""},
            before=before,
            after=after,
            sandbox=sandbox,
        )
    except Exception as e:
        print(f"⚠️ PayrollAuditService — error delegando a AuditService: {e}")


def get_audit_log(owner_uid: str, entity: str = None, entity_id: str = None,
                  limit: int = 200, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll = _audit_collection(owner_uid, sandbox)
        query = db_firestore.collection(coll).order_by("timestamp", direction="DESCENDING")
        if entity:
            query = query.where("entity", "==", entity)
        if entity_id:
            query = query.where("entityId", "==", entity_id)
        docs = query.limit(limit).get()
        return [d.to_dict() for d in docs]
    except Exception as e:
        print(f"⚠️ PayrollAuditService.get_audit_log: {e}")
        return []
