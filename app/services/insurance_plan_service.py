"""Persistencia y validacion de planes de seguro."""

import uuid
from datetime import datetime, timezone

from app.services.db_service import db_firestore, firebase_initialized
from app.services.insurance_cost_calculator import calculate_contribution
from app.services.insurance_provider_service import get_provider


def _collection(company_id, sandbox=True):
    return f"companies/{company_id}/{('sandbox_' if sandbox else '')}hr_insurance_plans"


def _now():
    return datetime.now(timezone.utc).isoformat()


def list_plans(company_id, sandbox=True):
    if not firebase_initialized or db_firestore is None:
        return []
    return [{"id": doc.id, **doc.to_dict()} for doc in db_firestore.collection(_collection(company_id, sandbox)).get()]


def get_plan(company_id, plan_id, sandbox=True):
    if not firebase_initialized or db_firestore is None:
        return None
    doc = db_firestore.collection(_collection(company_id, sandbox)).document(plan_id).get()
    return {"id": doc.id, **doc.to_dict()} if doc.exists else None


def save_plan(company_id, data, user_email="", sandbox=True, concepts=None):
    provider = get_provider(company_id, data.get("providerId", ""), sandbox=sandbox)
    if not provider or provider.get("status") != "active":
        raise ValueError("El proveedor debe existir y estar activo.")
    if concepts is not None:
        concept_code = data.get("payrollConceptId", "")
        if not any(c.get("code") == concept_code for c in concepts):
            raise ValueError("Seleccione un concepto de nómina válido y activo.")
    result = calculate_contribution(data.get("baseAmount", 0), data.get("companyContribution"), data.get("employeeContribution"))
    plan_id = data.get("id") or str(uuid.uuid4())
    now = _now()
    payload = dict(data, id=plan_id, updatedAt=now, updatedBy=user_email)
    payload["baseAmount"] = str(result["totalAmount"])
    payload.setdefault("createdAt", now)
    payload.setdefault("createdBy", user_email)
    payload.setdefault("status", "active")
    if not firebase_initialized or db_firestore is None:
        return payload
    db_firestore.collection(_collection(company_id, sandbox)).document(plan_id).set(payload)
    return payload
