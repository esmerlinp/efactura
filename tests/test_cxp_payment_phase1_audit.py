"""Auditoría de cierre de Fase 1 — consistencia integral del motor de pagos CxP.

Verifica que aprobación, anulación y pagos agrupados mantengan consistentes:
- el banco (se debita/crédita una sola vez),
- los asientos contables (un único asiento por pago, sin duplicar),
- los saldos de cada factura,
- y que el flujo individual siga funcionando.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

import app.services.supplier_invoice_service as mod
from app.services.supplier_invoice_service import SupplierInvoiceService


def _patch_firebase():
    stack = ExitStack()
    stack.enter_context(patch.object(mod, "firebase_initialized", True))
    stack.enter_context(patch.object(mod, "db_firestore", MagicMock()))
    return stack


def _delegating_tx():
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


def _invoice_ref(invoice_id, data, pending=None):
    ref = MagicMock()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = data
    ref.get.return_value = snap
    coll = MagicMock()
    coll.get.return_value = pending or []
    ref.collection.return_value = coll
    return ref


def _stateful_group_ref(group):
    ref = MagicMock()
    state = dict(group)
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.side_effect = lambda: dict(state)
    ref.get.return_value = snap
    ref.update.side_effect = lambda u: state.update(u)
    return ref


def _mock_coll_ref(invoices):
    coll = MagicMock()
    coll.document.side_effect = lambda iid: invoices[iid]
    return coll


def _invoice(total, supplier_id="sup-1", rem=None, cxp_status="Pendiente"):
    return {
        "id": "x", "total": total, "supplierId": supplier_id, "supplierName": "Proveedor A",
        "cxpStatus": cxp_status, "cxpRemainingBalance": total if rem is None else rem,
        "dueDate": "2026-12-31",
    }


class TestBankConsistency:
    def test_multi_invoice_approve_debits_bank_once(self):
        group = {
            "id": "g1", "supplierId": "sup-1", "supplierName": "P", "total": 2000.0,
            "approvalStatus": "pending", "paymentDate": "2026-06-15", "bankAccountId": "bank-1",
            "allocations": [{"invoiceId": "inv-1", "amount": 500.0}, {"invoiceId": "inv-2", "amount": 1500.0}],
        }
        inv1 = _invoice_ref("inv-1", _invoice(1000.0))
        inv2 = _invoice_ref("inv-2", _invoice(2000.0))
        g_ref = _stateful_group_ref(group)
        bank = {"id": "bank-1", "currentBalance": 10000.0}
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1, "inv-2": inv2})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp, \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 _delegating_tx(), \
                 patch("app.services.accounting_service.AccountingService.auto_generate_cxp_payment_entry",
                       return_value={"id": "entry-1"}) as gen, \
                 patch("app.services.db_service.DatabaseService.get_bank_account", return_value=dict(bank)), \
                 patch("app.services.db_service.DatabaseService.save_bank_account") as save_bank:
                grp.return_value.document.return_value = g_ref
                ok, msg = SupplierInvoiceService.approve_multi_invoice_payment(
                    owner_uid="u", group_id="g1", company_id="c",
                )
        assert ok is True
        gen.assert_called_once()
        save_bank.assert_called_once()
        assert save_bank.call_args[0][2]["currentBalance"] == 8000.0

    def test_double_approve_does_not_duplicate(self):
        group = {
            "id": "g1", "supplierId": "sup-1", "supplierName": "P", "total": 2000.0,
            "approvalStatus": "pending", "paymentDate": "2026-06-15", "bankAccountId": "bank-1",
            "allocations": [{"invoiceId": "inv-1", "amount": 500.0}, {"invoiceId": "inv-2", "amount": 1500.0}],
        }
        inv1 = _invoice_ref("inv-1", _invoice(1000.0))
        inv2 = _invoice_ref("inv-2", _invoice(2000.0))
        g_ref = _stateful_group_ref(group)
        bank = {"id": "bank-1", "currentBalance": 10000.0}
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1, "inv-2": inv2})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp, \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 _delegating_tx(), \
                 patch("app.services.accounting_service.AccountingService.auto_generate_cxp_payment_entry",
                       return_value={"id": "entry-1"}) as gen, \
                 patch("app.services.db_service.DatabaseService.get_bank_account", return_value=dict(bank)), \
                 patch("app.services.db_service.DatabaseService.save_bank_account") as save_bank:
                grp.return_value.document.return_value = g_ref
                ok1, _ = SupplierInvoiceService.approve_multi_invoice_payment(owner_uid="u", group_id="g1", company_id="c")
                ok2, msg2 = SupplierInvoiceService.approve_multi_invoice_payment(owner_uid="u", group_id="g1", company_id="c")
        assert ok1 is True and ok2 is True
        assert "ya estaba aprobado" in msg2.lower()
        gen.assert_called_once()
        save_bank.assert_called_once()

    def test_multi_invoice_void_credits_bank_once(self):
        group = {
            "id": "g1", "supplierId": "sup-1", "supplierName": "P", "total": 2000.0,
            "approvalStatus": "approved", "bankAccountId": "bank-1",
            "allocations": [{"invoiceId": "inv-1", "amount": 500.0}, {"invoiceId": "inv-2", "amount": 1500.0}],
        }
        inv1 = _invoice_ref("inv-1", _invoice(1000.0, rem=500.0, cxp_status="Abonado"))
        inv2 = _invoice_ref("inv-2", _invoice(2000.0, rem=500.0, cxp_status="Abonado"))
        g_ref = _stateful_group_ref(group)
        bank = {"id": "bank-1", "currentBalance": 8000.0}
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv1, "inv-2": inv2})), \
                 patch.object(SupplierInvoiceService, "_group_coll_ref", return_value=MagicMock()) as grp, \
                 patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry") as void_acc, \
                 patch("app.services.db_service.DatabaseService.get_bank_account", return_value=dict(bank)), \
                 patch("app.services.db_service.DatabaseService.save_bank_account") as save_bank:
                grp.return_value.document.return_value = g_ref
                ok, msg = SupplierInvoiceService.void_multi_invoice_payment(
                    owner_uid="u", group_id="g1", voided_by="u", reason="Error", company_id="c",
                )
        assert ok is True
        void_acc.assert_called_once()
        save_bank.assert_called_once()
        assert save_bank.call_args[0][2]["currentBalance"] == 10000.0
        assert inv1.update.call_args[0][0]["cxpRemainingBalance"] == 1000.0
        assert inv2.update.call_args[0][0]["cxpRemainingBalance"] == 2000.0


class TestIndividualFlowStillWorks:
    def test_register_approve_void_single_payment(self):
        inv = _invoice_ref("inv-1", _invoice(1000.0))
        bank = {"id": "bank-1", "currentBalance": 10000.0}
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv})), \
                 patch.object(SupplierInvoiceService, "validate_period"):
                ok, msg = SupplierInvoiceService.save_payment(
                    owner_uid="u", invoice_id="inv-1", payment_amount=500.0,
                    company_id="c", requested_by_uid="user-1",
                )
                assert ok is True and "pendiente" in msg.lower()
                inv.update.assert_not_called()

            pay_ref = MagicMock()
            pay_ref.get.return_value.exists = True
            pay_ref.get.return_value.to_dict.return_value = {
                "amount": 500.0, "approvalStatus": "pending", "paymentDate": "2026-06-15",
                "method": "Efectivo", "bankAccountId": "bank-1",
            }
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv})), \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 _delegating_tx(), \
                 patch("app.services.accounting_service.AccountingService.auto_generate_cxp_payment_entry",
                       return_value={"id": "entry-1"}) as gen, \
                 patch("app.services.db_service.DatabaseService.get_bank_account", return_value=dict(bank)), \
                 patch("app.services.db_service.DatabaseService.save_bank_account") as save_bank:
                inv.collection.return_value.document.return_value = pay_ref
                ok, msg = SupplierInvoiceService.approve_payment(
                    owner_uid="u", invoice_id="inv-1", payment_id="pay-1",
                    company_id="c", approved_by="A", approved_by_uid="user-2",
                )
                assert ok is True
                gen.assert_called_once()
                save_bank.assert_called_once()

            void_ref = MagicMock()
            void_ref.get.return_value.exists = True
            void_ref.get.return_value.to_dict.return_value = {
                "amount": 500.0, "approvalStatus": "approved", "bankAccountId": "bank-1",
            }
            with patch.object(SupplierInvoiceService, "_coll_ref", return_value=_mock_coll_ref({"inv-1": inv})), \
                 patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry") as void_acc, \
                 patch("app.services.db_service.DatabaseService.get_bank_account", return_value={"id": "bank-1", "currentBalance": 9500.0}), \
                 patch("app.services.db_service.DatabaseService.save_bank_account") as save_bank:
                inv.collection.return_value.document.return_value = void_ref
                ok, msg = SupplierInvoiceService.void_payment(
                    owner_uid="u", invoice_id="inv-1", payment_id="pay-1", company_id="c",
                )
                assert ok is True
                void_acc.assert_called_once()
                save_bank.assert_called_once()
                assert save_bank.call_args[0][2]["currentBalance"] == 10000.0
