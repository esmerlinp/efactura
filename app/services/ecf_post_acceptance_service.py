"""Idempotent effects applied after DGII explicitly accepts an e-CF."""

import logging
from datetime import datetime, timezone

from app.services.db_service import DatabaseService

logger = logging.getLogger(__name__)


class EcfPostAcceptanceService:
    """Coordinates inventory, accounting and notification after ACCEPTED."""

    @classmethod
    def process_accepted_invoice(cls, owner_uid, invoice_id, invoice,
                                 company_id=None, sandbox=True):
        if not invoice or str(invoice.get("dgiiStatus", "")).upper() != "ACCEPTED":
            return {"success": False, "status": "not_accepted"}

        invoice = dict(invoice)
        invoice["id"] = invoice_id
        invoice["isSyncedWithDGII"] = True
        invoice["postAcceptanceStatus"] = invoice.get("postAcceptanceStatus") or "PENDING"
        effects = {"inventory": False, "accounting": False, "email": False}

        try:
            if invoice.get("postAcceptanceStatus") not in ("INVENTORY_DONE", "ACCOUNTING_DONE", "COMPLETED"):
                invoice["postAcceptanceStatus"] = "INVENTORY_PENDING"
                DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox, company_id=company_id)
                invoice["inventoryCommitted"] = True
                invoice["postAcceptanceStatus"] = "INVENTORY_DONE"
                effects["inventory"] = True

            if not invoice.get("accountingPosted"):
                from app.services.accounting_service import AccountingService
                entry = AccountingService.auto_generate_invoice_entry(company_id, invoice, sandbox=sandbox)
                invoice["accountingPosted"] = bool(entry) or bool(invoice.get("accountingPosted"))
                invoice["postAcceptanceStatus"] = "ACCOUNTING_DONE" if invoice["accountingPosted"] else invoice.get("postAcceptanceStatus")
                effects["accounting"] = bool(entry) or bool(invoice.get("accountingPosted"))

            invoice["inventoryStatus"] = "COMMITTED"
            invoice["accountingStatus"] = "POSTED"
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox, company_id=company_id)

            # El correo es un efecto secundario opcional: nunca puede revertir
            # ni impedir que la venta aceptada quede completada.
            recipient_email = str(
                invoice.get("clientEmail") or invoice.get("email") or invoice.get("correo") or ""
            ).strip()
            if not recipient_email:
                try:
                    from app.web.invoices import _get_client_email
                    recipient_email = str(_get_client_email(
                        owner_uid, invoice, sandbox=sandbox, company_id=company_id
                    ) or "").strip()
                except Exception:
                    logger.exception("No se pudo resolver email de factura aceptada %s", invoice_id)

            if not recipient_email or "@" not in recipient_email:
                invoice["emailStatus"] = "NOT_APPLICABLE"
                invoice["emailError"] = "Cliente sin correo electrónico válido"
            else:
                try:
                    from app.web.invoices import send_invoice_email
                    sent, message = send_invoice_email(
                        owner_uid=owner_uid,
                        invoice=invoice,
                        recipient_email=recipient_email,
                        sandbox=sandbox,
                        company_id=company_id,
                    )
                    effects["email"] = bool(sent)
                    invoice["emailStatus"] = "SENT" if sent else "FAILED"
                    if sent:
                        invoice["emailNotified"] = True
                        invoice["autoEmailNotified"] = True
                        invoice["emailNotifiedTo"] = recipient_email
                        invoice["emailNotifiedAt"] = datetime.now(timezone.utc).isoformat()
                        invoice.pop("emailError", None)
                    else:
                        invoice["emailError"] = str(message or "Error al enviar el correo")[:500]
                except Exception as email_error:
                    logger.exception("Error enviando e-CF aceptado %s", invoice_id)
                    invoice["emailStatus"] = "FAILED"
                    invoice["emailError"] = str(email_error)[:500]

            invoice["postAcceptanceStatus"] = "COMPLETED"
            invoice["acceptedEffectsApplied"] = True
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox, company_id=company_id)
            return {"success": True, "status": "completed", "effects": effects}
        except Exception:
            logger.exception("Error aplicando efectos post-aceptación %s", invoice_id)
            invoice["postAcceptanceStatus"] = "FAILED"
            invoice["postAcceptanceError"] = "Error aplicando efectos posteriores a la aceptación DGII"
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox, company_id=company_id)
            return {"success": False, "status": "failed", "effects": effects}
