"""Entregable 3 — Pagos parciales y asignación multi-factura (CxP).

Cubre registro de un pago para varias facturas, asignación manual, validación
de saldos, un único asiento contable por pago, y la integración con
aprobación/rechazo/anulación y reversión contable.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

import app.services.supplier_invoice_service as mod
from app.services.supplier_invoice_service import SupplierInvoiceService
from app.services.accounting_service import AccountingPostingError


def _patch_firebase():
    stack = ExitStack()
    stack.enter_context(patch.object(mod, "firebase_initialized", True))
    stack.enter_context(patch.object(mod, "db_firestore", MagicMock()))
    return stack


def _delegating_tx():
    """Reemplaza run_firestore_transaction por una ejecución directa del cuerpo
    con una transacción fake que delega en los mocks de DocumentReference."""
    class _Tx:
        def get(self, ref):
            return ref.get()

        def update(self, ref, data):
            ref.update(data)

        def set(self, ref, data, **kw):
            ref.set(data)

        def delete(self, ref):
            ref.delete()

    def _run(func, *args, **kwargs):
        return func(_Tx(), *args, **kwargs)

    return patch("app.services.db_service.run_firestore_transaction", side_effect=_run)


def _invoice_ref(invoice_id, data, pending_payments=None):
    """DocumentReference mock de una factura, con su subcolección cxp_payments."""
    ref = MagicMock()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = data
    ref.get.return_value = snap
    coll = MagicMock()
    coll.get.return_value = pending_payments or []
    ref.collection.return_value = coll
    ref._id = invoice_id
    return ref


def _group_ref(existing=None):
    ref = MagicMock()
    if existing is None:
        snap = MagicMock()
        snap.exists = False
        ref.get.return_value = snap
    else:
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = existing
        ref.get.return_value = snap
    return ref


def _mock_coll_ref(invoices):
    coll = MagicMock()
    coll.document.side_effect = lambda inv_id: invoices[inv_id]
    return coll


def _invoice(total, supplier_id="sup-1", cxp_status="Pendiente", rem=None):
    return {
        "id": "x", "total": total, "supplierId": supplier_id,
        "supplierName": "Proveedor A", "cxpStatus": cxp_status,
        "cxpRemainingBalance": total if rem is None else rem,
        "dueDate": "2026-12-31",
    }


class TestRegisterMultiInvoice:
    def test_register_success(self):
        inv1 = _invoice_ref("inv-1", _invoice(1000.0))
        inv2 = _invoice_ref("inv-2", _invoice(2000.0))
        group_coll = MagicMock()
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1, "inv-2": inv2})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=group_coll), \
                 patch.object(SupplierInvoiceService, "validate_period"):
                ok, msg, group_id = SupplierInvoiceService.register_multi_invoice_payment(
                    owner_uid="u", supplier_id="sup-1",
                    allocations=[{"invoiceId": "inv-1", "amount": 500.0}, {"invoiceId": "inv-2", "amount": 1500.0}],
                    registered_by="Usuario", requested_by_uid="user-1",
                    company_id="c", sandbox=True,
                )
        assert ok is True
        assert group_id
        group_doc = group_coll.document.return_value.set.call_args[0][0]
        assert group_doc["total"] == 2000.0
        assert group_doc["approvalStatus"] == "pending"
        assert group_doc["source"] == "multi_invoice"
        assert len(group_doc["allocations"]) == 2
        # una asignación por factura
        assert inv1.collection.return_value.document.return_value.set.call_count == 1
        assert inv2.collection.return_value.document.return_value.set.call_count == 1

    def test_register_rejects_overallocation(self):
        inv1 = _invoice_ref("inv-1", _invoice(1000.0))
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()), \
                 patch.object(SupplierInvoiceService, "validate_period"):
                ok, msg, _ = SupplierInvoiceService.register_multi_invoice_payment(
                    owner_uid="u", supplier_id="sup-1",
                    allocations=[{"invoiceId": "inv-1", "amount": 1500.0}],
                    company_id="c",
                )
        assert ok is False
        assert "excede" in msg.lower()

    def test_register_rejects_duplicate_invoice(self):
        inv1 = _invoice_ref("inv-1", _invoice(5000.0))
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()), \
                 patch.object(SupplierInvoiceService, "validate_period"):
                ok, msg, _ = SupplierInvoiceService.register_multi_invoice_payment(
                    owner_uid="u", supplier_id="sup-1",
                    allocations=[{"invoiceId": "inv-1", "amount": 100.0}, {"invoiceId": "inv-1", "amount": 100.0}],
                    company_id="c",
                )
        assert ok is False
        assert "dos veces" in msg.lower()

    def test_register_rejects_wrong_supplier(self):
        inv1 = _invoice_ref("inv-1", _invoice(1000.0, supplier_id="otro"))
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()), \
                 patch.object(SupplierInvoiceService, "validate_period"):
                ok, msg, _ = SupplierInvoiceService.register_multi_invoice_payment(
                    owner_uid="u", supplier_id="sup-1",
                    allocations=[{"invoiceId": "inv-1", "amount": 100.0}],
                    company_id="c",
                )
        assert ok is False
        assert "proveedor" in msg.lower()

    def test_register_rejects_empty_allocations(self):
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=MagicMock()), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()):
                ok, msg, _ = SupplierInvoiceService.register_multi_invoice_payment(
                    owner_uid="u", supplier_id="sup-1", allocations=[], company_id="c",
                )
        assert ok is False


class TestApproveMultiInvoice:
    def test_approve_applies_balances_and_generates_single_entry(self):
        group = {
            "id": "g1", "supplierId": "sup-1", "supplierName": "Proveedor A",
            "total": 2000.0, "approvalStatus": "pending", "paymentDate": "2026-06-15",
            "paymentMethod": "Efectivo", "allocations": [
                {"invoiceId": "inv-1", "amount": 500.0},
                {"invoiceId": "inv-2", "amount": 1500.0},
            ],
        }
        inv1 = _invoice_ref("inv-1", _invoice(1000.0))
        inv2 = _invoice_ref("inv-2", _invoice(2000.0))
        g_ref = _group_ref(group)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1, "inv-2": inv2})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp_coll, \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 _delegating_tx(), \
                 patch("app.services.accounting_service.AccountingService.auto_generate_cxp_payment_entry",
                       return_value={"id": "entry-1"}) as gen:
                grp_coll.return_value.document.return_value = g_ref
                ok, msg = SupplierInvoiceService.approve_multi_invoice_payment(
                    owner_uid="u", group_id="g1", approved_by="Aprobador",
                    approved_by_uid="user-2", company_id="c",
                )
        assert ok is True
        # UN único asiento, por el total, con payment_id = group_id
        gen.assert_called_once()
        call_kwargs = gen.call_args.kwargs
        assert call_kwargs["payment_id"] == "g1"
        assert call_kwargs["amount"] == 2000.0
        # saldos actualizados
        assert inv1.update.call_args[0][0]["cxpRemainingBalance"] == 500.0
        assert inv2.update.call_args[0][0]["cxpRemainingBalance"] == 500.0
        # grupo marcado aprobado (en la transacción)
        group_updates = [c[0][0] for c in g_ref.update.call_args_list]
        assert any(u.get("approvalStatus") == "approved" for u in group_updates)

    def test_approve_idempotent(self):
        group = {"id": "g1", "approvalStatus": "approved", "allocations": []}
        g_ref = _group_ref(group)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=MagicMock()), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp_coll, \
                 _delegating_tx():
                grp_coll.return_value.document.return_value = g_ref
                ok, msg = SupplierInvoiceService.approve_multi_invoice_payment(
                    owner_uid="u", group_id="g1", company_id="c",
                )
        assert ok is True
        assert "ya estaba aprobado" in msg.lower()


class TestVoidMultiInvoice:
    def test_void_approved_reverses_accounting_and_restores_balances(self):
        group = {
            "id": "g1", "approvalStatus": "approved", "total": 2000.0,
            "allocations": [
                {"invoiceId": "inv-1", "amount": 500.0},
                {"invoiceId": "inv-2", "amount": 1500.0},
            ],
        }
        inv1 = _invoice_ref("inv-1", _invoice(1000.0, rem=500.0, cxp_status="Abonado"))
        inv2 = _invoice_ref("inv-2", _invoice(2000.0, rem=500.0, cxp_status="Abonado"))
        g_ref = _group_ref(group)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1, "inv-2": inv2})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp_coll, \
                 patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry") as void_acc:
                grp_coll.return_value.document.return_value = g_ref
                ok, msg = SupplierInvoiceService.void_multi_invoice_payment(
                    owner_uid="u", group_id="g1", voided_by="u", reason="Error", company_id="c",
                )
        assert ok is True
        void_acc.assert_called_once()
        assert inv1.update.call_args[0][0]["cxpRemainingBalance"] == 1000.0
        assert inv2.update.call_args[0][0]["cxpRemainingBalance"] == 2000.0
        assert g_ref.update.call_args[0][0]["approvalStatus"] == "voided"

    def test_void_pending_cancels_without_accounting_reversal(self):
        group = {
            "id": "g1", "approvalStatus": "pending",
            "allocations": [{"invoiceId": "inv-1", "amount": 500.0}],
        }
        inv1 = _invoice_ref("inv-1", _invoice(1000.0))
        g_ref = _group_ref(group)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp_coll, \
                 patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry") as void_acc:
                grp_coll.return_value.document.return_value = g_ref
                ok, msg = SupplierInvoiceService.void_multi_invoice_payment(
                    owner_uid="u", group_id="g1", company_id="c",
                )
        assert ok is True
        void_acc.assert_not_called()
        inv1.update.assert_not_called()


class TestRejectMultiInvoice:
    def test_reject_marks_rejected(self):
        group = {
            "id": "g1", "approvalStatus": "pending",
            "allocations": [{"invoiceId": "inv-1", "amount": 500.0}],
        }
        inv1 = _invoice_ref("inv-1", _invoice(1000.0))
        g_ref = _group_ref(group)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp_coll:
                grp_coll.return_value.document.return_value = g_ref
                ok, msg = SupplierInvoiceService.reject_multi_invoice_payment(
                    owner_uid="u", group_id="g1", company_id="c",
                )
        assert ok is True
        inv1.update.assert_not_called()
        assert g_ref.update.call_args[0][0]["approvalStatus"] == "rejected"
