from datetime import datetime, timezone
from time import sleep
from uuid import uuid4


class WebhookService:
    MAX_RETRIES = 5
    BASE_DELAY = 1.0
    MAX_DELAY = 60.0

    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @staticmethod
    def _path(owner_uid: str = None, webhook_id: str = None, company_id: str = None) -> str:
        if company_id:
            base = f"companies/{company_id}/webhooks"
        else:
            base = f"users/{owner_uid}/webhooks"
        return f"{base}/{webhook_id}" if webhook_id else base

    @staticmethod
    def _dlq_path(owner_uid: str = None, company_id: str = None) -> str:
        if company_id:
            return f"companies/{company_id}/webhooks_dlq"
        return f"users/{owner_uid}/webhooks_dlq"

    @classmethod
    def get_webhooks(cls, owner_uid: str = None, company_id: str = None) -> list:
        try:
            db = cls._get_db()
            docs = db.collection(cls._path(owner_uid=owner_uid, company_id=company_id)).stream()
            return [doc.to_dict() for doc in docs]
        except Exception:
            return []

    @classmethod
    def save_webhook(cls, owner_uid: str = None, data: dict = None, company_id: str = None) -> dict:
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
        db.document(cls._path(owner_uid=owner_uid, webhook_id=webhook_id, company_id=company_id)).set(webhook)
        return webhook

    @classmethod
    def delete_webhook(cls, owner_uid: str = None, webhook_id: str = None, company_id: str = None):
        db = cls._get_db()
        db.document(cls._path(owner_uid=owner_uid, webhook_id=webhook_id, company_id=company_id)).delete()

    @classmethod
    def _save_delivery(cls, owner_uid: str = None, webhook_id: str = None, event: str = "",
                       status: str = "", attempt: int = 0, message: str = "",
                       status_code: int = 0, company_id: str = None):
        try:
            db = cls._get_db()
            delivery = {
                "id": str(uuid4()),
                "webhookId": webhook_id,
                "event": event,
                "status": status,
                "attempt": attempt,
                "message": message,
                "statusCode": status_code,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if company_id:
                _coll_path = f"companies/{company_id}/webhook_deliveries"
            else:
                _coll_path = f"users/{owner_uid}/webhook_deliveries"
            db.collection(_coll_path).document(delivery["id"]).set(delivery)
        except Exception:
            pass

    @classmethod
    def _save_to_dlq(cls, owner_uid: str = None, webhook_id: str = None, event: str = "",
                     url: str = "", payload: dict = None, max_attempts: int = 0, company_id: str = None):
        try:
            db = cls._get_db()
            dlq = {
                "id": str(uuid4()),
                "webhookId": webhook_id,
                "event": event,
                "url": url,
                "payload": payload,
                "maxAttempts": max_attempts,
                "failedAt": datetime.now(timezone.utc).isoformat(),
                "status": "pending_retry",
            }
            db.collection(cls._dlq_path(owner_uid=owner_uid, company_id=company_id)).document(dlq["id"]).set(dlq)
        except Exception:
            pass

    @classmethod
    def dispatch(cls, owner_uid: str = None, event: str = "", payload: dict = None, company_id: str = None):
        import json
        import hmac
        import hashlib
        import urllib.request

        webhooks = cls.get_webhooks(owner_uid=owner_uid, company_id=company_id)
        for wh in webhooks:
            if wh.get("event") != event or not wh.get("active"):
                continue

            body = json.dumps(payload).encode()
            secret = wh.get("secret", "")
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            wh_id = wh["id"]
            wh_url = wh["url"]

            for attempt in range(1, cls.MAX_RETRIES + 1):
                try:
                    req = urllib.request.Request(
                        wh_url,
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Webhook-Signature": sig,
                            "Idempotency-Key": f"{wh_id}-{event}-{attempt}",
                        },
                        method="POST",
                    )
                    resp = urllib.request.urlopen(req, timeout=10)
                    cls._save_delivery(owner_uid=owner_uid, wh_id=wh_id, event=event, status="delivered",
                                       attempt=attempt, status_code=resp.status, company_id=company_id)
                    break
                except urllib.request.HTTPError as e:
                    cls._save_delivery(owner_uid=owner_uid, wh_id=wh_id, event=event, status="failed",
                                       attempt=attempt, message=str(e), status_code=e.code, company_id=company_id)
                except Exception as e:
                    cls._save_delivery(owner_uid=owner_uid, wh_id=wh_id, event=event, status="failed",
                                       attempt=attempt, message=str(e), company_id=company_id)
                if attempt < cls.MAX_RETRIES:
                    delay = min(cls.BASE_DELAY * (2 ** (attempt - 1)), cls.MAX_DELAY)
                    sleep(delay)
                else:
                    cls._save_to_dlq(owner_uid=owner_uid, wh_id=wh_id, event=event, url=wh_url,
                                     payload=payload, max_attempts=cls.MAX_RETRIES, company_id=company_id)
                    cls._save_delivery(owner_uid=owner_uid, wh_id=wh_id, event=event, status="dead_letter",
                                       attempt=attempt, message="Máximo de reintentos alcanzado", company_id=company_id)

    @classmethod
    def retry_dlq(cls, owner_uid: str = None, company_id: str = None):
        try:
            db = cls._get_db()
            docs = db.collection(cls._dlq_path(owner_uid=owner_uid, company_id=company_id)).where("status", "==", "pending_retry").stream()
            for doc in docs:
                item = doc.to_dict()
                cls.dispatch(owner_uid=owner_uid, event=item["event"], payload=item["payload"], company_id=company_id)
                db.document(cls._dlq_path(owner_uid=owner_uid, company_id=company_id)).document(doc.id).update({"status": "retried", "retriedAt": datetime.now(timezone.utc).isoformat()})
        except Exception:
            pass
