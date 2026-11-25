"""Fase 1 — Contabilización de pagos de Cuentas por Pagar (CxP).

Cubre el asiento de pago (débito CxP, crédito banco/efectivo), su idempotencia,
el uso de la cuenta contable vinculada a la cuenta bancaria, la reversión
contable al anular el pago, y el cableado en SupplierInvoiceService.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from app.services.accounting_service import AccountingService
import app.services.supplier_invoice_service as mod
from app.services.supplier_invoice_service import SupplierInvoiceService


def _account(aid, code, name, usage, nature="acreedora"):
    return {
        "id": aid, "code": code, "name": name, "usage": usage,
        "group": "pasivos", "type": "movimiento", "nature": nature, "isActive": True,
    }


CXP = _account("acc-cxp", "2.1.1.1.01", "Cuentas por pagar a proveedores", "cxp")
BANCO = _account("acc-banco", "1.1.2.01", "Banco 1", "banco", "deudora")
EFECTIVO = _account("acc-caja", "1.1.1.01", "Caja", "efectivo", "deudora")
CHART = [CXP, BANCO, EFECTIVO]


class TestCxpPaymentEntry:
    def test_generates_balanced_entry(self):
        captured = {}

        def capture(company_id, data, sandbox=True):
            captured.update(data)
            return {"id": "entry-1", "number": "A-00001"}

        with patch("app.services.accounting_service.DatabaseService.get_chart_of_accounts", return_value=list(CHART)), \
             patch("app.services.accounting_service.DatabaseService.get_accounting_entries", return_value=[]), \
             patch("app.services.accounting_service.AccountingRulesService.get_rules", return_value=[]), \
             patch.object(AccountingService, "generate_entry", side_effect=capture):
            entry = AccountingService.auto_generate_cxp_payment_entry(
                "c1", "pay-1", 1000.0, "2026-06-15", payment_method="Efectivo",
            )

        assert entry == {"id": "entry-1", "number": "A-00001"}
        lines = captured["lines"]
        debit = [l for l in lines if l["debit"] > 0]
        credit = [l for l in lines if l["credit"] > 0]
        assert len(debit) == 1 and len(credit) == 1
        assert debit[0]["accountId"] == "acc-cxp"
        assert credit[0]["accountId"] == "acc-caja"
        assert captured["referenceType"] == "cxp_payment"
        assert captured["referenceId"] == "pay-1"
        assert captured["entryType"] == "cxp_payment"
        assert round(sum(l["debit"] for l in lines), 2) == 1000.0
        assert round(sum(l["credit"] for l in lines), 2) == 1000.0

    def test_idempotent_when_entry_exists(self):
        existing = [{"id": "e1", "status": "active", "referenceType": "cxp_payment", "referenceId": "pay-1"}]
        with patch("app.services.accounting_service.DatabaseService.get_chart_of_accounts", return_value=list(CHART)), \
             patch("app.services.accounting_service.DatabaseService.get_accounting_entries", return_value=existing), \
             patch("app.services.accounting_service.AccountingRulesService.get_rules", return_value=[]):
            assert AccountingService.auto_generate_cxp_payment_entry("c1", "pay-1", 100.0, "2026-06-15") is None

    def test_zero_amount_returns_none(self):
        assert AccountingService.auto_generate_cxp_payment_entry("c1", "pay-1", 0, "2026-06-15") is None

    def test_bank_account_linked_account_wins(self):
        captured = {}

        def capture(company_id, data, sandbox=True):
            captured.update(data)
            return {"id": "e1"}

        bank = {"id": "b1", "accountingAccountId": "acc-banco"}
        with patch("app.services.accounting_service.DatabaseService.get_chart_of_accounts", return_value=list(CHART)), \
             patch("app.services.accounting_service.DatabaseService.get_accounting_entries", return_value=[]), \
             patch("app.services.accounting_service.AccountingRulesService.get_rules", return_value=[]), \
             patch("app.services.accounting_service.DatabaseService.get_bank_account", return_value=bank), \
             patch.object(AccountingService, "generate_entry", side_effect=capture):
            AccountingService.auto_generate_cxp_payment_entry(
                "c1", "pay-1", 100.0, "2026-06-15", bank_account_id="b1", payment_method="Efectivo",
            )

        credit = [l for l in captured["lines"] if l["credit"] > 0]
        assert credit[0]["accountId"] == "acc-banco"

    def test_void_entry_reverses_accounting(self):
        entries = [{"id": "e1", "status": "active", "referenceType": "cxp_payment", "referenceId": "pay-1"}]
        with patch("app.services.accounting_service.DatabaseService.get_accounting_entries", return_value=entries), \
             patch.object(AccountingService, "void_entry", return_value={"id": "e1", "status": "voided"}) as ve:
            rid = AccountingService.void_cxp_payment_entry("c1", "pay-1", user_id="u", reason="err", sandbox=True)
        assert rid == "e1"
        ve.assert_called_once()


class _Snapshot:
    def __init__(self, exists, data=None):
        self.exists = exists
        self._data = data or {}

    def to_dict(self):
        return self._data


class _Ref:
    def __init__(self, data=None):
        self.data = data
        self.updated = []
        self.set_values = []

    def get(self, transaction=None):
        return _Snapshot(self.data is not None, self.data)


class _Tx:
    def __init__(self, account_ref, movement_ref):
        self.account_ref = account_ref
        self.movement_ref = movement_ref

    def set(self, ref, data):
        ref.set_values.append(data)

    def update(self, ref, data):
        ref.updated.append(data)


def test_bank_payment_transaction_writes_movement_and_balance_once():
    account_ref = _Ref({"id": "bank-1", "currentBalance": 1000.0})
    movement_ref = _Ref()
    tx = _Tx(account_ref, movement_ref)
    company_coll = MagicMock()
    company_coll.document.side_effect = [account_ref, movement_ref]

    with patch("app.services.db_service._company_coll", return_value=company_coll):
        result = SupplierInvoiceService._apply_bank_payment_tx(
            tx, "owner", "bank-1", "payment-1", 100.0,
            "Pago factura", "user", "company", True,
        )

    assert result["alreadyApplied"] is False
    assert len(movement_ref.set_values) == 1
    assert movement_ref.set_values[0]["amount"] == -100.0
    assert account_ref.updated[0]["currentBalance"] == 900.0


def test_bank_payment_transaction_is_idempotent_when_movement_exists():
    account_ref = _Ref({"id": "bank-1", "currentBalance": 900.0})
    movement_ref = _Ref({"id": "existing"})
    tx = _Tx(account_ref, movement_ref)
    company_coll = MagicMock()
    company_coll.document.side_effect = [account_ref, movement_ref]

    with patch("app.services.db_service._company_coll", return_value=company_coll):
        result = SupplierInvoiceService._apply_bank_payment_tx(
            tx, "owner", "bank-1", "payment-1", 100.0,
            "Pago factura", "user", "company", True,
        )

    assert result["alreadyApplied"] is True
    assert not movement_ref.set_values
    assert not account_ref.updated


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


def _doc_ref(data):
    doc = MagicMock()
    doc.get.return_value.exists = True
    doc.get.return_value.to_dict.return_value = data
    doc.collection.return_value.get.return_value = []
    return doc


class TestSupplierInvoicePaymentWiring:
    def test_save_payment_registers_pending_without_accounting(self):
        data = {
            "id": "inv-1", "status": "registrada", "cxpStatus": "Pendiente",
            "total": 1000.0, "cxpRemainingBalance": 1000.0,
            "supplierName": "Prov A", "supplierId": "sup-1",
            "supplierInvoiceNumber": "F001",
        }
        doc = _doc_ref(data)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 patch("app.services.accounting_service.AccountingService.auto_generate_cxp_payment_entry") as gen:
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.save_payment(
                    owner_uid="u", invoice_id="inv-1", payment_amount=500,
                    sandbox=True, company_id="c", requested_by_uid="user-1",
                )
        assert ok is True
        assert "pendiente de aprobación" in msg.lower()
        gen.assert_not_called()
        doc.update.assert_not_called()
        pay_doc = doc.collection.return_value.document.return_value
        set_payload = pay_doc.set.call_args[0][0]
        assert set_payload["approvalStatus"] == "pending"
        assert set_payload["requestedBy"] == "user-1"

    def test_approve_payment_applies_balance_and_accounting(self):
        data = {
            "id": "inv-1", "status": "registrada", "cxpStatus": "Pendiente",
            "total": 1000.0, "cxpRemainingBalance": 1000.0,
            "supplierName": "Prov A", "supplierId": "sup-1",
            "supplierInvoiceNumber": "F001",
        }
        doc = _doc_ref(data)
        pay_doc = _pay_doc({"amount": 500.0, "approvalStatus": "pending",
                            "paymentDate": "2026-06-15", "method": "Efectivo"})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 _delegating_tx(), \
                 patch("app.services.accounting_service.AccountingService.auto_generate_cxp_payment_entry",
                       return_value={"id": "entry-1"}) as gen:
                coll_ref.return_value.document.return_value = doc
                doc.collection.return_value.document.return_value = pay_doc
                ok, msg = SupplierInvoiceService.approve_payment(
                    owner_uid="u", invoice_id="inv-1", payment_id="pay-1",
                    approved_by="Aprobador", approved_by_uid="user-2",
                    sandbox=True, company_id="c",
                )
        assert ok is True
        gen.assert_called_once()
        expense_update = doc.update.call_args[0][0]
        assert expense_update["cxpRemainingBalance"] == 500.0
        assert expense_update["cxpStatus"] == "Abonado"
        pay_updates = [c[0][0] for c in pay_doc.update.call_args_list]
        approved_update = next(u for u in pay_updates if u.get("approvalStatus") == "approved")
        assert approved_update["approvedByUid"] == "user-2"
        assert any(u.get("accountingStatus") == "posted" for u in pay_updates)

    def test_reject_payment_marks_rejected_without_applying(self):
        data = {"id": "inv-1", "status": "registrada", "cxpStatus": "Pendiente",
                "total": 1000.0, "cxpRemainingBalance": 1000.0}
        doc = _doc_ref(data)
        pay_doc = _pay_doc({"amount": 500.0, "approvalStatus": "pending"})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch("app.services.accounting_service.AccountingService.auto_generate_cxp_payment_entry") as gen:
                coll_ref.return_value.document.return_value = doc
                doc.collection.return_value.document.return_value = pay_doc
                ok, msg = SupplierInvoiceService.reject_payment(
                    owner_uid="u", invoice_id="inv-1", payment_id="pay-1",
                    rejected_by="Aprobador", sandbox=True, company_id="c",
                )
        assert ok is True
        gen.assert_not_called()
        doc.update.assert_not_called()
        pay_update = pay_doc.update.call_args[0][0]
        assert pay_update["approvalStatus"] == "rejected"

    def test_void_payment_reverses_accounting_entry(self):
        data = {"id": "inv-1", "status": "registrada", "cxpStatus": "Abonado",
                "total": 1000.0, "cxpRemainingBalance": 500.0}
        doc = _doc_ref(data)
        pay_doc = MagicMock()
        pay_doc.get.return_value.exists = True
        pay_doc.get.return_value.to_dict.return_value = {"amount": 500.0, "approvalStatus": "approved"}
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry") as void:
                coll_ref.return_value.document.return_value = doc
                doc.collection.return_value.document.return_value = pay_doc
                ok, msg = SupplierInvoiceService.void_payment(
                    owner_uid="u", invoice_id="inv-1", payment_id="pay-1",
                    sandbox=True, company_id="c",
                )
        assert ok is True
        void.assert_called_once()
        pay_doc.delete.assert_called_once()


import app.services.db_service as dbmod
from app.services.db_service import DatabaseService
from app.services.accounting_service import AccountingPostingError


def _expense_doc(data):
    doc = MagicMock()
    doc.get.return_value.exists = True
    doc.get.return_value.to_dict.return_value = data
    return doc


def _pay_doc(data):
    p = MagicMock()
    p.get.return_value.exists = True
    p.get.return_value.to_dict.return_value = data
    return p


class TestExpensePaymentVoid:
    def test_void_reverses_accounting_and_restores_balance(self):
        expense = {"amount": 1000.0, "cxpRemainingBalance": 500.0, "cxpStatus": "Abonado"}
        pay = {"amount": 500.0, "status": "active"}
        doc = _expense_doc(expense)
        payd = _pay_doc(pay)
        with patch.object(dbmod, "firebase_initialized", True), \
             patch.object(dbmod, "_company_coll") as coll, \
             patch.object(dbmod, "_invalidate_expenses"), \
             patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry") as void_acc:
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = payd
            ok, msg = DatabaseService.void_cxp_payment(
                "u", "exp-1", "pay-1", voided_by="Admin", reason="Error",
                company_id="c", sandbox=True,
            )
        assert ok is True
        void_acc.assert_called_once()
        payd.delete.assert_not_called()
        expense_update = doc.update.call_args[0][0]
        assert expense_update["cxpRemainingBalance"] == 1000.0
        assert expense_update["cxpStatus"] == "Pendiente"
        pay_update = payd.update.call_args[0][0]
        assert pay_update["status"] == "voided"
        assert pay_update["voidedBy"] == "Admin"

    def test_void_blocks_when_accounting_reversal_fails(self):
        expense = {"amount": 1000.0, "cxpRemainingBalance": 500.0, "cxpStatus": "Abonado"}
        pay = {"amount": 500.0, "status": "active"}
        doc = _expense_doc(expense)
        payd = _pay_doc(pay)
        with patch.object(dbmod, "firebase_initialized", True), \
             patch.object(dbmod, "_company_coll") as coll, \
             patch.object(dbmod, "_invalidate_expenses"), \
             patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry",
                   side_effect=AccountingPostingError("no persistió")):
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = payd
            ok, msg = DatabaseService.void_cxp_payment("u", "exp-1", "pay-1", company_id="c")
        assert ok is False
        assert "asiento" in msg.lower()
        doc.update.assert_not_called()
        payd.update.assert_not_called()
        payd.delete.assert_not_called()

    def test_void_is_idempotent(self):
        expense = {"amount": 1000.0, "cxpRemainingBalance": 500.0, "cxpStatus": "Abonado"}
        pay = {"amount": 500.0, "status": "voided"}
        doc = _expense_doc(expense)
        payd = _pay_doc(pay)
        with patch.object(dbmod, "firebase_initialized", True), \
             patch.object(dbmod, "_company_coll") as coll, \
             patch.object(dbmod, "_invalidate_expenses"), \
             patch("app.services.accounting_service.AccountingService.void_cxp_payment_entry") as void_acc:
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = payd
            ok, msg = DatabaseService.void_cxp_payment("u", "exp-1", "pay-1", company_id="c")
        assert ok is True
        assert "ya estaba anulado" in msg.lower()
        void_acc.assert_not_called()

    def test_get_cxp_payments_excludes_voided(self):
        v = MagicMock()
        v.id = "pay-void"
        v.to_dict.return_value = {"amount": 100.0, "status": "voided", "paymentDate": "2026-06-01T00:00:00+00:00"}
        a = MagicMock()
        a.id = "pay-active"
        a.to_dict.return_value = {"amount": 200.0, "status": "active", "paymentDate": "2026-06-02T00:00:00+00:00"}
        with patch.object(dbmod, "firebase_initialized", True), \
             patch.object(dbmod, "_company_coll") as coll_ref:
            coll_ref.return_value.document.return_value.collection.return_value.get.return_value = [v, a]
            payments = DatabaseService.get_cxp_payments("u", "exp-1", company_id="c")
        assert [p["id"] for p in payments] == ["pay-active"]
        assert payments[0]["amount"] == 200.0


class TestExpensePaymentApproval:
    def test_approve_cxp_payment_applies_balance_and_accounting(self):
        expense = {"amount": 1000.0, "cxpRemainingBalance": 1000.0, "cxpStatus": "Pendiente",
                   "providerName": "Prov A", "paymentMethod": "Efectivo"}
        pay = {"amount": 500.0, "approvalStatus": "pending", "paymentDate": "2026-06-15"}
        doc = _expense_doc(expense)
        payd = _pay_doc(pay)
        with patch.object(dbmod, "firebase_initialized", True), \
             patch.object(dbmod, "_company_coll") as coll, \
             patch.object(dbmod, "_invalidate_expenses"), \
             patch("app.services.fiscal_period_service.FiscalPeriodService.validate_period_open"), \
             _delegating_tx(), \
             patch("app.services.accounting_service.AccountingService.auto_generate_cxp_payment_entry",
                   return_value={"id": "entry-1"}) as gen:
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = payd
            ok, msg = DatabaseService.approve_cxp_payment(
                "u", "exp-1", "pay-1", approved_by="Aprobador", approved_by_uid="user-2",
                company_id="c", sandbox=True,
            )
        assert ok is True
        gen.assert_called_once()
        assert doc.update.call_args[0][0]["cxpRemainingBalance"] == 500.0
        pay_updates = [c[0][0] for c in payd.update.call_args_list]
        approved_update = next(u for u in pay_updates if u.get("approvalStatus") == "approved")
        assert approved_update["approvedByUid"] == "user-2"

    def test_approve_cxp_payment_idempotent_under_reapproval(self):
        expense = {"amount": 1000.0, "cxpRemainingBalance": 500.0, "cxpStatus": "Abonado"}
        pay = {"amount": 500.0, "approvalStatus": "approved", "paymentDate": "2026-06-15"}
        doc = _expense_doc(expense)
        payd = _pay_doc(pay)
        with patch.object(dbmod, "firebase_initialized", True), \
             patch.object(dbmod, "_company_coll") as coll, \
             patch.object(dbmod, "_invalidate_expenses"), \
             patch("app.services.fiscal_period_service.FiscalPeriodService.validate_period_open"), \
             _delegating_tx():
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = payd
            ok, msg = DatabaseService.approve_cxp_payment("u", "exp-1", "pay-1", company_id="c")
        assert ok is True
        assert "ya estaba aprobado" in msg.lower()
        doc.update.assert_not_called()

    def test_reject_cxp_payment_marks_rejected(self):
        expense = {"amount": 1000.0, "cxpRemainingBalance": 1000.0}
        pay = {"amount": 500.0, "approvalStatus": "pending"}
        doc = _expense_doc(expense)
        payd = _pay_doc(pay)
        with patch.object(dbmod, "firebase_initialized", True), \
             patch.object(dbmod, "_company_coll") as coll, \
             patch.object(dbmod, "_invalidate_expenses"):
            coll.return_value.document.return_value = doc
            doc.collection.return_value.document.return_value = payd
            ok, msg = DatabaseService.reject_cxp_payment("u", "exp-1", "pay-1", company_id="c")
        assert ok is True
        doc.update.assert_not_called()
        assert payd.update.call_args[0][0]["approvalStatus"] == "rejected"


class TestPaymentSoDMatrix:
    def test_can_approve_payments_conflicts_with_registration_permissions(self):
        from app.utils.decorators import SOD_CONFLICT_MATRIX
        conflicts = SOD_CONFLICT_MATRIX["canApprovePayments"]["conflicts"]
        assert "canManagePurchaseCXP" in conflicts
        assert "canExpenses" in conflicts
        assert "canCreateSupplier" in conflicts


class TestCanVoidPaymentPermission:
    def test_can_void_payment_permission_is_defined(self):
        from app.web.invoices import ALL_PERMISSION_KEYS, PERMISSION_GROUPS
        assert "canVoidPayment" in ALL_PERMISSION_KEYS
        grouped = {p for group in PERMISSION_GROUPS for p in group["perms"]}
        assert "canVoidPayment" in grouped
