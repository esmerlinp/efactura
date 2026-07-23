from datetime import datetime, timezone


BUDGET_CATEGORY_LABELS = {
    "compras": "Compras / Costo de ventas",
    "nomina": "Nómina",
    "alquiler": "Alquiler",
    "servicios": "Servicios públicos",
    "marketing": "Marketing y ventas",
    "transporte": "Transporte",
    "tecnologia": "Tecnología",
    "impuestos": "Impuestos y tasas",
    "financieros": "Gastos financieros",
    "otros": "Otros gastos",
}


class BudgetService:
    @staticmethod
    def _get_db():
        try:
            from app.services.db_service import db_firestore, firebase_initialized
            if firebase_initialized:
                return db_firestore
        except Exception:
            pass
        return None

    @staticmethod
    def _path(owner_uid: str = None, year: int = 0, company_id: str = None) -> str:
        if company_id:
            return f"companies/{company_id}/budgets/{year}"
        return f"users/{owner_uid}/budgets/{year}"

    @staticmethod
    def _parse_amount(value) -> float:
        try:
            return round(float(str(value or 0).replace(",", "")), 2)
        except Exception:
            return 0.0

    @classmethod
    def get_categories(cls) -> list:
        return [{"code": code, "label": label} for code, label in BUDGET_CATEGORY_LABELS.items()]

    @classmethod
    def normalise_budget(cls, year: int, budget: dict) -> dict:
        months = {}
        raw_months = budget.get("months", {}) if budget else {}
        for month in range(1, 13):
            month_key = str(month)
            raw_values = raw_months.get(month_key, {})
            months[month_key] = {
                code: cls._parse_amount(raw_values.get(code, 0))
                for code in BUDGET_CATEGORY_LABELS
            }
        return {
            "year": int(budget.get("year", year) if budget else year),
            "months": months,
            "updatedAt": budget.get("updatedAt", "") if budget else "",
            "updatedBy": budget.get("updatedBy", "") if budget else "",
        }

    @classmethod
    def get_budget(cls, owner_uid: str = None, year: int = 0, branch_id=None, project_id=None, company_id: str = None) -> dict:
        db = cls._get_db()
        if db:
            try:
                doc = db.document(cls._path(owner_uid=owner_uid, year=year, company_id=company_id)).get()
                if doc.exists:
                    data = doc.to_dict()
                    budget = cls.normalise_budget(year, data)
                    budget["branchId"] = data.get("branchId", "default-sucursal-principal")
                    budget["projectId"] = data.get("projectId")
                    return budget
            except Exception:
                pass
        return cls.normalise_budget(year, {"year": year, "months": {}})

    @classmethod
    def save_budget(cls, owner_uid: str = None, year: int = 0, budget_data: dict = None, company_id: str = None) -> dict:
        db = cls._get_db()
        budget = cls.normalise_budget(year, {"year": year, "months": budget_data.get("months", {})})
        budget["updatedAt"] = datetime.now(timezone.utc).isoformat()
        budget["updatedBy"] = budget_data.get("updatedBy", "")
        budget["branchId"] = budget_data.get("branchId", "default-sucursal-principal")
        budget["projectId"] = budget_data.get("projectId", None)
        if db:
            db.document(cls._path(owner_uid=owner_uid, year=year, company_id=company_id)).set(budget)
        return budget

    @staticmethod
    def _parse_date(date_str: str):
        try:
            if not date_str:
                return None
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return datetime.strptime(date_str[:10], "%Y-%m-%d")
        except Exception:
            return None

    @classmethod
    def _category_for_expense(cls, expense: dict) -> str:
        raw = (expense.get("budgetCategory") or expense.get("category") or "").strip().lower()
        aliases = {
            "compra": "compras",
            "compras": "compras",
            "costo": "compras",
            "costo de ventas": "compras",
            "nomina": "nomina",
            "nómina": "nomina",
            "sueldos": "nomina",
            "alquiler": "alquiler",
            "renta": "alquiler",
            "servicio": "servicios",
            "servicios": "servicios",
            "luz": "servicios",
            "agua": "servicios",
            "telefono": "servicios",
            "teléfono": "servicios",
            "marketing": "marketing",
            "publicidad": "marketing",
            "transporte": "transporte",
            "combustible": "transporte",
            "tecnologia": "tecnologia",
            "tecnología": "tecnologia",
            "software": "tecnologia",
            "impuesto": "impuestos",
            "impuestos": "impuestos",
            "financiero": "financieros",
            "financieros": "financieros",
            "banco": "financieros",
            "otros": "otros",
        }
        return aliases.get(raw, raw if raw in BUDGET_CATEGORY_LABELS else "otros")

    @classmethod
    def get_variance(cls, owner_uid: str = None, year: int = 0, month: int = 0, sandbox: bool = True, company_id: str = None) -> dict:
        from app.services.db_service import DatabaseService

        budget = cls.get_budget(owner_uid=owner_uid, year=year, company_id=company_id)
        month_key = str(month)
        month_budget = budget.get("months", {}).get(month_key, {})

        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, company_id=company_id)
        actuals = {code: 0.0 for code in BUDGET_CATEGORY_LABELS}
        for exp in expenses:
            dt = cls._parse_date(exp.get("date", ""))
            if not dt or dt.year != year or dt.month != month:
                continue
            code = cls._category_for_expense(exp)
            actuals[code] = actuals.get(code, 0.0) + float(exp.get("amount", 0.0))

        variance = {}
        for code, label in BUDGET_CATEGORY_LABELS.items():
            planned = cls._parse_amount(month_budget.get(code, 0.0))
            actual = round(actuals.get(code, 0.0), 2)
            delta = round(actual - planned, 2)
            pct_used = round(actual / planned * 100, 1) if planned > 0 else (100.0 if actual > 0 else 0.0)
            variance[code] = {
                "code": code,
                "label": label,
                "budget": planned,
                "actual": actual,
                "variance": delta,
                "pct_used": pct_used,
                "status": "over" if planned > 0 and actual > planned else "ok",
            }
        return variance

    @classmethod
    def get_year_variance(cls, owner_uid: str = None, year: int = 0, sandbox: bool = True, company_id: str = None) -> dict:
        months = {}
        totals = {
            "budget": 0.0,
            "actual": 0.0,
            "variance": 0.0,
            "over_categories": 0,
        }
        for month in range(1, 13):
            variance = cls.get_variance(owner_uid=owner_uid, year=year, month=month, sandbox=sandbox, company_id=company_id)
            month_budget = sum(v["budget"] for v in variance.values())
            month_actual = sum(v["actual"] for v in variance.values())
            months[str(month)] = {
                "month": month,
                "budget": round(month_budget, 2),
                "actual": round(month_actual, 2),
                "variance": round(month_actual - month_budget, 2),
                "pct_used": round(month_actual / month_budget * 100, 1) if month_budget > 0 else 0,
                "categories": variance,
            }
            totals["budget"] += month_budget
            totals["actual"] += month_actual
            totals["over_categories"] += sum(1 for v in variance.values() if v["status"] == "over")

        totals["budget"] = round(totals["budget"], 2)
        totals["actual"] = round(totals["actual"], 2)
        totals["variance"] = round(totals["actual"] - totals["budget"], 2)
        totals["pct_used"] = round(totals["actual"] / totals["budget"] * 100, 1) if totals["budget"] > 0 else 0
        return {"year": year, "months": months, "totals": totals}
