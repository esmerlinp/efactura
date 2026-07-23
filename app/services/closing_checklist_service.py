from datetime import datetime, timezone
from uuid import uuid4


class ClosingChecklistService:
    DEFAULT_TASKS = [
        {"id": "reconcile_banks", "label": "Conciliar cuentas bancarias", "category": "bancos"},
        {"id": "review_ar", "label": "Revisar aging de cuentas por cobrar", "category": "cxc"},
        {"id": "review_ap", "label": "Revisar aging de cuentas por pagar", "category": "cxp"},
        {"id": "depreciate_assets", "label": "Ejecutar depreciación de activos fijos", "category": "activos"},
        {"id": "accrue_expenses", "label": "Registrar gastos devengados", "category": "ajustes"},
        {"id": "review_inventory", "label": "Revisar valuación de inventario", "category": "inventario"},
        {"id": "review_trial_balance", "label": "Revisar balanza de comprobación", "category": "contabilidad"},
        {"id": "post_adjustments", "label": "Registrar asientos de ajuste", "category": "ajustes"},
        {"id": "review_taxes", "label": "Revisar impuestos por pagar (ITBIS, ISR)", "category": "impuestos"},
        {"id": "close_period", "label": "Cerrar período fiscal", "category": "cierre"},
    ]

    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @staticmethod
    def _path(owner_uid: str, key: str = None, company_id: str = None) -> str:
        if company_id:
            base = f"companies/{company_id}/closing_checklists"
        else:
            base = f"users/{owner_uid}/closing_checklists"
        return f"{base}/{key}" if key else base

    @classmethod
    def get_or_create_checklist(cls, owner_uid: str, year: int, month: int, company_id: str = None) -> dict:
        db = cls._get_db()
        key = f"{year}-{month:02d}"
        doc = db.document(cls._path(owner_uid, key, company_id=company_id)).get()
        if doc.exists:
            data = doc.to_dict()
            return data

        tasks = []
        for t in cls.DEFAULT_TASKS:
            tasks.append({**t, "completed": False, "completedAt": None, "completedBy": None, "notes": ""})

        checklist = {
            "id": key,
            "year": year,
            "month": month,
            "tasks": tasks,
            "progress": 0,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        db.document(cls._path(owner_uid, key, company_id=company_id)).set(checklist)
        return checklist

    @classmethod
    def toggle_task(cls, owner_uid: str, year: int, month: int, task_id: str, completed_by: str = "", company_id: str = None) -> dict:
        checklist = cls.get_or_create_checklist(owner_uid, year, month, company_id=company_id)
        for task in checklist["tasks"]:
            if task["id"] == task_id:
                task["completed"] = not task["completed"]
                task["completedAt"] = datetime.now(timezone.utc).isoformat() if task["completed"] else None
                task["completedBy"] = completed_by if task["completed"] else None
                break

        completed = sum(1 for t in checklist["tasks"] if t["completed"])
        total = len(checklist["tasks"])
        checklist["progress"] = round(completed / total * 100, 1) if total > 0 else 0
        checklist["updatedAt"] = datetime.now(timezone.utc).isoformat()

        db = cls._get_db()
        db.document(cls._path(owner_uid, checklist["id"], company_id=company_id)).set(checklist)
        return checklist

    @classmethod
    def update_task_note(cls, owner_uid: str, year: int, month: int, task_id: str, notes: str, company_id: str = None) -> dict:
        checklist = cls.get_or_create_checklist(owner_uid, year, month, company_id=company_id)
        for task in checklist["tasks"]:
            if task["id"] == task_id:
                task["notes"] = notes
                break
        checklist["updatedAt"] = datetime.now(timezone.utc).isoformat()
        db = cls._get_db()
        db.document(cls._path(owner_uid, checklist["id"], company_id=company_id)).set(checklist)
        return checklist
