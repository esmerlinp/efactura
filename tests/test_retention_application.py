"""Complemento 3.1 — Aplicación de retenciones en pagos agrupados y gastos, y
reversión al anular pagos.

Verifica proporcionalidad en parciales, acumulados por factura, idempotencia y
reversión sin modificar el cálculo original.
"""

from unittest.mock import MagicMock, patch

import pytest

import app.services.db_service as dbmod
import app.services.supplier_invoice_service as mod
from app.services.db_service import DatabaseService
from app.services.supplier_invoice_service import SupplierInvoiceService


class _Tx:
    def get(self, ref):
        return ref.get()

    def set(self, ref, data, **kw):
        ref.set(data)

    def update(self, ref, data):
        ref.update(data)

    def delete(self, ref):
        ref.delete()


def _snap(data):
    s = MagicMock()
    s.exists = True
    s.to_dict.return_value = data
    return s


def _invoice_ref(invoice_id, data):
    ref = MagicMock()
    ref.get.return_value = _snap(data)
    return ref


def _coll_ref_for(invoices):
    coll = MagicMock()
    coll.document.side_effect = lambda iid: invoices[iid]
    return coll


class TestMultiInvoiceRetention:
    def test_applies_proportional_retention_per_allocation(self):
        inv1 = _invoice_ref("inv-1", {
            "id": "inv-1", "status": "registrada", "total": 1000.0, "cxpRemainingBalance": 1000.0,
            "retentionIsrAmount": 20.0, "retentionItbisAmount": 10.0,
            "retentionIsrApplied": 0.0, "retentionItbisApplied": 0.0,
        })
        inv2 = _invoice_ref("inv-2", {
            "id": "inv-2", "status": "registrada", "total": 2000.0, "cxpRemainingBalance": 2000.0,
            "retentionIsrAmount": 40.0, "retentionItbisAmount": 20.0,
            "retentionIsrApplied": 0.0, "retentionItbisApplied": 0.0,
        })
        group = {
            "id": "g1", "approvalStatus": "pending",
            "allocations": [{"invoiceId": "inv-1", "amount": 500.0}, {"invoiceId": "inv-2", "amount": 1500.0}],
        }
        group_ref = MagicMock()
        group_ref.get.return_value = _snap(group)
        with patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp, \
             patch.object(SupplierInvoiceService, "_coll_ref", return_value=_coll_ref_for({"inv-1": inv1, "inv-2": inv2})):
            grp.return_value.document.return_value = group_ref
            result = SupplierInvoiceService._approve_multi_invoice_tx(
                _Tx(), "u", "g1", "Aprobador", "u2", "", "c", True,
            )
        assert result == "approved"
        u1 = inv1.update.call_args[0][0]
        assert u1["retentionIsrApplied"] == 10.0  # 20 × 500/1000
        assert u1["retentionItbisApplied"] == 5.0  # 10 × 500/1000
        assert u1["retentionStatus"] == "partial"
        u2 = inv2.update.call_args[0][0]
        assert u2["retentionIsrApplied"] == 30.0  # 40 × 1500/2000
        assert u2["retentionItbisApplied"] == 15.0  # 20 × 1500/2000
        assert u2["retentionStatus"] == "partial"


class TestExpenseRetention:
    def test_applies_retention_from_withheld(self):
        expense = {
            "id": "exp-1", "amount": 1000.0, "cxpRemainingBalance": 1000.0,
            "isrWithheld": 20.0, "itbisWithheld": 10.0,
            "retentionIsrApplied": 0.0, "retentionItbisApplied": 0.0,
        }
        doc = MagicMock()
        doc.get.return_value = _snap(expense)
        pay_ref = MagicMock()
        pay_ref.get.return_value = _snap({"amount": 500.0, "approvalStatus": "pending"})
        with patch.object(dbmod, "_company_coll") as coll:
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = pay_ref
            result = DatabaseService._approve_cxp_payment_tx(
                _Tx(), "u", "exp-1", "pay-1", "Aprobador", "u2", "", True, "c",
            )
        assert result == "approved"
        u = doc.update.call_args[0][0]
        assert u["retentionIsrApplied"] == 10.0
        assert u["retentionItbisApplied"] == 5.0
        assert u["retentionStatus"] == "partial"


class TestRetentionReversal:
    def test_void_single_payment_reverses_retention(self):
        inv = {"id": "inv-1", "status": "registrada", "cxpStatus": "Abonado",
               "total": 1000.0, "cxpRemainingBalance": 500.0,
               "retentionIsrApplied": 10.0, "retentionItbisApplied": 5.0}
        doc = MagicMock()
        doc.get.return_value = _snap(inv)
        pay_ref = MagicMock()
        pay_ref.get.return_value = _snap({"amount": 500.0, "approvalStatus": "approved",
                                          "retentionIsrApplied": 10.0, "retentionItbisApplied": 5.0})
        with patch.object(mod, "firebase_initialized", True), \
             patch.object(mod, "db_firestore", MagicMock()), \
             patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
             patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry"):
            coll_ref.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = pay_ref
            ok, msg = SupplierInvoiceService.void_payment(
                owner_uid="u", invoice_id="inv-1", payment_id="pay-1", sandbox=True, company_id="c",
            )
        assert ok is True
        u = doc.update.call_args[0][0]
        assert u["retentionIsrApplied"] == 0.0
        assert u["retentionItbisApplied"] == 0.0

    def test_void_expense_payment_reverses_retention(self):
        expense = {"amount": 1000.0, "cxpRemainingBalance": 500.0, "cxpStatus": "Abonado",
                   "retentionIsrApplied": 10.0, "retentionItbisApplied": 5.0}
        doc = MagicMock()
        doc.get.return_value = _snap(expense)
        pay_ref = MagicMock()
        pay_ref.get.return_value = _snap({"amount": 500.0, "approvalStatus": "approved",
                                          "retentionIsrApplied": 10.0, "retentionItbisApplied": 5.0})
        with patch.object(dbmod, "firebase_initialized", True), \
             patch.object(dbmod, "_company_coll") as coll, \
             patch.object(dbmod, "_invalidate_expenses"), \
             patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry"):
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = pay_ref
            ok, msg = DatabaseService.void_cxp_payment("u", "exp-1", "pay-1", company_id="c")
        assert ok is True
        u = doc.update.call_args[0][0]
        assert u["retentionIsrApplied"] == 0.0
        assert u["retentionItbisApplied"] == 0.0

    def test_void_multi_invoice_reverses_retention(self):
        inv = {"id": "inv-1", "status": "registrada", "total": 1000.0, "cxpRemainingBalance": 500.0,
               "retentionIsrApplied": 10.0, "retentionItbisApplied": 5.0}
        inv_ref = _invoice_ref("inv-1", inv)
        alloc_ref = MagicMock()
        alloc_ref.get.return_value = _snap({"retentionIsrApplied": 10.0, "retentionItbisApplied": 5.0})
        inv_ref.collection.return_value.document.return_value = alloc_ref
        group = {"id": "g1", "approvalStatus": "approved",
                 "allocations": [{"invoiceId": "inv-1", "amount": 500.0}]}
        group_ref = MagicMock()
        group_ref.get.return_value = _snap(group)
        with patch.object(mod, "firebase_initialized", True), \
             patch.object(mod, "db_firestore", MagicMock()), \
             patch.object(SupplierInvoiceService, "_coll_ref", return_value=_coll_ref_for({"inv-1": inv_ref})), \
             patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp, \
             patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry"):
            grp.return_value.document.return_value = group_ref
            ok, msg = SupplierInvoiceService.void_multi_invoice_payment(
                owner_uid="u", group_id="g1", voided_by="u", reason="x", company_id="c",
            )
        assert ok is True
        u = inv_ref.update.call_args[0][0]
        assert u["retentionIsrApplied"] == 0.0
        assert u["retentionItbisApplied"] == 0.0


class TestRetentionIdempotency:
    def test_double_approve_expense_does_not_double_apply(self):
        expense = {"amount": 1000.0, "cxpRemainingBalance": 1000.0,
                   "isrWithheld": 20.0, "retentionIsrApplied": 0.0}
        doc = MagicMock()
        doc.get.return_value = _snap(expense)
        pay_ref = MagicMock()
        pay_ref.get.return_value = _snap({"amount": 500.0, "approvalStatus": "pending"})
        with patch.object(dbmod, "_company_coll") as coll:
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = pay_ref
            # Primera aprobación muta el estado del pago
            expense["retentionIsrApplied"] = 10.0
            pay_ref.get.return_value = _snap({"amount": 500.0, "approvalStatus": "approved"})
            result = DatabaseService._approve_cxp_payment_tx(
                _Tx(), "u", "exp-1", "pay-1", "A", "u2", "", True, "c",
            )
        assert result == "already_approved"
        doc.update.assert_not_called()
