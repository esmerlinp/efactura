import uuid
from datetime import datetime, timezone
from app.services.db_service import DatabaseService
from app.utils.ecf_utils import is_ncf_type_rui


def is_final_consumer(invoice):
    rnc = (invoice.get("clientRNC") or "").strip()
    client_id = invoice.get("clientId") or ""
    return not rnc or rnc == "000000000" or client_id == "default"


class RuiGenerationService:

    @staticmethod
    def is_invoice_eligible(invoice, company_id=None) -> bool:
        if not invoice:
            return False
        if invoice.get("status") != "Cobrada":
            return False
        if invoice.get("ruiId"):
            return False
        if not invoice.get("includeInRui", True):
            return False
        if invoice.get("isQuotation"):
            return False
        ecf = invoice.get("ecfType", "")
        if "Nota de Crédito" in ecf or "Nota de Débito" in ecf:
            return False
        if not is_final_consumer(invoice):
            return False
        return True

    @staticmethod
    def _validate_prerequisites(owner_uid, company, business_date, sandbox, company_id=None):
        if not company.get("ruiEnabled"):
            raise ValueError("RUI no está habilitado para esta empresa.")
        auth_number = (company.get("ruiAuthorizationNumber") or "").strip()
        if not auth_number:
            raise ValueError("No se ha configurado el Número de Autorización DGII para RUI.")
        if not business_date:
            raise ValueError("La fecha fiscal es requerida.")
        existing = DatabaseService.get_fiscal_summary_documents(
            owner_uid, sandbox=sandbox,
            document_type="RUI",
            business_date=str(business_date)[:10],
            company_id=company_id
        )
        for doc in existing:
            if doc.get("estado") == "ACTIVO":
                raise ValueError(f"Ya existe un RUI ACTIVO para la fecha {str(business_date)[:10]}.")

    @staticmethod
    def _calculate_totals(invoices):
        gravado18 = 0.0
        itbis18 = 0.0
        gravado16 = 0.0
        itbis16 = 0.0
        exento = 0.0
        total_ventas = 0.0
        for inv in invoices:
            total_ventas += float(inv.get("total", 0.0))
            for item in inv.get("items", []):
                rate = float(item.get("itbisRate", 0.18))
                subtotal = float(item.get("subtotal", 0.0))
                itbis_amt = float(item.get("itbisAmount", 0.0))
                if rate == 0.0:
                    exento += subtotal
                elif abs(rate - 0.16) < 0.001:
                    gravado16 += subtotal
                    itbis16 += itbis_amt
                else:
                    gravado18 += subtotal
                    itbis18 += itbis_amt
        return {
            "gravado18": round(gravado18, 2),
            "itbis18": round(itbis18, 2),
            "gravado16": round(gravado16, 2),
            "itbis16": round(itbis16, 2),
            "exento": round(exento, 2),
            "total": round(total_ventas, 2),
        }

    @staticmethod
    def generate_rui(owner_uid, business_date, user_email, user_name="", sandbox=True, auto=False, notes="", company_id=None):
        company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
        RuiGenerationService._validate_prerequisites(owner_uid, company, business_date, sandbox, company_id=company_id)

        eligible = DatabaseService.get_rui_eligible_invoices(owner_uid, business_date, sandbox=sandbox, company_id=company_id)
        eligible = [inv for inv in eligible if RuiGenerationService.is_invoice_eligible(inv, company_id=company_id)]
        if not eligible:
            raise ValueError(f"No hay facturas elegibles para RUI en la fecha {str(business_date)[:10]}.")

        invoice_ids = [inv["id"] for inv in eligible]
        totals = RuiGenerationService._calculate_totals(eligible)
        cantidad = len(eligible)

        pos_shift_ids = list({
            inv.get("posShiftId") for inv in eligible
            if inv.get("posShiftId")
        })
        cash_register_ids = list({
            inv.get("cashRegisterId") for inv in eligible
            if inv.get("cashRegisterId")
        })

        encf, log_id = DatabaseService.consume_next_sequence(
            owner_uid, "B12", user_email, sandbox=sandbox, company_id=company_id
        )

        business_date_str = str(business_date)[:10]

        doc_dict = {
            "id": f"RUI_{owner_uid}_{business_date_str}",
            "ownerUID": owner_uid,
            "documentType": "RUI",
            "businessDate": business_date_str,
            "ncf": encf,
            "sequenceLogId": log_id,
            "sequenceType": "B12",
            "estado": "ACTIVO",
            "cancelledBy": "",
            "cancelledAt": "",
            "cancelReason": "",
            "replacementRuiId": "",
            "totalGravado18": totals["gravado18"],
            "totalGravado16": totals["gravado16"],
            "totalExento": totals["exento"],
            "totalItbis18": totals["itbis18"],
            "totalItbis16": totals["itbis16"],
            "totalVentas": totals["total"],
            "cantidadTransacciones": cantidad,
            "taxSnapshot": totals,
            "posShiftIds": pos_shift_ids,
            "cashRegisterIds": cash_register_ids,
            "generatedBy": user_email,
            "generatedByEmail": user_email,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }

        saved = DatabaseService.save_fiscal_summary_document(owner_uid, doc_dict, sandbox=sandbox, company_id=company_id)
        if not saved:
            raise RuntimeError("Error al guardar el documento RUI en Firestore.")

        marked = DatabaseService.mark_invoices_as_rui_included(
            owner_uid, invoice_ids, saved["id"], encf, sandbox=sandbox, company_id=company_id
        )
        if not marked:
            raise RuntimeError("Error al marcar facturas como incluidas en RUI.")

        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_POS,
            entity_id=saved["id"],
            entity_label=f"RUI generado: {encf} - {business_date_str} ({cantidad} transacciones, RD$ {totals['total']:,.2f})",
            user_session={"email": user_email, "uid": "", "ownerUID": owner_uid},
            before=None,
            after=saved,
            sandbox=sandbox
        )

        from app.events.events import RuiGenerated
        from app.events.setup import event_bus
        event = RuiGenerated(
            owner_uid=owner_uid,
            sandbox=sandbox,
            rui_id=saved["id"],
            rui_ncf=encf,
            business_date=business_date_str,
            rui_data=saved,
        )
        event_bus.publish(event)

        return saved

    @staticmethod
    def cancel_rui(owner_uid, rui_id, cancelled_by, cancelled_by_email, cancel_reason, sandbox=True, replacement_rui_id="", company_id=None):
        if not cancel_reason or not cancel_reason.strip():
            raise ValueError("El motivo de anulación es obligatorio.")

        doc = DatabaseService.get_fiscal_summary_document(owner_uid, rui_id, sandbox=sandbox, company_id=company_id)
        if not doc:
            raise ValueError(f"Documento RUI {rui_id} no encontrado.")
        if doc.get("estado") != "ACTIVO":
            raise ValueError(f"El documento RUI ya está {doc.get('estado')}.")

        result = DatabaseService.cancel_fiscal_summary_document(
            owner_uid, rui_id, cancelled_by, cancelled_by_email,
            cancel_reason, replacement_rui_id=replacement_rui_id, sandbox=sandbox, company_id=company_id
        )
        if not result:
            raise RuntimeError("Error al anular el documento RUI en Firestore.")

        DatabaseService.release_invoices_from_rui(owner_uid, rui_id, sandbox=sandbox, company_id=company_id)

        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_POS,
            entity_id=rui_id,
            entity_label=f"RUI anulado: {doc.get('ncf', '')} - Motivo: {cancel_reason}",
            user_session={"email": cancelled_by_email, "uid": cancelled_by, "ownerUID": owner_uid},
            before=doc,
            after=result,
            sandbox=sandbox
        )

        return result
