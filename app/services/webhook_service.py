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
    def _path(owner_uid: str, webhook_id: str = None) -> str:
        base = f"users/{owner_uid}/webhooks"
        return f"{base}/{webhook_id}" if webhook_id else base

    @staticmethod
    def _dlq_path(owner_uid: str) -> str:
        return f"users/{owner_uid}/webhooks_dlq"

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
    def _save_delivery(cls, owner_uid: str, webhook_id: str, event: str,
                       status: str, attempt: int, message: str = "",
                       status_code: int = 0):
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
            db.collection(f"users/{owner_uid}/webhook_deliveries").document(delivery["id"]).set(delivery)
        except Exception:
            pass

    @classmethod
    def _save_to_dlq(cls, owner_uid: str, webhook_id: str, event: str,
                     url: str, payload: dict, max_attempts: int):
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
            db.collection(cls._dlq_path(owner_uid)).document(dlq["id"]).set(dlq)
        except Exception:
            pass

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
                    cls._save_delivery(owner_uid, wh_id, event, "delivered",
                                       attempt, status_code=resp.status)
                    break
                except urllib.request.HTTPError as e:
                    cls._save_delivery(owner_uid, wh_id, event, "failed",
                                       attempt, str(e), status_code=e.code)
                except Exception as e:
                    cls._save_delivery(owner_uid, wh_id, event, "failed",
                                       attempt, str(e))
                if attempt < cls.MAX_RETRIES:
                    delay = min(cls.BASE_DELAY * (2 ** (attempt - 1)), cls.MAX_DELAY)
                    sleep(delay)
                else:
                    cls._save_to_dlq(owner_uid, wh_id, event, wh_url,
                                     payload, cls.MAX_RETRIES)
                    cls._save_delivery(owner_uid, wh_id, event, "dead_letter",
                                       attempt, "Máximo de reintentos alcanzado")

    @classmethod
    def retry_dlq(cls, owner_uid: str):
        try:
            db = cls._get_db()
            docs = db.collection(cls._dlq_path(owner_uid)).where("status", "==", "pending_retry").stream()
            for doc in docs:
                item = doc.to_dict()
                cls.dispatch(owner_uid, item["event"], item["payload"])
                db.document(cls._dlq_path(owner_uid)).document(doc.id).update({"status": "retried", "retriedAt": datetime.now(timezone.utc).isoformat()})
        except Exception:
            pass
