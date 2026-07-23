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
    def compute_unrealized_gain_loss(cls, owner_uid: str, account_id: str, current_rate: float, company_id=None) -> dict:
        from app.services.db_service import DatabaseService
        entries = DatabaseService.get_accounting_entries(owner_uid, company_id=company_id)

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

    @classmethod
    def generate_revaluation_entries(cls, owner_uid: str, new_rate: float = None,
                                       currency: str = "USD", sandbox: bool = True, company_id=None) -> dict:
        from app.services.db_service import DatabaseService
        from app.services.accounting_service import AccountingService

        if new_rate is None:
            new_rate = cls.get_rate(currency)
        old_rate = cls.get_rate(currency)

        entries = DatabaseService.get_accounting_entries(owner_uid, company_id=company_id)
        accounts = DatabaseService.get_chart_of_accounts(owner_uid, company_id=company_id)
        account_map = {a["id"]: a for a in accounts}

        gain_account = next((a for a in accounts if a.get("code") == "4.2.3"), None)
        loss_account = next((a for a in accounts if a.get("code") == "6.4.02"), None)
        if not gain_account or not loss_account:
            return {"error": "Cuentas de ganancia/pérdida por diferencia en cambio no encontradas"}

        foreign_accounts = {}
        for entry in entries:
            if entry.get("status") == "voided":
                continue
            for line in entry.get("lines", []):
                acc_id = line.get("accountId", "")
                acc_currency = line.get("currency", "")
                if acc_currency and acc_currency != cls.BASE_CURRENCY and acc_id not in foreign_accounts:
                    foreign_accounts[acc_id] = acc_currency

        if not foreign_accounts:
            return {"entries": [], "note": "No hay cuentas en moneda extranjera"}

        generated_entries = []
        for acc_id, acc_currency in foreign_accounts.items():
            balance_fc = 0.0
            for entry in entries:
                if entry.get("status") == "voided":
                    continue
                for line in entry.get("lines", []):
                    if line.get("accountId") == acc_id:
                        balance_fc += float(line.get("debit", 0)) - float(line.get("credit", 0))

            if abs(balance_fc) < 0.01:
                continue

            current_value = round(balance_fc * new_rate, 2)
            previous_value = round(balance_fc * old_rate, 2)
            diff = round(current_value - previous_value, 2)

            if abs(diff) < 0.01:
                continue

            acc_info = account_map.get(acc_id, {})
            lines = []
            if diff > 0:
                lines.append({"accountId": acc_id, "accountCode": acc_info.get("code", ""),
                              "accountName": acc_info.get("name", ""),
                              "debit": diff, "credit": 0.00,
                              "description": f"Revaluación {acc_currency} → DOP a tasa {new_rate}"})
                lines.append({"accountId": gain_account["id"], "accountCode": gain_account["code"],
                              "accountName": gain_account["name"],
                              "debit": 0.00, "credit": diff,
                              "description": f"Ganancia por diferencia en cambio {acc_currency}"})
            else:
                abs_diff = abs(diff)
                lines.append({"accountId": loss_account["id"], "accountCode": loss_account["code"],
                              "accountName": loss_account["name"],
                              "debit": abs_diff, "credit": 0.00,
                              "description": f"Pérdida por diferencia en cambio {acc_currency}"})
                lines.append({"accountId": acc_id, "accountCode": acc_info.get("code", ""),
                              "accountName": acc_info.get("name", ""),
                              "debit": 0.00, "credit": abs_diff,
                              "description": f"Revaluación {acc_currency} → DOP a tasa {new_rate}"})

            try:
                entry = AccountingService.generate_entry(company_id, {
                    "entryType": "adjustment",
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "concept": f"Revaluación cambiaria {acc_currency} a tasa {new_rate} — diferencia RD$ {abs(diff):,.2f}",
                    "referenceType": "currency_revaluation",
                    "referenceId": f"{acc_id}-rev",
                    "referenceNumber": acc_currency,
                    "lines": lines,
                    "createdBy": "system",
                }, sandbox=sandbox)
                generated_entries.append(entry)
            except Exception as e:
                print(f"Error generando revaluación para {acc_id}: {e}")

        return {"entries": generated_entries, "note": f"Revaluación completada a tasa {new_rate}"}
