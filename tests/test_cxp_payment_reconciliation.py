from unittest.mock import patch

from app.services.cxp_payment_reconciliation_service import CxpPaymentReconciliationService


def test_scan_detects_bank_and_accounting_gaps():
    invoice = {"id": "inv-1", "supplierName": "Proveedor"}
    payment = {
        "id": "pay-1", "approvalStatus": "approved", "amount": 100,
        "bankAccountId": "bank-1", "bankStatus": "error", "accountingStatus": "pending",
    }
    with patch("app.services.cxp_payment_reconciliation_service.SupplierInvoiceService.get_all", return_value=[invoice]), \
            patch("app.services.cxp_payment_reconciliation_service.SupplierInvoiceService.get_payments", return_value=[payment]):
        result = CxpPaymentReconciliationService.scan("owner", "company")

    assert result[0]["paymentId"] == "pay-1"
    assert set(result[0]["issues"]) == {"bank_pending_or_error", "accounting_pending_or_error"}


def test_scan_ignores_fully_posted_payment():
    invoice = {"id": "inv-1"}
    payment = {
        "id": "pay-1", "approvalStatus": "approved", "bankAccountId": "bank-1",
        "bankStatus": "posted", "accountingStatus": "posted",
    }
    with patch("app.services.cxp_payment_reconciliation_service.SupplierInvoiceService.get_all", return_value=[invoice]), \
            patch("app.services.cxp_payment_reconciliation_service.SupplierInvoiceService.get_payments", return_value=[payment]):
        assert CxpPaymentReconciliationService.scan("owner", "company") == []


def test_repair_reprocesses_missing_bank_movement():
    invoice = {"id": "inv-1", "ncf": "E3101", "supplierName": "Proveedor"}
    payment = {
        "id": "pay-1", "approvalStatus": "approved", "amount": 100,
        "bankAccountId": "bank-1", "bankStatus": "error", "accountingStatus": "posted",
    }
    with patch("app.services.cxp_payment_reconciliation_service.SupplierInvoiceService.get", return_value=invoice), \
            patch("app.services.cxp_payment_reconciliation_service.SupplierInvoiceService.get_payments", return_value=[payment]), \
            patch("app.services.cxp_payment_reconciliation_service.run_firestore_transaction", return_value={"movementId": "movement-1"}, create=True), \
            patch("app.services.cxp_payment_reconciliation_service.SupplierInvoiceService._coll_ref") as coll_ref:
        coll_ref.return_value.document.return_value.collection.return_value.document.return_value.update = lambda data: None
        ok, message = CxpPaymentReconciliationService.repair_payment("owner", "company", "inv-1", "pay-1")

    assert ok is True
    assert "conciliado" in message.lower()
