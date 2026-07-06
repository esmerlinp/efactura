from datetime import datetime, timezone
from typing import Optional

from flask import current_app as app


class MultiCurrencyService:
    BASE_CURRENCY = "DOP"

    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @classmethod
    def get_rate(cls, currency: str, date_str: str = None) -> float:
        if currency == cls.BASE_CURRENCY:
            return 1.0

        from app.utils.currency import CurrencyService
        try:
            return CurrencyService.get_rate(currency)
        except Exception:
            pass

        if currency == "USD":
            return 58.50
        elif currency == "EUR":
            return 63.20
        return 1.0

    @classmethod
    def convert_to_base(cls, amount: float, currency: str, date_str: str = None) -> float:
        if currency == cls.BASE_CURRENCY:
            return amount
        rate = cls.get_rate(currency, date_str)
        return round(amount * rate, 2)

    @classmethod
    def save_exchange_rate(cls, currency: str, rate: float, date_str: str):
        try:
            db = cls._get_db()
            doc_id = f"{date_str or datetime.now(timezone.utc).strftime('%Y-%m-%d')}_{currency}"
            db.document(f"config/exchange_rates/{doc_id}").set({
                "currency": currency,
                "rate": rate,
                "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "createdAt": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            app.logger.warning(f"MultiCurrencyService.save_exchange_rate error: {e}")

    @classmethod
    def get_rate_history(cls, currency: str, days: int = 30) -> list:
        try:
            db = cls._get_db()
            cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            docs = db.collection("config/exchange_rates") \
                .where("currency", "==", currency) \
                .order_by("date", direction="DESCENDING") \
                .limit(days).stream()
            return [doc.to_dict() for doc in docs]
        except Exception:
            return []

    @classmethod
    def compute_unrealized_gain_loss(cls, owner_uid: str, account_id: str, current_rate: float) -> dict:
        from app.services.db_service import DatabaseService
        entries = DatabaseService.get_accounting_entries(owner_uid)

        debit = 0.0
        credit = 0.0
        for entry in entries:
            if entry.get("status") == "voided":
                continue
            for line in entry.get("lines", []):
                if line.get("accountId") == account_id:
                    debit += float(line.get("debit", 0))
                    credit += float(line.get("credit", 0))

        balance_fc = round(debit - credit, 2)
        return {
            "account_id": account_id,
            "balance_fc": balance_fc,
            "current_rate": current_rate,
            "balance_base": round(balance_fc * current_rate, 2),
        }
