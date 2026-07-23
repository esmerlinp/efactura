from datetime import datetime, timezone
from uuid import uuid4
from flask import current_app as app
class LedgerAuditService:
    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @staticmethod
    def _audit_path(owner_uid: str, entry_id: str, audit_id: str = None, company_id=None):
        if company_id:
            base = f"companies/{company_id}/journal_entry_audit/{entry_id}"
        else:
            base = f"users/{owner_uid}/journal_entry_audit/{entry_id}"
        if audit_id:
            return f"{base}/changes/{audit_id}"
        return base

    @staticmethod
    def log_entry_creation(entry: dict, owner_uid: str, performed_by: str = "", company_id=None):
        try:
            db = LedgerAuditService._get_db()
            entry_id = entry.get('id', '')
            if not entry_id:
                return

            audit_id = str(uuid4())
            doc_ref = db.document(LedgerAuditService._audit_path(owner_uid, entry_id, audit_id, company_id=company_id))
            doc_ref.set({
                "action": "CREATE",
                "entry_id": entry_id,
                "entry_number": entry.get('number', ''),
                "performed_by": performed_by,
                "snapshot": LedgerAuditService._sanitize_entry(entry),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            app.logger.warning(f"LedgerAuditService.log_entry_creation error: {e}")

    @staticmethod
    def log_entry_update(old_entry: dict, new_entry: dict, owner_uid: str, performed_by: str = "", company_id=None):
        try:
            db = LedgerAuditService._get_db()
            entry_id = old_entry.get('id', '')
            if not entry_id:
                return

            diff = LedgerAuditService._compute_diff(old_entry, new_entry)
            if not diff:
                return

            audit_id = str(uuid4())
            doc_ref = db.document(LedgerAuditService._audit_path(owner_uid, entry_id, audit_id, company_id=company_id))
            doc_ref.set({
                "action": "UPDATE",
                "entry_id": entry_id,
                "entry_number": new_entry.get('number', ''),
                "performed_by": performed_by,
                "before": diff.get("before", {}),
                "after": diff.get("after", {}),
                "changed_fields": diff.get("changed_fields", []),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            app.logger.warning(f"LedgerAuditService.log_entry_update error: {e}")

    @staticmethod
    def log_entry_void(entry: dict, owner_uid: str, performed_by: str = "", reason: str = "", company_id=None):
        try:
            db = LedgerAuditService._get_db()
            entry_id = entry.get('id', '')
            if not entry_id:
                return

            audit_id = str(uuid4())
            doc_ref = db.document(LedgerAuditService._audit_path(owner_uid, entry_id, audit_id, company_id=company_id))
            doc_ref.set({
                "action": "VOID",
                "entry_id": entry_id,
                "entry_number": entry.get('number', ''),
                "performed_by": performed_by,
                "reason": reason,
                "snapshot": LedgerAuditService._sanitize_entry(entry),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            app.logger.warning(f"LedgerAuditService.log_entry_void error: {e}")

    @staticmethod
    def get_entry_audit_log(owner_uid: str, entry_id: str, company_id=None) -> list:
        try:
            db = LedgerAuditService._get_db()
            docs = db.collection(LedgerAuditService._audit_path(owner_uid, entry_id, company_id=company_id) + "/changes") \
                .order_by("timestamp", direction="DESCENDING") \
                .stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            app.logger.warning(f"LedgerAuditService.get_entry_audit_log error: {e}")
            return []

    @staticmethod
    def _sanitize_entry(entry: dict) -> dict:
        return {
            "id": entry.get("id", ""),
            "number": entry.get("number", ""),
            "entryType": entry.get("entryType", ""),
            "date": entry.get("date", ""),
            "concept": entry.get("concept", ""),
            "totalDebit": entry.get("totalDebit", 0.0),
            "totalCredit": entry.get("totalCredit", 0.0),
            "isBalanced": entry.get("isBalanced", True),
            "status": entry.get("status", "active"),
            "line_count": len(entry.get("lines", [])),
            "lines": [
                {
                    "accountCode": line.get("accountCode", ""),
                    "accountName": line.get("accountName", ""),
                    "debit": line.get("debit", 0.0),
                    "credit": line.get("credit", 0.0),
                    "description": line.get("description", ""),
                }
                for line in entry.get("lines", [])
            ],
        }

    @staticmethod
    def _compute_diff(old: dict, new: dict) -> dict:
        before = {}
        after = {}
        changed = []
        all_keys = set(list(old.keys()) + list(new.keys()))
        skip_keys = {"updatedAt", "createdAt"}

        for key in all_keys:
            if key in skip_keys:
                continue
            old_val = old.get(key)
            new_val = new.get(key)
            if key == "lines":
                old_lines = LedgerAuditService._sanitize_lines(old_val or [])
                new_lines = LedgerAuditService._sanitize_lines(new_val or [])
                if old_lines != new_lines:
                    before["lines"] = old_lines
                    after["lines"] = new_lines
                    changed.append("lines")
            elif old_val != new_val:
                before[key] = old_val
                after[key] = new_val
                changed.append(key)

        if not changed:
            return {}
        return {"before": before, "after": after, "changed_fields": changed}

    @staticmethod
    def _sanitize_lines(lines: list) -> list:
        return [
            {
                "accountCode": line.get("accountCode", ""),
                "accountName": line.get("accountName", ""),
                "debit": line.get("debit", 0.0),
                "credit": line.get("credit", 0.0),
                "description": line.get("description", ""),
            }
            for line in lines
        ]
