"""Reconciliation and repair for approved supplier payments."""

from datetime import datetime, timezone

from app.services.supplier_invoice_service import SupplierInvoiceService


class CxpPaymentReconciliationService:
    @classmethod
    def scan(cls, owner_uid, company_id, sandbox=True):
        findings = []
        invoices = SupplierInvoiceService.get_all(
            owner_uid=owner_uid, sandbox=sandbox, company_id=company_id
        ) or []
        for invoice in invoices:
            if SupplierInvoiceService.is_voided(invoice):
                continue
            for payment in SupplierInvoiceService.get_payments(
                owner_uid=owner_uid, invoice_id=invoice.get("id"),
                sandbox=sandbox, company_id=company_id,
            ) or []:
                if str(payment.get("approvalStatus") or "").lower() not in ("approved", "aprobado"):
                    continue
                issues = []
                if payment.get("bankAccountId") and payment.get("bankStatus") != "posted":
                    issues.append("bank_pending_or_error")
                if payment.get("accountingStatus") != "posted":
                    issues.append("accounting_pending_or_error")
                if issues:
                    findings.append({
                        "invoiceId": invoice.get("id"),
                        "paymentId": payment.get("id"),
                        "issues": issues,
                        "supplierName": invoice.get("supplierName", ""),
                        "amount": float(payment.get("amount", 0) or 0),
                    })
        return findings

    @classmethod
    def repair_payment(cls, owner_uid, company_id, invoice_id, payment_id,
                       sandbox=True, repaired_by="system"):
        invoice = SupplierInvoiceService.get(
            owner_uid=owner_uid, invoice_id=invoice_id,
            sandbox=sandbox, company_id=company_id,
        )
        if not invoice:
            return False, "Factura proveedor no encontrada."
        payments = SupplierInvoiceService.get_payments(
            owner_uid=owner_uid, invoice_id=invoice_id,
            sandbox=sandbox, company_id=company_id,
        ) or []
        payment = next((p for p in payments if p.get("id") == payment_id), None)
        if not payment:
            return False, "Pago no encontrado."
        if str(payment.get("approvalStatus") or "").lower() not in ("approved", "aprobado"):
            return False, "Solo se pueden reparar pagos aprobados."

        if payment.get("bankAccountId") and payment.get("bankStatus") != "posted":
            try:
                from app.services.db_service import run_firestore_transaction
                bank_result = run_firestore_transaction(
                    SupplierInvoiceService._apply_bank_payment_tx,
                    owner_uid,
                    payment.get("bankAccountId"),
                    payment_id,
                    float(payment.get("amount", 0) or 0),
                    f"Pago factura {invoice.get('ncf') or invoice.get('supplierInvoiceNumber') or ''}",
                    repaired_by,
                    company_id,
                    sandbox,
                )
                payments_ref = SupplierInvoiceService._coll_ref(
                    owner_uid=owner_uid, sandbox=sandbox, company_id=company_id
                ).document(invoice_id).collection("cxp_payments").document(payment_id)
                payments_ref.update({
                    "bankStatus": "posted",
                    "bankMovementId": bank_result.get("movementId", ""),
                    "bankError": "",
                })
            except Exception as exc:
                return False, f"No se pudo reparar banks/: {exc}"

        if payment.get("accountingStatus") == "posted":
            return True, "Pago conciliado correctamente."

        from app.services.accounting_service import AccountingService
        try:
            entry = AccountingService.auto_generate_cxp_payment_entry(
                company_id=company_id,
                payment_id=payment_id,
                amount=float(payment.get("amount", 0) or 0),
                payment_date=str(payment.get("paymentDate") or "")[:10],
                bank_account_id=payment.get("bankAccountId", ""),
                payment_method=payment.get("method", ""),
                concept=f"Pago factura {invoice.get('ncf') or invoice.get('supplierInvoiceNumber') or ''}",
                supplier_id=invoice.get("supplierId", ""),
                supplier_name=invoice.get("supplierName", ""),
                sandbox=sandbox,
            )
            payments_ref = SupplierInvoiceService._coll_ref(
                owner_uid=owner_uid, sandbox=sandbox, company_id=company_id
            ).document(invoice_id).collection("cxp_payments").document(payment_id)
            payments_ref.update({
                "accountingStatus": "posted" if entry else "pending",
                "accountingEntryId": (entry or {}).get("id", ""),
                "accountingError": "",
                "repairedAt": datetime.now(timezone.utc).isoformat(),
                "repairedBy": repaired_by,
            })
            if not entry:
                return False, "No se generó el asiento contable del pago."
            return True, "Pago conciliado correctamente."
        except Exception as exc:
            return False, str(exc)
