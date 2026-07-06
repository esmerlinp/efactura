from datetime import datetime, timezone
from uuid import uuid4


class BudgetService:
    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @staticmethod
    def _path(owner_uid: str, year: int) -> str:
        return f"users/{owner_uid}/budgets/{year}"

    @classmethod
    def get_budget(cls, owner_uid: str, year: int) -> dict:
        try:
            db = cls._get_db()
            doc = db.document(cls._path(owner_uid, year)).get()
            if doc.exists:
                return doc.to_dict()
        except Exception:
            pass
        return {"year": year, "months": {}}

    @classmethod
    def save_budget(cls, owner_uid: str, year: int, budget_data: dict) -> dict:
        db = cls._get_db()
        budget = {
            "year": year,
            "months": budget_data.get("months", {}),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "updatedBy": budget_data.get("updatedBy", ""),
        }
        db.document(cls._path(owner_uid, year)).set(budget)
        return budget

    @classmethod
    def get_variance(cls, owner_uid: str, year: int, month: int) -> dict:
        from app.services.db_service import DatabaseService

        budget = cls.get_budget(owner_uid, year)
        month_key = str(month)
        month_budget = budget.get("months", {}).get(month_key, {})

        expenses = DatabaseService.get_expenses(owner_uid)
        actuals = {}
        for exp in expenses:
            try:
                date_str = exp.get("date", "")
                if "T" in date_str:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                if dt.year == year and dt.month == month:
                    code = exp.get("category", "otros")
                    actuals[code] = actuals.get(code, 0.0) + float(exp.get("amount", 0.0))
            except Exception:
                continue

        variance = {}
        for code, amount in month_budget.items():
            actual = actuals.get(code, 0.0)
            variance[code] = {
                "budget": amount,
                "actual": round(actual, 2),
                "variance": round(actual - amount, 2),
                "pct_used": round(actual / amount * 100, 1) if amount > 0 else 0,
            }
        return variance
