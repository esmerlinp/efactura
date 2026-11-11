from app.web.portal import (
    PortalDbService,
    PORTAL_STATUS_CANCELLED,
    PORTAL_STATUS_OVERDUE,
    PORTAL_STATUS_PAID,
    PORTAL_STATUS_PARTIAL,
    PORTAL_STATUS_PENDING,
    PORTAL_STATUS_REVIEW,
    resolve_portal_invoice_status,
)


class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def where(self, filter=None):
        return self

    def get(self):
        return self._docs

    def document(self, doc_id=None):
        return self

    def collection(self, name):
        return self


class _FakeDb:
    def __init__(self, docs):
        self._collection = _FakeCollection(docs)

    def collection(self, *args, **kwargs):
        return self._collection


def _invoice(**overrides):
    data = {
        "id": "inv-1",
        "clientId": "client-1",
        "invoiceNumber": "FAC-001",
        "status": "Emitida",
        "date": "2026-01-10",
        "dueDate": "2099-12-31",
        "netPayable": 100.0,
        "total": 100.0,
        "remainingBalance": 100.0,
    }
    data.update(overrides)
    return data


def test_dgii_pending_invoice_shows_pending_payment():
    invoice = _invoice(status="Emitida", dgiiStatus="PENDING")
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_PENDING


def test_mixed_pending_dgii_status_does_not_leak():
    invoice = _invoice(status="Pendiente DGII", dgiiStatus="PENDING")
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_PENDING


def test_paid_invoice_with_pending_dgii_status_shows_paid():
    invoice = _invoice(status="Pendiente DGII", dgiiStatus="PENDING", remainingBalance=0.0)
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_PAID


def test_dgii_rejected_invoice_is_not_shown_as_rejected():
    invoice = _invoice(status="Rechazado DGII", dgiiStatus="REJECTED")
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_PENDING


def test_dgii_contingency_invoice_shows_pending_payment():
    invoice = _invoice(status="Emitida", dgiiStatus="CONTINGENCY", emisionMode="FALLBACK")
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_PENDING


def test_paid_invoice_ignores_dgii_rejection():
    invoice = _invoice(status="Cobrada", dgiiStatus="REJECTED", remainingBalance=0.0)
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_PAID


def test_partial_payment_shows_partial_status():
    invoice = _invoice(status="Parcialmente Cobrada", remainingBalance=40.0)
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_PARTIAL


def test_overdue_invoice_shows_overdue():
    invoice = _invoice(status="Emitida", dueDate="2020-01-01")
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_OVERDUE


def test_payment_proof_in_review_shows_review():
    invoice = _invoice(status="Revisión de Pago")
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_REVIEW


def test_cancelled_invoice_shows_cancelled():
    invoice = _invoice(status="Anulada")
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_CANCELLED


def test_quotation_status_is_preserved():
    invoice = _invoice(isQuotation=True, status="Pendiente Aut. Cliente")
    assert resolve_portal_invoice_status(invoice) == "Pendiente Aut. Cliente"


def test_expired_quotation_shows_overdue():
    invoice = _invoice(isQuotation=True, status="Pendiente Aut. Cliente", quotationExpired=True)
    assert resolve_portal_invoice_status(invoice) == PORTAL_STATUS_OVERDUE


def test_get_client_invoices_adds_commercial_status_and_keeps_dgii_status(monkeypatch):
    void_invoice = _invoice(id="inv-void", status="Anulada")
    void_invoice.pop("remainingBalance")
    docs = [
        _FakeDoc("draft-1", _invoice(id="draft-1", status="Borrador")),
        _FakeDoc("inv-pending", _invoice(
            id="inv-pending",
            status="Pendiente DGII",
            dgiiStatus="PENDING",
        )),
        _FakeDoc("inv-void", void_invoice),
    ]
    monkeypatch.setattr("app.web.portal.db_firestore", _FakeDb(docs))

    invoices = PortalDbService.get_client_invoices(
        owner_uid="owner-1",
        client_id="client-1",
        sandbox=True,
        company_id="company-1",
    )
    by_id = {inv["id"]: inv for inv in invoices}

    assert "draft-1" not in by_id
    assert by_id["inv-pending"]["status"] == "Pendiente DGII"
    assert by_id["inv-pending"]["dgiiStatus"] == "PENDING"
    assert by_id["inv-pending"]["portalStatus"] == PORTAL_STATUS_PENDING
    assert by_id["inv-void"]["portalStatus"] == PORTAL_STATUS_CANCELLED
    assert by_id["inv-void"]["remainingBalance"] == 0.0


def test_document_detail_defines_payment_modal_handlers(app):
    from flask import render_template

    invoice = {
        "id": "inv-payable",
        "invoiceNumber": "FAC-001",
        "isQuotation": False,
        "status": "Emitida",
        "portalStatus": PORTAL_STATUS_PENDING,
        "date": "2026-01-10",
        "dueDate": "2099-12-31",
        "currency": "DOP",
        "paymentType": "Contado",
        "subtotal": 100.0,
        "totalITBIS": 18.0,
        "discountAmount": 0.0,
        "total": 118.0,
        "netPayable": 118.0,
        "totalPaid": 0.0,
        "remainingBalance": 118.0,
        "items": [],
    }
    company = {
        "companyName": "Empresa Portal SRL",
        "companyRNC": "131880681",
    }

    with app.test_request_context():
        rendered = render_template(
            "portal/document_detail.html",
            invoice=invoice,
            company=company,
            client={"razonSocial": "Cliente Portal"},
            branch=None,
            today_str="2026-01-10",
            owner_uid="test-owner",
            sandbox=True,
            paypal_configured=True,
            comments=[],
        )

    assert 'onclick="openPaymentOptionsModal()"' in rendered
    assert "function openPaymentOptionsModal()" in rendered
    assert "function closePaymentModal()" in rendered
    assert 'id="payment-modal"' in rendered
    assert "/portal/pago/inv-payable?method=paypal" in rendered
    assert "/portal/pago/inv-payable?method=proof" in rendered
