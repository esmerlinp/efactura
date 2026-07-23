"""
NcfTraditionalService — Emisión de comprobantes NCF tradicionales (B01-B18).

Los NCF tradicionales son documentos en papel pre-impreso que requieren:
1. Consumir un número de secuencia NCF
2. Registrar el documento en Firestore
3. Actualizar contabilidad y reportes

A diferencia de e-CF (E31-E50), NO requieren XML, firma digital ni API DGII.
"""
import uuid
from datetime import datetime, timezone

from app.models.fiscal_document_type import by_code, Family
from app.services.db_service import DatabaseService, _company_coll


EMITABLE_TRADITIONAL = {
    "B01", "B02", "B03", "B04", "B05", "B06", "B07",
    "B08", "B09", "B10", "B11",
    "B13", "B14", "B15", "B16", "B17", "B18",
}


class NcfTraditionalService:

    COLLECTION = "ncf_traditional"

    @classmethod
    def _coll(cls, sandbox: bool) -> str:
        return f"sandbox_{cls.COLLECTION}" if sandbox else cls.COLLECTION

    @classmethod
    def emit(cls, company_id: str, ncf_type: str, document_data: dict,
             user_email: str, sandbox: bool = True) -> dict:
        code = ncf_type.strip().upper()
        cls._validate_type(code)
        company = DatabaseService.get_company_profile(company_id, company_id=company_id)
        if not company:
            raise ValueError("Perfil de empresa no encontrado.")

        ncf, log_id = DatabaseService.consume_next_sequence(
            company_id, code, user_email, sandbox=sandbox
        )

        doc_id = f"{code}_{company_id}_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        doc = {
            "id": doc_id,
            "companyId": company_id,
            "tipoComprobante": code,
            "ncf": ncf,
            "sequenceLogId": log_id,
            "estado": "EMITIDO",
            "total": float(document_data.get("total", 0.0)),
            "subtotal": float(document_data.get("subtotal", 0.0)),
            "totalItbis": float(document_data.get("totalItbis", 0.0)),
            "clientRnc": (document_data.get("clientRnc") or "").strip(),
            "clientName": (document_data.get("clientName") or "").strip(),
            "clientIdNumber": (document_data.get("clientIdNumber") or "").strip(),
            "referenceNcf": (document_data.get("referenceNcf") or "").strip(),
            "referenceDate": (document_data.get("referenceDate") or "").strip(),
            "modificationCode": (document_data.get("modificationCode") or "").strip(),
            "items": document_data.get("items", []),
            "notes": (document_data.get("notes") or "").strip(),
            "emittedBy": user_email,
            "emittedAt": now_iso,
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "sandbox": sandbox,
        }

        t = by_code(code)
        doc["razonSocial"] = t.label

        saved = cls._save_document(company_id, doc, sandbox)
        if not saved:
            raise RuntimeError(f"Error al guardar {code} {ncf} en Firestore.")

        cls._log_audit(company_id, user_email, doc, sandbox)
        cls._generate_accounting_entry(company_id, code, saved, sandbox)
        return saved

    @classmethod
    def cancel(cls, company_id: str, doc_id: str, reason: str,
               cancelled_by_email: str, sandbox: bool = True) -> dict:
        if not reason or not reason.strip():
            raise ValueError("Motivo de anulación requerido.")

        doc = cls._get_document(company_id, doc_id, sandbox)
        if not doc:
            raise ValueError(f"Documento {doc_id} no encontrado.")
        if doc.get("estado") != "EMITIDO":
            raise ValueError(f"Documento ya está {doc.get('estado')}.")

        now_iso = datetime.now(timezone.utc).isoformat()
        doc["estado"] = "ANULADO"
        doc["cancelReason"] = reason.strip()
        doc["cancelledAt"] = now_iso
        doc["cancelledBy"] = cancelled_by_email
        doc["updatedAt"] = now_iso

        cls._update_document(company_id, doc_id, doc, sandbox)
        cls._log_audit(company_id, cancelled_by_email, doc, sandbox, action="CANCEL")
        return doc

    @classmethod
    def list_by_company(cls, company_id: str, sandbox: bool = True,
                        tipo: str = "", estado: str = "") -> list[dict]:
        docs = cls._list_documents(company_id, sandbox)
        if tipo:
            docs = [d for d in docs if d.get("tipoComprobante") == tipo.strip().upper()]
        if estado:
            docs = [d for d in docs if d.get("estado") == estado.strip().upper()]
        return sorted(docs, key=lambda d: d.get("emittedAt", ""), reverse=True)

    @classmethod
    def _validate_type(cls, code: str):
        if code not in EMITABLE_TRADITIONAL:
            raise ValueError(
                f"Tipo no soportado: {code}. "
                f"Soportados: {', '.join(sorted(EMITABLE_TRADITIONAL))}"
            )
        t = by_code(code)
        if t.family != Family.TRADITIONAL:
            raise ValueError(f"{code} no es un NCF tradicional.")

    # --- Persistencia (mockeable en tests) ---

    @classmethod
    def _save_document(cls, company_id: str, doc: dict, sandbox: bool) -> dict | None:
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return doc
        try:
            coll_name = cls._coll(sandbox)
            ref = _company_coll(company_id=company_id, coll_name=coll_name).document(doc["id"])
            ref.set(doc)
            return doc
        except Exception as e:
            print(f"Error guardando NCF tradicional: {e}")
            return None

    @classmethod
    def _get_document(cls, company_id: str, doc_id: str, sandbox: bool) -> dict | None:
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return None
        try:
            coll_name = cls._coll(sandbox)
            ref = _company_coll(company_id=company_id, coll_name=coll_name).document(doc_id)
            snap = ref.get()
            return snap.to_dict() if snap.exists else None
        except Exception as e:
            print(f"Error obteniendo NCF tradicional {doc_id}: {e}")
            return None

    @classmethod
    def _update_document(cls, company_id: str, doc_id: str, doc: dict, sandbox: bool):
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return
        try:
            coll_name = cls._coll(sandbox)
            ref = _company_coll(company_id=company_id, coll_name=coll_name).document(doc_id)
            ref.set(doc)
        except Exception as e:
            print(f"Error actualizando NCF tradicional {doc_id}: {e}")

    @classmethod
    def _list_documents(cls, company_id: str, sandbox: bool) -> list[dict]:
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return []
        try:
            coll_name = cls._coll(sandbox)
            docs = _company_coll(company_id=company_id, coll_name=coll_name).get()
            return [d.to_dict() for d in docs]
        except Exception as e:
            print(f"Error listando NCF tradicionales: {e}")
            return []

    # --- Auditoría ---

    @classmethod
    def _log_audit(cls, company_id, user_email, doc, sandbox, action="EMIT"):
        try:
            from app.services.audit_service import AuditService, ACTION_CREATE, ACTION_UPDATE, MODULE_INVOICES
            act = ACTION_CREATE if action == "EMIT" else ACTION_UPDATE
            AuditService.log_from_request(
                owner_uid=company_id, action=act, module=MODULE_INVOICES,
                entity_id=doc["id"],
                entity_label=f"NCF {doc['tipoComprobante']} {doc['ncf']} {action} - "
                             f"RD$ {float(doc.get('total', 0)):,.2f}",
                user_session={"email": user_email, "uid": "", "ownerUID": company_id},
                before={}, after=doc, sandbox=sandbox,
            )
        except Exception:
            pass

    # --- Contabilidad ---

    @classmethod
    def _generate_accounting_entry(cls, company_id, code, doc, sandbox):
        from app.models.fiscal_document_type import by_code
        from app.services.accounting_service import AccountingService

        t = by_code(code)
        entry_type = t.accounting_entry_type
        if entry_type == "standard":
            return

        data = {
            **doc,
            "totalITBIS": float(doc.get("totalItbis", 0)),
            "paymentType": doc.get("paymentType", "Contado"),
            "clientId": doc.get("clientRnc", ""),
            "invoiceNumber": doc.get("ncf", ""),
        }

        try:
            if entry_type == "invoice":
                AccountingService.auto_generate_invoice_entry(
                    company_id, data, sandbox=sandbox
                )
            elif entry_type == "expense":
                AccountingService.auto_generate_expense_entry(
                    company_id, data, sandbox=sandbox
                )
            elif entry_type == "credit_note":
                AccountingService.auto_generate_credit_note_entry(
                    company_id, data, sandbox=sandbox
                )
        except Exception:
            pass

    # --- Metadatos ---

    @staticmethod
    def get_emitables() -> list[dict]:
        from app.models.fiscal_document_type import all_types
        result = []
        for t in all_types():
            if t.family == Family.TRADITIONAL and t.code != "B12":
                result.append({
                    "code": t.code,
                    "label": t.label,
                    "category": t.category.value,
                    "has_itbis": t.has_itbis,
                    "has_retention": t.has_retention,
                    "max_amount": t.max_amount,
                    "requires_rnc": t.requires_rnc,
                })
        return sorted(result, key=lambda x: x["code"])
