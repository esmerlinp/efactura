from datetime import datetime, timezone
from uuid import uuid4


class WebhookService:
    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @staticmethod
    def _path(owner_uid: str, webhook_id: str = None) -> str:
        base = f"users/{owner_uid}/webhooks"
        return f"{base}/{webhook_id}" if webhook_id else base

    @classmethod
    def get_webhooks(cls, owner_uid: str) -> list:
        try:
            db = cls._get_db()
            docs = db.collection(cls._path(owner_uid)).stream()
            return [doc.to_dict() for doc in docs]
        except Exception:
            return []

    @classmethod
    def save_webhook(cls, owner_uid: str, data: dict) -> dict:
        db = cls._get_db()
        webhook_id = data.get("id") or str(uuid4())
        webhook = {
            "id": webhook_id,
            "event": data.get("event", ""),
            "url": data.get("url", ""),
            "secret": data.get("secret", str(uuid4())[:16]),
            "active": data.get("active", True),
            "createdAt": data.get("createdAt") or datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        db.document(cls._path(owner_uid, webhook_id)).set(webhook)
        return webhook

    @classmethod
    def delete_webhook(cls, owner_uid: str, webhook_id: str):
        db = cls._get_db()
        db.document(cls._path(owner_uid, webhook_id)).delete()

    @classmethod
    def dispatch(cls, owner_uid: str, event: str, payload: dict):
        import json
        import hmac
        import hashlib
        import urllib.request

        webhooks = cls.get_webhooks(owner_uid)
        for wh in webhooks:
            if wh.get("event") != event or not wh.get("active"):
                continue
            try:
                body = json.dumps(payload).encode()
                secret = wh.get("secret", "")
                sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
                req = urllib.request.Request(
                    wh["url"],
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": sig,
                    },
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
