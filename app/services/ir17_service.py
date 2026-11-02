"""Persistencia y ciclo de vida de declaraciones IR-17."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.fiscal_forms.ir17_rules import IR17_RULES_VERSION, default_line_items
from app.services.ir17_calculator import calculate_ir17
from app.services.ir17_validator import validate_ir17


class IR17Service:
    COLLECTION = "ir17_declarations"

    @classmethod
    def _collection(cls, owner_uid, company_id, sandbox):
        from app.services.db_service import _company_coll, db_firestore, firebase_initialized
        if not firebase_initialized or db_firestore is None:
            return None
        prefix = "sandbox_" if sandbox else ""
        return _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=prefix + cls.COLLECTION)

    @classmethod
    def list(cls, owner_uid, company_id, sandbox):
        coll = cls._collection(owner_uid, company_id, sandbox)
        if coll is None:
            return []
        result = []
        for doc in coll.get():
            item = doc.to_dict()
            item["id"] = doc.id
            result.append(item)
        return sorted(result, key=lambda x: x.get("period", ""), reverse=True)

    @classmethod
    def get(cls, owner_uid, company_id, sandbox, declaration_id):
        coll = cls._collection(owner_uid, company_id, sandbox)
        if coll is None:
            return None
        doc = coll.document(declaration_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    @classmethod
    def save(cls, owner_uid, company_id, sandbox, data, user_id, declaration_id=None):
        coll = cls._collection(owner_uid, company_id, sandbox)
        if coll is None:
            raise RuntimeError("La base de datos no está disponible.")
        existing = cls.get(owner_uid, company_id, sandbox, declaration_id) if declaration_id else None
        if existing and existing.get("status") == "Presentada":
            raise ValueError("Una declaración presentada es inmutable; cree una rectificativa.")
        declaration_id = declaration_id or str(uuid.uuid4())
        if not existing and data.get("declaration_type", "Normal") == "Normal":
            for candidate in cls.list(owner_uid, company_id, sandbox):
                if candidate.get("period") == data.get("period") and candidate.get("declaration_type", "Normal") == "Normal":
                    raise ValueError("Ya existe una declaración normal para este período.")
        now = datetime.now(timezone.utc).isoformat()
        calculated = calculate_ir17(data)
        payload = _firestore_safe(dict(data))
        calculated = _firestore_safe(calculated)
        payload.update({
            "id": declaration_id,
            "company_id": company_id,
            "owner_uid": owner_uid,
            "rules_version": data.get("rules_version", IR17_RULES_VERSION),
            "status": data.get("status", existing.get("status", "Borrador") if existing else "Borrador"),
            "totals": calculated,
            "updated_at": now,
            "updated_by": user_id,
            "created_at": existing.get("created_at", now) if existing else now,
            "created_by": existing.get("created_by", user_id) if existing else user_id,
        })
        coll.document(declaration_id).set(payload)
        coll.document(declaration_id).collection("history").document(str(uuid.uuid4())).set({
            "action": "update" if existing else "create",
            "at": now,
            "by": user_id,
            "status": payload["status"],
        })
        return payload

    @classmethod
    def new_payload(cls, profile, period):
        return {
            "rnc": profile.get("companyRNC", ""),
            "razon_social": profile.get("companyName", ""),
            "nombre_comercial": profile.get("tradeName", ""),
            "telefono": profile.get("companyPhone", ""),
            "correo": profile.get("companyEmail", ""),
            "period": period,
            "declaration_type": "Normal",
            "line_items": default_line_items(),
            "conventions_amount": "0.00",
            "supplementary_benefits": "0.00",
            "supplementary_rate": "0.27",
            "authorized_credits": "0.00",
            "account_payments": "0.00",
            "prior_balance": "0.00",
            "surcharges": "0.00",
            "indemnity_interest": "0.00",
            "status": "Borrador",
            "rules_version": IR17_RULES_VERSION,
        }

    @classmethod
    def validate(cls, data):
        return validate_ir17(data)


def _firestore_safe(value):
    """Convierte resultados Decimal recursivos a valores aceptados por Firestore."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _firestore_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_firestore_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_firestore_safe(item) for item in value]
    return value
