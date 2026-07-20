"""OffboardingDataService — CRUD Firestore para el módulo Offboarding.

Sigue el mismo patrón que hr_data_service.py pero opera sobre 5 colecciones:
  - offboarding_requests
  - offboarding_settlements
  - offboarding_checklists
  - offboarding_documents
  - offboarding_interviews
  - offboarding_payments
  - offboarding_risk_assessments
  - offboarding_legal_cases
  - offboarding_rehire_requests
  - offboarding_versions
"""

from datetime import datetime, timezone
from typing import Optional

from app.services.db_service import db_firestore, firebase_initialized


# ── Helpers ────────────────────────────────────────────────────────────────

def _offboard_collection(owner_uid: str, sub: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_{sub}"


def _collection(sub: str, owner_uid: str, sandbox: bool):
    if not firebase_initialized or db_firestore is None:
        raise RuntimeError("Firestore no inicializado para OffboardingDataService")
    return db_firestore.collection(_offboard_collection(owner_uid, sub, sandbox))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CRUD genérico para cualquier colección "sub" ──────────────────────────

def get_all(sub: str, owner_uid: str, sandbox: bool = True,
            order_by: str = "createdAt", direction: str = "DESCENDING",
            limit: int = 100, where_filters: list[tuple] = None) -> list[dict]:
    coll = _collection(sub, owner_uid, sandbox)
    query = coll.order_by(order_by, direction=direction)
    docs = query.limit(limit).get()
    results = [d.to_dict() for d in docs]
    if where_filters:
        for field, op, value in where_filters:
            if op == "==":
                results = [r for r in results if r.get(field) == value]
    return results


def get_one(sub: str, doc_id: str, owner_uid: str, sandbox: bool = True) -> Optional[dict]:
    coll = _collection(sub, owner_uid, sandbox)
    doc = coll.document(doc_id).get()
    return doc.to_dict() if doc.exists else None


def save(sub: str, doc_id: str, data: dict, owner_uid: str, sandbox: bool = True) -> str:
    coll = _collection(sub, owner_uid, sandbox)
    data["updatedAt"] = _now()
    existing = coll.document(doc_id).get()
    if existing.exists:
        old = existing.to_dict()
        if "createdAt" in old:
            data["createdAt"] = old["createdAt"]
    else:
        if "createdAt" not in data or not data["createdAt"]:
            data["createdAt"] = _now()
    coll.document(doc_id).set(data, merge=True)
    return doc_id


def delete(sub: str, doc_id: str, owner_uid: str, sandbox: bool = True) -> bool:
    coll = _collection(sub, owner_uid, sandbox)
    coll.document(doc_id).delete()
    return True


# ── Helpers específicos ────────────────────────────────────────────────────

def get_request(request_id: str, owner_uid: str, sandbox: bool = True) -> Optional[dict]:
    return get_one("offboarding_requests", request_id, owner_uid, sandbox)


def save_request(request_id: str, data: dict, owner_uid: str, sandbox: bool = True) -> str:
    return save("offboarding_requests", request_id, data, owner_uid, sandbox)


def list_requests(owner_uid: str, sandbox: bool = True,
                  status: str = None, limit: int = 100) -> list[dict]:
    filters = None
    if status:
        filters = [("status", "==", status)]
    return get_all("offboarding_requests", owner_uid, sandbox,
                   order_by="createdAt", direction="DESCENDING",
                   limit=limit, where_filters=filters)
