"""Tests del correo de la Carta de Retención de compras/proveedor.

Verifica que además de la carta, se adjunten la representación impresa (PDF)
del comprobante del proveedor y su XML firmado cuando el comprobante fue
emitido, igual que el correo de factura de ventas.
"""

from unittest.mock import MagicMock, patch

from flask import request, session


INVOICE = {
    "id": "sinv-1",
    "ncf": "B0100000001",
    "encf": "E4100000001",
    "supplierName": "Proveedor Demo SRL",
    "supplierRnc": "131-00000-1",
    "supplierCedula": "001-0000000-1",
    "email": "proveedor@test.com",
    "date": "2026-10-12",
    "total": 1180.0,
    "itbis": 180.0,
    "retainedISR": 0.10,
    "retainedITBIS": 0.30,
}


CTX = {
    "doc_num": "B0100000001",
    "inv_num": "B0100000001",
    "xml_content": "<?xml version='1.0'?><eCF></eCF>",
    "qr_url": "https://dgii.gov.do/validaecf",
    "qr_base64": "QUJD",
    "fecha_firma_str": "12-10-2026 12:00:00",
    "branch": {"id": "b1", "name": "Sede"},
}


def _post_email(app, invoice, ctx):
    from app.web.purchase_orders import supplier_retention_letter_email

    with app.test_request_context(
        "/purchase-orders/invoices/sinv-1/retention-letter/email",
        method="POST",
        data={"email": "proveedor@test.com"},
    ):
        session["user"] = {"ownerUID": "user-test", "name": "Admin", "cedula": "001-0000000-9"}
        session["selected_company_id"] = "comp-1"
        session["is_sandbox_mode"] = True

        app.config["SMTP_USER"] = "smtp@example.com"
        app.config["SMTP_PASSWORD"] = "password123"

        with patch("app.web.purchase_orders.check_permission", return_value=True), \
             patch("app.web.purchase_orders.SupplierInvoiceService.get", return_value=invoice), \
             patch("app.web.purchase_orders.DatabaseService.get_company_profile", return_value={"companyName": "Empresa Test", "companyRNC": "101-00000-1"}), \
             patch("app.web.purchase_orders._supplier_comprobante_context", return_value=ctx), \
             patch("app.web.purchase_orders.WEASYPRINT_AVAILABLE", True), \
             patch("app.web.purchase_orders.WeasyprintHTML") as mock_html, \
             patch("app.web.purchase_orders.render_template", return_value="<html>PDF</html>"), \
             patch("app.services.mailer.Mailer.send", return_value=True) as mock_send:
            mock_html.return_value.write_pdf.return_value = b"%PDF-1.4"
            resp = supplier_retention_letter_email("sinv-1")
            return resp, mock_send


def test_retention_email_attaches_letter_pdf_and_xml(app):
    resp, mock_send = _post_email(app, dict(INVOICE), dict(CTX))

    assert resp.get_json()["success"] is True
    mock_send.assert_called_once()
    atts = mock_send.call_args.kwargs["attachments"]
    names = [a["filename"] for a in atts]

    assert "Carta_Retencion_B0100000001.pdf" in names
    assert "Factura_B0100000001.pdf" in names
    assert "eCF_E4100000001.xml" in names


def test_retention_email_without_emitted_comprobante_omits_xml(app):
    ctx = dict(CTX)
    ctx["xml_content"] = ""
    resp, mock_send = _post_email(app, dict(INVOICE, encf=""), ctx)

    assert resp.get_json()["success"] is True
    atts = mock_send.call_args.kwargs["attachments"]
    names = [a["filename"] for a in atts]

    assert "Carta_Retencion_B0100000001.pdf" in names
    assert not any(n.endswith(".xml") for n in names)


def test_resolve_supplier_email_prefers_invoice_field(app):
    from app.web.purchase_orders import _resolve_supplier_email

    with app.app_context():
        assert _resolve_supplier_email("u", {"email": "f@x.com"}, True, "c") == "f@x.com"


def test_resolve_supplier_email_by_supplier_id(app):
    from app.web.purchase_orders import _resolve_supplier_email

    with app.app_context():
        with patch("app.services.contact_service.ContactService.get_contact", return_value=None), \
             patch("app.web.purchase_orders.SupplierService.get_supplier", return_value={"email": "prov@x.com"}):
            assert _resolve_supplier_email("u", {"supplierId": "s1"}, True, "c") == "prov@x.com"


def test_resolve_supplier_email_by_rnc(app):
    from app.web.purchase_orders import _resolve_supplier_email

    with app.app_context():
        with patch("app.web.purchase_orders.SupplierService.get_supplier_by_rnc", return_value={"email": "rnc@x.com"}):
            assert _resolve_supplier_email("u", {"supplierRnc": "131-00000-1"}, True, "c") == "rnc@x.com"


def test_resolve_supplier_email_empty_when_not_found(app):
    from app.web.purchase_orders import _resolve_supplier_email

    with app.app_context():
        with patch("app.web.purchase_orders.SupplierService.get_supplier_by_rnc", return_value=None), \
             patch("app.services.contact_service.ContactService.get_contact_by_rnc", return_value=None):
            assert _resolve_supplier_email("u", {"supplierRnc": "131-00000-1"}, True, "c") == ""


def test_supplier_invoice_pdf_route_uses_helper(app):
    from app.web.purchase_orders import supplier_invoice_pdf

    with app.test_request_context("/purchase-orders/invoices/sinv-1/pdf?action=download"):
        session["user"] = {"ownerUID": "user-test"}
        session["selected_company_id"] = "comp-1"
        session["is_sandbox_mode"] = True

        with patch("app.web.purchase_orders.check_permission", return_value=True), \
             patch("app.web.purchase_orders.SupplierInvoiceService.get", return_value=dict(INVOICE)), \
             patch("app.web.purchase_orders.DatabaseService.get_company_profile", return_value={"companyName": "Empresa Test"}), \
             patch("app.web.purchase_orders._supplier_comprobante_context", return_value=dict(CTX)), \
             patch("app.web.purchase_orders.WEASYPRINT_AVAILABLE", True), \
             patch("app.web.purchase_orders.WeasyprintHTML") as mock_html, \
             patch("app.web.purchase_orders.render_template", return_value="<html></html>"):
            mock_html.return_value.write_pdf.return_value = b"%PDF-1.4"
            resp = supplier_invoice_pdf("sinv-1")

    assert resp.headers["Content-Type"] == "application/pdf"
    assert "Factura_B0100000001.pdf" in resp.headers["Content-Disposition"]


def test_supplier_invoice_xml_route_uses_helper(app):
    from app.web.purchase_orders import supplier_invoice_xml_download

    with app.test_request_context("/purchase-orders/invoices/sinv-1/xml"):
        session["user"] = {"ownerUID": "user-test"}
        session["selected_company_id"] = "comp-1"
        session["is_sandbox_mode"] = True

        with patch("app.web.purchase_orders.check_permission", return_value=True), \
             patch("app.web.purchase_orders.SupplierInvoiceService.get", return_value=dict(INVOICE)), \
             patch("app.web.purchase_orders.DatabaseService.get_company_profile", return_value={"companyName": "Empresa Test"}), \
             patch("app.web.purchase_orders._supplier_comprobante_context", return_value=dict(CTX)):
            resp = supplier_invoice_xml_download("sinv-1")

    assert resp.headers["Content-Type"] == "application/xml; charset=utf-8"
    assert "eCF_E4100000001.xml" in resp.headers["Content-Disposition"]
    assert b"<eCF>" in resp.get_data()


def test_retention_letter_uses_invoice_emission_date(app):
    from datetime import datetime

    from flask import render_template

    with app.test_request_context("/"):
        html = render_template(
            "invoices/retention_letter.html",
            invoice={
                "invoiceNumber": "FAC-1",
                "clientName": "Proveedor",
                "clientRNC": "131-00000-1",
                "total": 1180.0,
                "totalITBIS": 180.0,
                "date": "2026-03-09",
                "paymentDate": "2026-03-09",
            },
            company={"companyName": "Test SRL", "companyRNC": "132-00000-1"},
            now=datetime(2026, 10, 12),
            retained_isr=100.0,
            retained_itbis=54.0,
            retained_total=154.0,
            retention_percent=30,
            net_amount=1026.0,
            payment_method="Efectivo",
            representative_name="Admin",
            representative_id="001-0000000-9",
            auto_print=False,
        )

    assert "9 de marzo de 2026" in html
    assert "12 de octubre de 2026" not in html
