"""Alertas idempotentes de promociones próximas a vencer."""

import hashlib
from datetime import date

from app.services.db_service import DatabaseService
from app.services.internal_service_document_service import InternalServiceDocumentService


class InternalServiceDocumentAlertService:
    @classmethod
    def process(cls, company_id, owner_uid, sandbox=True):
        today = date.today()
        alerts = 0
        for document in InternalServiceDocumentService.list(company_id, sandbox):
            if document.get("persistedState") != "active":
                continue
            end_date = document.get("promotionEndDate", "")
            if not end_date:
                continue
            try:
                end = date.fromisoformat(end_date)
            except ValueError:
                continue
            days = (end - today).days
            if days not in (0, 7, 30):
                continue
            key = f"internal_promotion_expiry:{company_id}:{sandbox}:{document['id']}:{end_date}:{days}"
            notification_id = hashlib.sha256(key.encode()).hexdigest()[:32]
            DatabaseService.create_user_notification(owner_uid, {
                "id": notification_id,
                "title": "Promoción próxima a vencer" if days >= 0 else "Promoción vencida",
                "message": f"{document.get('documentNumber', '')} vence el {end_date}. Validar el inicio de facturación formal.",
                "link": f"/internal-documents/{document['id']}",
                "documentNumber": document.get("documentNumber", ""),
                "companyId": company_id,
                "sandbox": sandbox,
                "category": "internal_service_document",
            })
            alerts += 1
        return alerts
