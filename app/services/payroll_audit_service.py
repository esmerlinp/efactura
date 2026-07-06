"""PayrollAuditService — Registro de auditoría para todas las acciones del módulo de nómina."""

import uuid
from datetime import datetime, timezone
from app.services.db_service import db_firestore, firebase_initialized


def _audit_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_audit_log"


def log_action(owner_uid: str, action: str, entity: str, entity_id: str,
               user_email: str, changes: dict = None, comment: str = "",
               sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
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
        }
        db_firestore.collection(coll).document(entry["id"]).set(entry)
    except Exception as e:
        print(f"⚠️ PayrollAuditService.log_action: {e}")


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
