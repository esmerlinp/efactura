from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


class ApprovalService:
    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @staticmethod
    def _path(owner_uid: str, rule_id: str = None) -> str:
        base = f"users/{owner_uid}/approval_rules"
        return f"{base}/{rule_id}" if rule_id else base

    @classmethod
    def get_rules(cls, owner_uid: str) -> list:
        try:
            db = cls._get_db()
            docs = db.collection(cls._path(owner_uid)).stream()
            return [doc.to_dict() for doc in docs]
        except Exception:
            return []

    @classmethod
    def save_rule(cls, owner_uid: str, rule_data: dict) -> dict:
        db = cls._get_db()
        rule_id = rule_data.get("id") or str(uuid4())
        rule = {
            "id": rule_id,
            "document_type": rule_data.get("document_type", "expense"),
            "min_amount": float(rule_data.get("min_amount", 0)),
            "approvers": rule_data.get("approvers", []),
            "require_all": bool(rule_data.get("require_all", True)),
            "is_active": bool(rule_data.get("is_active", True)),
            "createdAt": rule_data.get("createdAt") or datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        db.document(cls._path(owner_uid, rule_id)).set(rule)
        return rule

    @classmethod
    def delete_rule(cls, owner_uid: str, rule_id: str):
        db = cls._get_db()
        db.document(cls._path(owner_uid, rule_id)).delete()

    @classmethod
    def check_needs_approval(cls, owner_uid: str, doc_type: str, amount: float) -> tuple:
        rules = cls.get_rules(owner_uid)
        applicable = [r for r in rules if r.get("document_type") == doc_type and r.get("is_active")]
        for rule in applicable:
            if amount >= float(rule.get("min_amount", 0)):
                return True, rule
        return False, None

    @classmethod
    def create_approval_request(cls, owner_uid: str, doc_type: str, doc_id: str,
                                 doc_number: str, amount: float, requestor: str):
        db = cls._get_db()
        needs_approval, rule = cls.check_needs_approval(owner_uid, doc_type, amount)
        if not needs_approval:
            return None

        request_id = str(uuid4())
        approvers = rule.get("approvers", [])
        steps = [{"approver_id": a.get("id"), "approver_name": a.get("name"),
                   "approver_email": a.get("email"), "status": "pending",
                   "decided_at": None, "comment": ""}
                 for a in approvers]

        request = {
            "id": request_id,
            "document_type": doc_type,
            "document_id": doc_id,
            "document_number": doc_number,
            "amount": amount,
            "requestor": requestor,
            "rule_id": rule.get("id"),
            "require_all": rule.get("require_all", True),
            "steps": steps,
            "status": "pending",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        db.document(f"users/{owner_uid}/approval_requests/{request_id}").set(request)
        return request_id

    @classmethod
    def get_pending_approvals(cls, owner_uid: str, approver_id: str) -> list:
        try:
            db = cls._get_db()
            docs = db.collection(f"users/{owner_uid}/approval_requests") \
                .where("status", "==", "pending").stream()
            pending = []
            for doc in docs:
                data = doc.to_dict()
                for step in data.get("steps", []):
                    if step.get("approver_id") == approver_id and step.get("status") == "pending":
                        pending.append(data)
                        break
            return pending
        except Exception:
            return []

    @classmethod
    def decide_approval(cls, owner_uid: str, request_id: str, approver_id: str,
                         approved: bool, comment: str = "") -> dict:
        db = cls._get_db()
        doc = db.document(f"users/{owner_uid}/approval_requests/{request_id}").get()
        if not doc.exists:
            return {"success": False, "error": "Solicitud no encontrada"}

        data = doc.to_dict()
        all_approved = True
        any_rejected = False

        for step in data.get("steps", []):
            if step.get("approver_id") == approver_id and step.get("status") == "pending":
                step["status"] = "approved" if approved else "rejected"
                step["decided_at"] = datetime.now(timezone.utc).isoformat()
                step["comment"] = comment
            if step.get("status") == "rejected":
                any_rejected = True
            if step.get("status") != "approved":
                all_approved = False

        if any_rejected:
            data["status"] = "rejected"
        elif all_approved:
            data["status"] = "approved"

        data["updatedAt"] = datetime.now(timezone.utc).isoformat()
        db.document(f"users/{owner_uid}/approval_requests/{request_id}").set(data)

        return {"success": True, "status": data["status"]}
