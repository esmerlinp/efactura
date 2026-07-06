from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from flask import current_app as app


class FiscalPeriodService:
    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @staticmethod
    def _path(owner_uid: str, period_id: str = None) -> str:
        base = f"users/{owner_uid}/fiscal_periods"
        if period_id:
            return f"{base}/{period_id}"
        return base

    @staticmethod
    def _period_key(year: int, month: int) -> str:
        return f"{year}-{month:02d}"

    @classmethod
    def get_period(cls, owner_uid: str, year: int, month: int) -> Optional[dict]:
        try:
            db = cls._get_db()
            doc = db.document(cls._path(owner_uid, cls._period_key(year, month))).get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            app.logger.warning(f"FiscalPeriodService.get_period error: {e}")
        return None

    @classmethod
    def ensure_period_exists(cls, owner_uid: str, year: int, month: int) -> dict:
        existing = cls.get_period(owner_uid, year, month)
        if existing:
            return existing
        period = {
            "id": cls._period_key(year, month),
            "year": year,
            "month": month,
            "status": "open",
            "closedAt": None,
            "closedBy": None,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        try:
            db = cls._get_db()
            db.document(cls._path(owner_uid, period["id"])).set(period)
        except Exception as e:
            app.logger.warning(f"FiscalPeriodService.ensure_period_exists error: {e}")
        return period

    @classmethod
    def close_period(cls, owner_uid: str, year: int, month: int, closed_by: str = "") -> dict:
        period = cls.ensure_period_exists(owner_uid, year, month)
        if period["status"] == "closed":
            raise ValueError(f"El período {year}-{month:02d} ya está cerrado.")

        period["status"] = "closed"
        period["closedAt"] = datetime.now(timezone.utc).isoformat()
        period["closedBy"] = closed_by

        try:
            db = cls._get_db()
            db.document(cls._path(owner_uid, period["id"])).set(period)
        except Exception as e:
            app.logger.warning(f"FiscalPeriodService.close_period error: {e}")
        return period

    @classmethod
    def open_period(cls, owner_uid: str, year: int, month: int) -> dict:
        period = cls.get_period(owner_uid, year, month)
        if not period:
            return cls.ensure_period_exists(owner_uid, year, month)
        if period["status"] == "closed":
            raise ValueError(
                f"El período {year}-{month:02d} ya fue cerrado. "
                "Reabrir un período cerrado requiere autorización del propietario."
            )
        return period

    @classmethod
    def is_period_closed(cls, owner_uid: str, date_str: str) -> bool:
        try:
            if "T" in date_str:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except Exception:
            return False

        period = cls.get_period(owner_uid, dt.year, dt.month)
        if not period:
            return False
        return period.get("status") == "closed"

    @classmethod
    def validate_period_open(cls, owner_uid: str, date_str: str):
        if cls.is_period_closed(owner_uid, date_str):
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                label = f"{dt.year}-{dt.month:02d}"
            except Exception:
                label = date_str
            raise ValueError(
                f"El período fiscal {label} está cerrado. "
                "No se permiten nuevas transacciones en períodos cerrados."
            )

    @classmethod
    def list_periods(cls, owner_uid: str, year: int = None) -> list:
        try:
            db = cls._get_db()
            query = db.collection(cls._path(owner_uid))
            if year:
                query = query.where("year", "==", year)
            docs = query.stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            app.logger.warning(f"FiscalPeriodService.list_periods error: {e}")
            return []

    @classmethod
    def close_year(cls, owner_uid: str, year: int, closed_by: str = "") -> dict:
        results = {"year": year, "closed": [], "already_closed": [], "errors": []}
        for month in range(1, 13):
            try:
                period = cls.close_period(owner_uid, year, month, closed_by)
                results["closed"].append(f"{year}-{month:02d}")
            except ValueError as e:
                if "ya está cerrado" in str(e):
                    results["already_closed"].append(f"{year}-{month:02d}")
                else:
                    results["errors"].append(str(e))
        return results
