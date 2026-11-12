import re
import uuid
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

from app.services.db_service import db_firestore, firebase_initialized


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CustomerAccountService:
    COLLECTION = "customer_accounts"

    @staticmethod
    def normalize_rnc(value):
        return "".join(char for char in str(value or "") if char.isalnum()).lower()

    @staticmethod
    def normalize_email(value):
        return str(value or "").strip().lower()

    @classmethod
    def valid_email(cls, value):
        return bool(EMAIL_RE.match(cls.normalize_email(value)))

    @classmethod
    def ensure_for_contact(cls, contact, owner_uid, company_id, sandbox):
        """Create/update the global account and its company membership."""
        if not firebase_initialized or db_firestore is None:
            return None
        rnc = cls.normalize_rnc(contact.get("rnc"))
        email = cls.normalize_email(contact.get("email"))
        if "cliente" not in (contact.get("types") or []) or not rnc:
            return None
        if not cls.valid_email(email):
            raise ValueError("El correo electrónico del cliente es obligatorio y debe ser válido.")

        account_ref = db_firestore.collection(cls.COLLECTION)
        account = None
        account_id = None
        matches = account_ref.where("rncNormalized", "==", rnc).limit(1).stream()
        for doc in matches:
            account = doc.to_dict() or {}
            account_id = doc.id
            break

        now = datetime.now(timezone.utc).isoformat()
        if not account:
            account_id = str(uuid.uuid4())
            account = {
                "rnc": str(contact.get("rnc") or "").strip(),
                "rncNormalized": rnc,
                "legalName": contact.get("razonSocial", ""),
                "email": email,
                "emailNormalized": email,
                "passwordHash": generate_password_hash(rnc),
                "mustChangePassword": True,
                "status": "active",
                "createdAt": now,
                "updatedAt": now,
            }
            account_ref.document(account_id).set(account)
        else:
            account_ref.document(account_id).set({
                "legalName": contact.get("razonSocial", ""),
                "email": email,
                "emailNormalized": email,
                "updatedAt": now,
            }, merge=True)

        membership_id = f"{company_id}_{contact['id']}_{int(bool(sandbox))}"
        account_ref.document(account_id).collection("memberships").document(membership_id).set({
            "ownerUid": owner_uid,
            "companyId": company_id,
            "clientId": contact["id"],
            "sandbox": bool(sandbox),
            "status": "active",
            "updatedAt": now,
        }, merge=True)
        return account_id
