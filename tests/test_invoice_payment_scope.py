from unittest.mock import patch

from flask import session

from app.web import invoices as invoices_module


class _DocRef:
    def __init__(self, path):
        self.path = path
        self.updates = []

    def update(self, data):
        self.updates.append(data)


class _Collection:
    def __init__(self, path):
        self.path = path
        self.refs = []

    def document(self, doc_id):
        ref = _DocRef(f"{self.path}/{doc_id}")
        self.refs.append(ref)
        return ref


def _set_session(company_id="comp-1", sandbox=True):
    session["user"] = {
        "ownerUID": "owner-1",
        "email": "admin@example.com",
        "uid": "user-1",
        "name": "Admin",
    }
    session["selected_company_id"] = company_id
    session["is_sandbox_mode"] = sandbox


def _invoice(**overrides):
    data = {
        "id": "inv-1",
        "invoiceNumber": "FAC-001",
        "clientId": "",
        "clientEmail": "",
        "clientName": "Cliente",
        "status": "Revisión de Pago",
        "totalPaid": 0.0,
        "netPayable": 100.0,
        "remainingBalance": 100.0,
    }
    data.update(overrides)
    return data


def _assert_company_scope_updated(collection):
    assert len(collection.refs) == 1
    assert collection.refs[0].path == "companies/comp-1/sandbox_invoices/inv-1"


def test_approve_payment_proof_updates_company_scoped_invoice(app):
    collection = _Collection("companies/comp-1/sandbox_invoices")

    with app.test_request_context(
        "/invoices/inv-1/approve_payment_proof",
        method="POST",
        data={"amount": "100"},
    ):
        _set_session()
        with patch.object(invoices_module, "check_permission", return_value=True), \
             patch.object(invoices_module.DatabaseService, "get_invoice", return_value=_invoice()), \
             patch.object(invoices_module.DatabaseService, "register_invoice_payment"), \
             patch.object(invoices_module, "_company_coll", return_value=collection), \
             patch("app.services.audit_service.AuditService.log_from_request"):
            response = invoices_module.approve_payment_proof("inv-1")

    assert response.status_code == 302
    _assert_company_scope_updated(collection)
    assert "pendingPaymentProof" in collection.refs[0].updates[0]


def test_reject_payment_proof_updates_company_scoped_invoice(app):
    collection = _Collection("companies/comp-1/sandbox_invoices")

    with app.test_request_context(
        "/invoices/inv-1/reject_payment_proof",
        method="POST",
        data={"rejectionReason": "Comprobante ilegible"},
    ):
        _set_session()
        with patch.object(invoices_module, "check_permission", return_value=True), \
             patch.object(invoices_module.DatabaseService, "get_invoice", return_value=_invoice()), \
             patch.object(invoices_module, "_company_coll", return_value=collection), \
             patch("app.services.audit_service.AuditService.log_from_request"):
            response = invoices_module.reject_payment_proof("inv-1")

    assert response.status_code == 302
    _assert_company_scope_updated(collection)
    update = collection.refs[0].updates[0]
    assert update["status"] == "Emitida"
    assert "pendingPaymentProof" in update


def test_send_receipt_email_returns_json(app, monkeypatch):
    monkeypatch.setitem(app.config, "SMTP_USER", "smtp@example.com")
    monkeypatch.setitem(app.config, "SMTP_PASSWORD", "secret")
    company = {"tradeName": "Empresa Demo", "companyRNC": "131880681", "colorMarca": "#10b981"}

    with app.test_request_context(
        "/invoices/inv-1/send-receipt",
        method="POST",
        json={
            "email": "cliente@example.com",
            "paymentId": "pay-123456789",
            "paymentDate": "11/11/2026",
            "paymentMethod": "Transferencia",
            "amount": 100,
        },
    ):
        _set_session()
        with patch.object(invoices_module.DatabaseService, "get_invoice", return_value=_invoice()), \
             patch.object(invoices_module.DatabaseService, "get_company_profile", return_value=company), \
             patch("app.services.mailer.Mailer.send", return_value=True):
            response = invoices_module.send_receipt_email("inv-1")

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert "cliente@example.com" in body["message"]


def test_send_receipt_email_without_smtp_returns_json(app, monkeypatch):
    monkeypatch.setitem(app.config, "SMTP_USER", "")
    monkeypatch.setitem(app.config, "SMTP_PASSWORD", "")

    with app.test_request_context(
        "/invoices/inv-1/send-receipt",
        method="POST",
        json={"email": "cliente@example.com"},
    ):
        _set_session()
        with patch.object(invoices_module.DatabaseService, "get_invoice", return_value=_invoice()), \
             patch.object(invoices_module.DatabaseService, "get_company_profile", return_value={}):
            response = invoices_module.send_receipt_email("inv-1")

    body, status = response
    assert status == 503
    assert body.get_json()["success"] is False
