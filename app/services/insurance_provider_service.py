"""Persistencia y reglas de proveedores de seguro."""

import uuid
from datetime import datetime, timezone

from app.services.db_service import db_firestore, firebase_initialized


def _collection(company_id, sandbox=True):
    return f"companies/{company_id}/{('sandbox_' if sandbox else '')}hr_insurance_providers"


def _now():
    return datetime.now(timezone.utc).isoformat()


def list_providers(company_id, sandbox=True):
    if not firebase_initialized or db_firestore is None:
        return []
    return [{"id": doc.id, **doc.to_dict()} for doc in db_firestore.collection(_collection(company_id, sandbox)).get()]


def get_provider(company_id, provider_id, sandbox=True):
    if not firebase_initialized or db_firestore is None:
        return None
    doc = db_firestore.collection(_collection(company_id, sandbox)).document(provider_id).get()
    return {"id": doc.id, **doc.to_dict()} if doc.exists else None


def save_provider(company_id, data, user_email="", sandbox=True):
    provider_id = data.get("id") or str(uuid.uuid4())
    now = _now()
    payload = dict(data, id=provider_id, updatedAt=now, updatedBy=user_email)
    payload.setdefault("createdAt", now)
    payload.setdefault("createdBy", user_email)
    payload.setdefault("status", "active")
    if not firebase_initialized or db_firestore is None:
        return payload
    db_firestore.collection(_collection(company_id, sandbox)).document(provider_id).set(payload)
    return payload
