"""Persistencia transaccional de documentos internos."""

import hashlib
import uuid
from datetime import datetime, timezone

from app.services.db_service import db_firestore, firebase_initialized, _company_coll

try:
    from google.cloud.firestore_v1 import transactional
except ImportError:  # pragma: no cover - Firebase is required in production
    transactional = lambda fn: fn


class InternalServiceDocumentRepository:
    COLLECTION = "internal_service_documents"
    COUNTER = "internal_service_document_counter"
    IDEMPOTENCY = "internal_service_document_idempotency"

    @classmethod
    def _name(cls, base: str, sandbox: bool) -> str:
        return f"sandbox_{base}" if sandbox else base

    @classmethod
    def collection(cls, company_id, sandbox):
        return _company_coll(company_id=company_id, coll_name=cls._name(cls.COLLECTION, sandbox))

    @classmethod
    def get(cls, company_id, document_id, sandbox):
        if not firebase_initialized:
            return None
        ref = cls.collection(company_id, sandbox).document(document_id)
        doc = ref.get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["id"] = doc.id
        return data

    @classmethod
    def list(cls, company_id, sandbox):
        if not firebase_initialized:
            return []
        result = []
        for doc in cls.collection(company_id, sandbox).stream():
            data = doc.to_dict() or {}
            data["id"] = doc.id
            result.append(data)
        return result

    @classmethod
    def create_transactional(cls, company_id, sandbox, payload, idempotency_key):
        if not firebase_initialized:
            raise RuntimeError("Firestore no está disponible.")
        if not company_id:
            raise ValueError("La empresa activa es obligatoria.")
        transaction = db_firestore.transaction()
        document_id = str(uuid.uuid4())
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        docs = cls.collection(company_id, sandbox)
        counter = _company_coll(company_id=company_id, coll_name=cls._name(cls.COUNTER, sandbox)).document("current")
        idem = _company_coll(company_id=company_id, coll_name=cls._name(cls.IDEMPOTENCY, sandbox)).document(key_hash)

        @transactional
        def run(txn):
            existing_idem = idem.get(transaction=txn)
            if existing_idem.exists:
                existing_id = (existing_idem.to_dict() or {}).get("documentId")
                existing = docs.document(existing_id).get(transaction=txn)
                if existing.exists:
                    result = existing.to_dict() or {}
                    result["id"] = existing.id
                    result["idempotentHit"] = True
                    return result

            counter_doc = counter.get(transaction=txn)
            next_number = int((counter_doc.to_dict() or {}).get("next", 1)) if counter_doc.exists else 1
            now = datetime.now(timezone.utc).isoformat()
            record = dict(payload)
            record.update({
                "id": document_id,
                "documentNumber": f"DISG-{next_number:06d}",
                "sequenceNumber": next_number,
                "createdAt": now,
                "updatedAt": now,
            })
            txn.create(docs.document(document_id), record)
            txn.set(counter, {"next": next_number + 1, "updatedAt": now})
            txn.create(idem, {
                "id": key_hash,
                "idempotencyKey": idempotency_key,
                "documentId": document_id,
                "createdAt": now,
            })
            return record

        return run(transaction)

    @classmethod
    def void(cls, company_id, document_id, sandbox, reason, actor):
        if not firebase_initialized:
            raise RuntimeError("Firestore no está disponible.")
        ref = cls.collection(company_id, sandbox).document(document_id)
        doc = ref.get()
        if not doc.exists:
            return None
        current = doc.to_dict() or {}
        if current.get("persistedState") == "voided":
            return current
        now = datetime.now(timezone.utc).isoformat()
        update = {
            "persistedState": "voided",
            "cancelReason": reason,
            "cancelledBy": actor.get("name", ""),
            "cancelledByEmail": actor.get("email", ""),
            "cancelledAt": now,
            "updatedAt": now,
        }
        ref.update(update)
        current.update(update)
        return current
