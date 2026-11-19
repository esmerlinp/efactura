"""Proyección de lectura de Cuentas por Pagar consolidada (proveedores + gastos).

No es un motor financiero: solo normaliza las obligaciones existentes y sus
pagos para una vista unificada. Las operaciones de pago, aprobación, banco y
contabilidad siguen viviendo en ``SupplierInvoiceService`` y ``DatabaseService``.
"""

from datetime import datetime, timedelta, timezone

SOURCE_PROVIDER = "provider"
SOURCE_EXPENSE = "expense"

STATUS_PENDING = "pendiente"
STATUS_PARTIAL = "parcial"
STATUS_PAID = "pagada"
STATUS_OVERDUE = "vencida"
STATUS_VOIDED = "anulada"

DOC_PENDING = "pendiente"
DOC_APPROVED = "aprobada"
DOC_NA = "no_aplica"

PAY_NONE = "sin_pagos"
PAY_PENDING = "pendiente"
PAY_APPROVED = "aprobada"
PAY_MIXED = "mixta"

DUE_SOON_DAYS = 30


def _money(value):
    try:
        return round(float(value or 0), 2)
    except (ValueError, TypeError):
        return 0.0


def _date_str(value):
    s = str(value or "")[:10]
    return s if len(s) == 10 else ""


def _currency(value):
    c = str(value or "").strip().upper()
    return c if c else "DOP"


def _expense_is_voided(exp):
    status = str(exp.get("status", "") or "").strip().lower()
    cxp = str(exp.get("cxpStatus", "") or "").strip().lower()
    return status in ("anulada", "voided") or cxp == "anulada"


class CxpConsolidationService:
    """Consolida obligaciones y pagos de proveedores y gastos."""

    # ── Normalización de pagos ───────────────────────────────────────────────
    @classmethod
    def _normalize_payment(cls, payment, obligation):
        return {
            "id": payment.get("id", ""),
            "amount": _money(payment.get("amount")),
            "payment_date": _date_str(payment.get("paymentDate")),
            "method": payment.get("method", "") or "",
            "reference": payment.get("reference", "") or "",
            "bank_account_id": payment.get("bankAccountId", "") or "",
            "approval_status": str(payment.get("approvalStatus", "") or "").lower(),
            "approved_by": payment.get("approvedBy", "") or "",
            "registered_by": payment.get("registeredBy", "") or "",
            "accounting_status": payment.get("accountingStatus", "") or "",
            "currency": obligation.get("currency", "DOP"),
            "source": obligation["source"],
            "obligation_id": obligation["id"],
            "obligation_number": obligation["document_number"],
            "supplier_name": obligation["supplier_name"],
            "detail_url": obligation["detail_url"],
        }

    @classmethod
    def _payment_approval_state(cls, payments):
        statuses = {str(p.get("approvalStatus", "") or "").lower() for p in payments}
        if not statuses:
            return PAY_NONE
        pending = "pending" in statuses
        approved = "approved" in statuses
        if pending and approved:
            return PAY_MIXED
        if pending:
            return PAY_PENDING
        if approved:
            return PAY_APPROVED
        return PAY_NONE

    # ── Normalización de obligaciones ────────────────────────────────────────
    @classmethod
    def _finish_obligation(cls, rec, payments, today):
        approved = [p for p in payments if str(p.get("approvalStatus", "") or "").lower() == "approved"]
        pending = [p for p in payments if str(p.get("approvalStatus", "") or "").lower() == "pending"]
        rec["paid"] = round(sum(_money(p.get("amount")) for p in approved), 2)
        rec["pending_payment_amount"] = round(sum(_money(p.get("amount")) for p in pending), 2)
        rec["payment_approval"] = cls._payment_approval_state(payments)
        rec["payments"] = [cls._normalize_payment(p, rec) for p in payments]

        total = rec["total"]
        balance = rec["balance"]
        computed_balance = round(total - rec["paid"], 2)
        rec["balance_mismatch"] = abs(balance - computed_balance) > 0.01

        if rec["voided"]:
            rec["status"] = STATUS_VOIDED
        elif balance <= 0.01 and total > 0:
            rec["status"] = STATUS_PAID
        elif rec["paid"] > 0 and balance > 0:
            rec["status"] = STATUS_PARTIAL
        elif rec["due_date"] and rec["due_date"] < today:
            rec["status"] = STATUS_OVERDUE
        else:
            rec["status"] = STATUS_PENDING
        return rec

    @classmethod
    def _provider_record(cls, inv, payments, today):
        from app.services.supplier_invoice_service import SupplierInvoiceService
        total = _money(inv.get("total"))
        balance = _money(inv.get("cxpRemainingBalance", total))
        rec = {
            "id": inv.get("id", ""),
            "source": SOURCE_PROVIDER,
            "voided": SupplierInvoiceService.is_voided(inv),
            "document_number": inv.get("invoiceNumber", "") or inv.get("supplierInvoiceNumber", "") or "",
            "reference_number": inv.get("poNumber", "") or "",
            "supplier_name": inv.get("supplierName", "") or "",
            "supplier_tax_id": inv.get("supplierRnc", "") or inv.get("supplierCedula", "") or "",
            "ncf": inv.get("ncf", "") or "",
            "description": "",
            "issue_date": _date_str(inv.get("date")),
            "due_date": _date_str(inv.get("dueDate")),
            "currency": _currency(inv.get("currency")),
            "total": total,
            "balance": balance,
            "document_approval": DOC_NA,
            "detail_url": "",
        }
        return cls._finish_obligation(rec, payments, today)

    @classmethod
    def _expense_record(cls, exp, payments, today):
        total = _money(exp.get("amount", exp.get("total", 0)))
        balance = _money(exp.get("cxpRemainingBalance", total))
        rec = {
            "id": exp.get("id", ""),
            "source": SOURCE_EXPENSE,
            "voided": _expense_is_voided(exp),
            "document_number": exp.get("ncf", "") or exp.get("documentNumber", "") or "",
            "reference_number": "",
            "supplier_name": exp.get("providerName", "") or "",
            "supplier_tax_id": exp.get("rncEmisor", "") or "",
            "ncf": exp.get("ncf", "") or "",
            "description": exp.get("concept", "") or "",
            "issue_date": _date_str(exp.get("date")),
            "due_date": _date_str(exp.get("dueDate")),
            "currency": _currency(exp.get("currency")),
            "total": total,
            "balance": balance,
            "document_approval": (
                DOC_PENDING
                if str(exp.get("approvalStatus", "") or "").strip().lower() in ("pendiente", "pending")
                else DOC_APPROVED
            ),
            "detail_url": "",
        }
        return cls._finish_obligation(rec, payments, today)

    # ── Construcción principal ───────────────────────────────────────────────
    @classmethod
    def build(cls, owner_uid, company_id, sandbox=True):
        """Devuelve {obligations, pending_documents, payments, kpis}."""
        from app.services.supplier_invoice_service import SupplierInvoiceService
        from app.services.db_service import DatabaseService

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        obligations = []
        pending_documents = []

        # Proveedores
        invoices = SupplierInvoiceService.get_all(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
        for inv in invoices:
            if SupplierInvoiceService.is_voided(inv):
                # las anuladas se conservan en la vista "Anuladas"
                payments = SupplierInvoiceService.get_payments(owner_uid=owner_uid, invoice_id=inv.get("id", ""), sandbox=sandbox, company_id=company_id)
                rec = cls._provider_record(inv, payments, today)
                obligations.append(rec)
            else:
                payments = SupplierInvoiceService.get_payments(owner_uid=owner_uid, invoice_id=inv.get("id", ""), sandbox=sandbox, company_id=company_id)
                obligations.append(cls._provider_record(inv, payments, today))

        # Gastos
        expenses = DatabaseService.get_expenses(owner_uid, company_id=company_id, sandbox=sandbox)
        for exp in expenses:
            if _expense_is_voided(exp):
                payments = DatabaseService.get_cxp_payments(owner_uid, exp.get("id", ""), sandbox=sandbox, company_id=company_id)
                obligations.append(cls._expense_record(exp, payments, today))
                continue
            # Documento pendiente de aprobación → no es obligación aún
            if str(exp.get("approvalStatus", "") or "").strip().lower() in ("pendiente", "pending"):
                pending_documents.append(cls._expense_record(exp, [], today))
                continue
            # Solo crédito genera obligación
            if str(exp.get("paymentType", "") or "").strip().lower() != "crédito":
                continue
            payments = DatabaseService.get_cxp_payments(owner_uid, exp.get("id", ""), sandbox=sandbox, company_id=company_id)
            obligations.append(cls._expense_record(exp, payments, today))

        payments = []
        for rec in obligations:
            payments.extend(rec["payments"])

        kpis = cls.summarize(obligations, pending_documents, payments)

        return {
            "obligations": obligations,
            "pending_documents": pending_documents,
            "payments": payments,
            "kpis": kpis,
        }

    # ── Indicadores por moneda ───────────────────────────────────────────────
    @classmethod
    def summarize(cls, obligations, pending_documents, payments, period=None, today=None):
        today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        period = period or datetime.now(timezone.utc).strftime("%Y-%m")

        kpis = {}

        def bucket(cur):
            if cur not in kpis:
                kpis[cur] = {
                    "pending": 0.0,
                    "overdue": 0.0,
                    "due_soon": 0.0,
                    "pending_doc_approval": 0.0,
                    "pending_payment_approval": 0.0,
                    "paid_in_period": 0.0,
                }
            return kpis[cur]

        for rec in obligations:
            cur = rec["currency"]
            k = bucket(cur)
            if rec["status"] == STATUS_OVERDUE:
                k["overdue"] = round(k["overdue"] + rec["balance"], 2)
            elif rec["status"] in (STATUS_PENDING, STATUS_PARTIAL):
                k["pending"] = round(k["pending"] + rec["balance"], 2)
            if rec["status"] in (STATUS_PENDING, STATUS_PARTIAL, STATUS_OVERDUE):
                k["pending_payment_approval"] = round(k["pending_payment_approval"] + rec["pending_payment_amount"], 2)

        # Por vencer: saldo pendiente > 0 y vencimiento dentro de los próximos 30 días
        horizon = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=DUE_SOON_DAYS)).strftime("%Y-%m-%d")
        for rec in obligations:
            if rec["status"] in (STATUS_PENDING, STATUS_PARTIAL):
                if rec["due_date"] and today <= rec["due_date"] <= horizon:
                    bucket(rec["currency"])["due_soon"] = round(
                        bucket(rec["currency"])["due_soon"] + rec["balance"], 2
                    )

        for doc in pending_documents:
            bucket(doc["currency"])["pending_doc_approval"] = round(
                bucket(doc["currency"])["pending_doc_approval"] + doc["total"], 2
            )

        for p in payments:
            if str(p.get("approval_status", "") or "").lower() == "approved":
                if (p.get("payment_date", "") or "")[:7] == period:
                    bucket(p["currency"])["paid_in_period"] = round(
                        bucket(p["currency"])["paid_in_period"] + p["amount"], 2
                    )

        return kpis
