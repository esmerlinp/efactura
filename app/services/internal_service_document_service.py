"""Servicio de dominio para promociones internas no fiscales."""

from datetime import date

from app.models.internal_service_document import (
    PROMOTION_TYPES,
    calculated_status,
    calculate_line,
    cents,
)
from app.repositories.internal_service_document_repository import InternalServiceDocumentRepository
from app.services.db_service import DatabaseService


class InternalServiceDocumentError(ValueError):
    pass


class InternalServiceDocumentService:
    @staticmethod
    def _validate_dates(start, end, billing):
        if not start or not end or not billing:
            raise InternalServiceDocumentError("Las fechas de promoción y facturación son obligatorias.")
        if end < start:
            raise InternalServiceDocumentError("La fecha final no puede ser anterior a la inicial.")
        if billing < start:
            raise InternalServiceDocumentError("La fecha de facturación no puede ser anterior al inicio.")

    @classmethod
    def create(cls, *, owner_uid, company_id, sandbox, client_id, issue_date,
               reason, promotion_type, promotion_start, promotion_end,
               billing_start, lines, notes, idempotency_key, actor):
        if promotion_type not in PROMOTION_TYPES:
            raise InternalServiceDocumentError("Tipo de promoción inválido.")
        if not reason.strip():
            raise InternalServiceDocumentError("El motivo es obligatorio.")
        cls._validate_dates(promotion_start, promotion_end, billing_start)
        if not idempotency_key or len(idempotency_key) > 200:
            raise InternalServiceDocumentError("La clave de idempotencia es obligatoria.")

        client = DatabaseService.get_client(
            owner_uid,
            client_id,
            sandbox=sandbox,
            company_id=company_id,
        )
        if not client or (client.get("company_id") and client.get("company_id") != company_id):
            raise InternalServiceDocumentError("El cliente no pertenece a la empresa activa.")
        catalog = {str(item.get("id")): item for item in DatabaseService.get_items(owner_uid, sandbox=sandbox, company_id=company_id)}
        if not lines:
            raise InternalServiceDocumentError("Debes agregar al menos un servicio o producto.")

        stored_lines = []
        subtotal = discount = payable = 0
        for line in lines:
            item = catalog.get(str(line.get("itemId")))
            if not item:
                raise InternalServiceDocumentError("Uno de los productos no pertenece a la empresa activa.")
            calculated = calculate_line(item, line.get("quantity", 1), line.get("discountRate", 100))
            stored_lines.append(calculated.to_dict())
            subtotal += cents(calculated.subtotal)
            discount += cents(calculated.discount)
            payable += cents(calculated.payable)

        now = date.today().isoformat()
        payload = {
            "ownerUID": owner_uid,
            "companyId": company_id,
            "sandbox": bool(sandbox),
            "issueDate": issue_date,
            "reason": reason.strip(),
            "promotionType": promotion_type,
            "promotionTypeLabel": PROMOTION_TYPES[promotion_type],
            "promotionStartDate": promotion_start,
            "promotionEndDate": promotion_end,
            "billingStartDate": billing_start,
            "persistedState": "active",
            "calculatedState": calculated_status({"promotionStartDate": promotion_start, "promotionEndDate": promotion_end}, now),
            "clientSnapshot": dict(client),
            "clientId": client_id,
            "lines": stored_lines,
            "subtotalCents": subtotal,
            "discountCents": discount,
            "payableCents": payable,
            "notes": notes.strip(),
            "createdBy": actor.get("name", ""),
            "createdByEmail": actor.get("email", ""),
            "source": "internal_service_document",
            "nonFiscal": True,
        }
        return InternalServiceDocumentRepository.create_transactional(company_id, sandbox, payload, idempotency_key)

    @classmethod
    def get(cls, company_id, document_id, sandbox):
        document = InternalServiceDocumentRepository.get(company_id, document_id, sandbox)
        if document:
            document["calculatedState"] = calculated_status(document, date.today().isoformat())
        return document

    @classmethod
    def list(cls, company_id, sandbox):
        documents = InternalServiceDocumentRepository.list(company_id, sandbox)
        today = date.today().isoformat()
        for document in documents:
            document["calculatedState"] = calculated_status(document, today)
        return sorted(documents, key=lambda item: item.get("issueDate", ""), reverse=True)

    @classmethod
    def void(cls, company_id, document_id, sandbox, reason, actor):
        if not reason.strip():
            raise InternalServiceDocumentError("El motivo de anulación es obligatorio.")
        return InternalServiceDocumentRepository.void(company_id, document_id, sandbox, reason.strip(), actor)
