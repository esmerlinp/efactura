"""Build a dry-run bank ledger from historical source documents."""


class BankLedgerRebuildService:
    @staticmethod
    def persist_candidates(db, owner_uid, company_id, movements, sandbox=True, registered_by="historical_migration", apply=False):
        created = 0
        skipped = 0
        if not apply:
            return {"created": 0, "skipped": len(movements), "dry_run": True}
        for movement in movements:
            try:
                db.save_bank_movement(
                    owner_uid,
                    movement["accountId"],
                    movement["amount"],
                    movement["type"],
                    movement["sourceType"],
                    movement["sourceId"],
                    movement.get("description", ""),
                    sandbox=sandbox,
                    company_id=company_id,
                    registered_by=registered_by,
                )
                created += 1
            except Exception:
                skipped += 1
        return {"created": created, "skipped": skipped, "dry_run": False}
    @staticmethod
    def build_candidates(db, owner_uid, company_id, account_id, sandbox=True):
        movements = []
        invoices = db.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id, include_all=True) or []
        for invoice in invoices:
            invoice_id = invoice.get("id")
            for payment in db.get_invoice_payments(owner_uid, invoice_id, sandbox=sandbox, company_id=company_id) or []:
                if payment.get("bankAccountId") != account_id:
                    continue
                movements.append({
                    "accountId": account_id, "amount": float(payment.get("amount", 0) or 0),
                    "type": "income", "sourceType": "invoice_payment",
                    "sourceId": payment.get("id") or invoice_id,
                    "description": f"Cobro {invoice.get('invoiceNumber', '')}",
                    "date": str(payment.get("paymentDate") or invoice.get("date") or "")[:10],
                })

        expenses = db.get_expenses(owner_uid, sandbox=sandbox, company_id=company_id) or []
        for expense in expenses:
            expense_id = expense.get("id")
            if expense.get("bankAccountId") == account_id:
                movements.append({
                    "accountId": account_id, "amount": -float(expense.get("amount", 0) or 0),
                    "type": "expense", "sourceType": "cash_expense", "sourceId": expense_id,
                    "description": f"Gasto {expense.get('concept', '')}",
                    "date": str(expense.get("date", ""))[:10],
                })

        try:
            from app.services.supplier_invoice_service import SupplierInvoiceService
            for invoice in SupplierInvoiceService.get_all(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id) or []:
                if SupplierInvoiceService.is_voided(invoice):
                    continue
                for payment in SupplierInvoiceService.get_payments(owner_uid=owner_uid, invoice_id=invoice.get("id"), sandbox=sandbox, company_id=company_id) or []:
                    if payment.get("bankAccountId") != account_id or str(payment.get("approvalStatus", "")).lower() not in ("approved", "aprobado", ""):
                        continue
                    movements.append({
                        "accountId": account_id, "amount": -float(payment.get("amount", 0) or 0),
                        "type": "expense", "sourceType": "supplier_payment",
                        "sourceId": payment.get("id") or invoice.get("id"),
                        "description": f"Pago proveedor {invoice.get('invoiceNumber', '')}",
                        "date": str(payment.get("paymentDate") or invoice.get("date") or "")[:10],
                    })
        except Exception:
            pass
            for payment in db.get_cxp_payments(owner_uid, expense_id, sandbox=sandbox, company_id=company_id) or []:
                if payment.get("bankAccountId") != account_id:
                    continue
                movements.append({
                    "accountId": account_id, "amount": -float(payment.get("amount", 0) or 0),
                    "type": "expense", "sourceType": "cxp_payment",
                    "sourceId": payment.get("id") or expense_id,
                    "description": f"Pago CxP {expense.get('concept', '')}",
                    "date": str(payment.get("paymentDate") or expense.get("date") or "")[:10],
                })

        for transfer in db.get_bank_transfers(owner_uid, sandbox=sandbox, company_id=company_id) or []:
            if transfer.get("fromAccountId") == account_id:
                amount = -float(transfer.get("amount", 0) or 0)
            elif transfer.get("toAccountId") == account_id:
                amount = float(transfer.get("amount", 0) or 0)
            else:
                continue
            movements.append({
                "accountId": account_id, "amount": amount, "type": "transfer",
                "sourceType": "bank_transfer", "sourceId": transfer.get("id"),
                "description": transfer.get("description", "Transferencia"),
                "date": str(transfer.get("date", ""))[:10],
            })
        return movements

    @staticmethod
    def summarize(account, movements):
        initial = float(account.get("initialBalance", 0) or 0)
        total = sum(float(m.get("amount", 0) or 0) for m in movements)
        stored = float(account.get("currentBalance", 0) or 0)
        return {
            "account_id": account.get("id"), "initial_balance": round(initial, 2),
            "movement_total": round(total, 2), "reconstructed_balance": round(initial + total, 2),
            "stored_balance": round(stored, 2), "difference": round(stored - initial - total, 2),
            "movement_count": len(movements), "movements": movements,
        }
