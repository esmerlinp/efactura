"""Tests for invoice email notification (notify_invoice_email & send_invoice_email).

Validates that:
1. send_invoice_email accepts company_id and properly falls back when not provided.
2. company_id and rnc_emisor are defined and no NameError is raised.
3. notify_invoice_email route properly forwards company_id and returns success.
4. _get_client_email retrieves client email from client profile, invoice, or RNC.
5. notify_invoice_email falls back to client profile email when no email is posted in the body.
"""

from unittest.mock import MagicMock, patch
import pytest


def test_send_invoice_email_no_name_error(app):
    """Ensure send_invoice_email does not fail with NameError ('company_id' or 'rnc_emisor')."""
    from app.web.invoices import send_invoice_email

    invoice = {
        "id": "inv-123",
        "encf": "E3200000001",
        "ecfType": "Factura de Consumo (E32)",
        "date": "2026-10-12",
        "total": 1180.0,
        "currency": "DOP",
        "clientName": "Juan Pérez",
        "xmlContent": "<eCF><Encabezado></Encabezado></eCF>",
        "branchId": "branch-1",
    }
    company = {
        "id": "comp-456",
        "companyName": "Empresa Test SRL",
        "tradeName": "Empresa Test",
        "companyRNC": "131-88068-1",
        "colorMarca": "#1a365d",
    }
    branch = {"id": "branch-1", "name": "Sede Principal"}

    with app.app_context():
        with patch("app.web.invoices.DatabaseService") as mock_db, \
             patch("app.web.invoices.Mailer.send", return_value=True) as mock_mailer, \
             patch("app.web.invoices.render_template", return_value="<html>PDF</html>"):

            mock_db.get_company_profile.return_value = company
            mock_db.get_branches.return_value = [branch]

            app.config["SMTP_USER"] = "smtp@example.com"
            app.config["SMTP_PASSWORD"] = "password123"

            success, message = send_invoice_email(
                owner_uid="user-test",
                invoice=invoice,
                recipient_email="cliente@test.com",
                sandbox=True,
                company_id="comp-456",
            )

            assert success is True
            assert "Factura enviada exitosamente" in message
            mock_db.get_company_profile.assert_called_once_with("user-test", company_id="comp-456")
            mock_db.get_branches.assert_called_once_with("user-test", company_id="comp-456", sandbox=True)

            mock_mailer.assert_called_once()
            call_kwargs = mock_mailer.call_args.kwargs
            attachments = call_kwargs["attachments"]
            assert any(att["filename"] == "131880681E3200000001.xml" for att in attachments)


def test_send_invoice_email_fallback_company_id(app):
    """Ensure send_invoice_email falls back to invoice dict or profile id when company_id is None."""
    from app.web.invoices import send_invoice_email

    invoice = {
        "id": "inv-123",
        "companyId": "comp-fallback",
        "encf": "E3200000001",
        "xmlContent": "<eCF></eCF>",
        "total": 100.0,
    }
    company = {
        "id": "comp-fallback",
        "companyName": "Empresa Fallback",
        "companyRNC": "101000001",
    }

    with app.app_context():
        with patch("app.web.invoices.DatabaseService") as mock_db, \
             patch("app.web.invoices.Mailer.send", return_value=True), \
             patch("app.web.invoices.render_template", return_value="<html>PDF</html>"):

            mock_db.get_company_profile.return_value = company
            mock_db.get_branches.return_value = []

            app.config["SMTP_USER"] = "smtp@example.com"
            app.config["SMTP_PASSWORD"] = "password123"

            success, message = send_invoice_email(
                owner_uid="user-test",
                invoice=invoice,
                recipient_email="cliente@test.com",
            )

            assert success is True
            mock_db.get_company_profile.assert_called_once_with("user-test", company_id="comp-fallback")


def test_get_client_email_from_client_profile(app):
    """Ensure _get_client_email retrieves email from client record when clientId is present."""
    from app.web.invoices import _get_client_email

    invoice = {"id": "inv-1", "clientId": "cli-123"}
    client_doc = {"id": "cli-123", "name": "Cliente VIP", "email": "vip@cliente.com"}

    with app.app_context():
        with patch("app.web.invoices.DatabaseService.get_client", return_value=client_doc) as mock_gc:
            email = _get_client_email("owner-1", invoice, sandbox=True, company_id="comp-1")
            assert email == "vip@cliente.com"
            mock_gc.assert_called_once_with("owner-1", "cli-123", sandbox=True, company_id="comp-1")


def test_get_client_email_from_invoice_directly(app):
    """Ensure _get_client_email prioritizes email when already on invoice dict."""
    from app.web.invoices import _get_client_email

    invoice = {"id": "inv-2", "clientEmail": "directo@cliente.com", "clientId": "cli-456"}
    with app.app_context():
        with patch("app.web.invoices.DatabaseService.get_client") as mock_gc:
            email = _get_client_email("owner-1", invoice, sandbox=False, company_id="comp-1")
            assert email == "directo@cliente.com"
            mock_gc.assert_not_called()


def test_notify_invoice_email_route(client, app):
    """Test POST /invoices/<invoice_id>/notify-email succeeds and passes company_id."""
    user_dict = {
        "uid": "test_owner_uid",
        "ownerUID": "test_owner_uid",
        "role": "owner",
        "email": "admin@test.com",
        "name": "Admin",
        "status": "active",
        "default_company_id": "test_comp_1",
    }
    company_doc = {
        "id": "test_comp_1",
        "owner_uid": "test_owner_uid",
        "companyName": "Empresa Test",
        "status": "Activo",
        "configured": True,
        "production_enabled": True,
        "sandbox_enabled": True,
        "planId": "plan_test",
        "plan_id": "plan_test",
        "plan_version": 1,
    }
    invoice_data = {
        "id": "inv-999",
        "encf": "E3100000001",
        "xmlContent": "<eCF></eCF>",
        "total": 500.0,
    }

    with client.session_transaction() as sess:
        sess.clear()
        sess["user"] = dict(user_dict)
        sess["selected_company_id"] = "test_comp_1"
        sess["selected_owner_uid"] = "test_owner_uid"
        sess["is_sandbox_mode"] = False
        sess["company_plan_id"] = "plan_test"
        sess["company_plan_version"] = 1
        sess["company_modules"] = {"e_cf": {"enabled": True}}

    with patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_dict), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value={"status": "active", "role": "owner"}), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value={"company_id": "test_comp_1", "owner_uid": "test_owner_uid", "permissions": {"canInvoice": True}}), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={"modules": {"e_cf": {"enabled": True}}}), \
         patch("app.services.db_service.DatabaseService.get_invoice", return_value=invoice_data) as mock_get_inv, \
         patch("app.web.invoices.send_invoice_email", return_value=(True, "Factura enviada exitosamente por correo a test@client.com.")) as mock_send:

        res = client.post(
            "/invoices/inv-999/notify-email",
            json={"email": "test@client.com"},
        )

        assert res.status_code == 200
        json_data = res.get_json()
        assert json_data["success"] is True

        mock_get_inv.assert_called_once_with("test_owner_uid", "inv-999", company_id="test_comp_1", sandbox=False)
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs["company_id"] == "test_comp_1"
        assert kwargs["sandbox"] is False


def test_notify_invoice_email_fallback_to_client_email(client, app):
    """Test POST /invoices/<invoice_id>/notify-email with empty email falls back to client profile email."""
    user_dict = {
        "uid": "test_owner_uid",
        "ownerUID": "test_owner_uid",
        "role": "owner",
        "email": "admin@test.com",
        "name": "Admin",
        "status": "active",
        "default_company_id": "test_comp_1",
    }
    company_doc = {
        "id": "test_comp_1",
        "owner_uid": "test_owner_uid",
        "companyName": "Empresa Test",
        "status": "Activo",
        "configured": True,
        "production_enabled": True,
        "sandbox_enabled": True,
        "planId": "plan_test",
        "plan_id": "plan_test",
        "plan_version": 1,
    }
    invoice_data = {
        "id": "inv-999",
        "clientId": "cli-auto",
        "encf": "E3100000001",
        "xmlContent": "<eCF></eCF>",
        "total": 500.0,
    }
    client_doc = {
        "id": "cli-auto",
        "email": "perfil@cliente.com",
    }

    with client.session_transaction() as sess:
        sess.clear()
        sess["user"] = dict(user_dict)
        sess["selected_company_id"] = "test_comp_1"
        sess["selected_owner_uid"] = "test_owner_uid"
        sess["is_sandbox_mode"] = False
        sess["company_plan_id"] = "plan_test"
        sess["company_plan_version"] = 1
        sess["company_modules"] = {"e_cf": {"enabled": True}}

    with patch("app.services.db_service.DatabaseService.get_user_profile", return_value=user_dict), \
         patch("app.services.db_service.DatabaseService.get_company", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=company_doc), \
         patch("app.services.db_service.DatabaseService.get_membership", return_value={"status": "active", "role": "owner"}), \
         patch("app.services.db_service.DatabaseService.get_company_context", return_value={"company_id": "test_comp_1", "owner_uid": "test_owner_uid", "permissions": {"canInvoice": True}}), \
         patch("app.services.db_service.DatabaseService.get_branches", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_projects", return_value=[]), \
         patch("app.services.db_service.DatabaseService.get_plan", return_value={"modules": {"e_cf": {"enabled": True}}}), \
         patch("app.services.db_service.DatabaseService.get_invoice", return_value=invoice_data), \
         patch("app.services.db_service.DatabaseService.get_client", return_value=client_doc), \
         patch("app.web.invoices.send_invoice_email", return_value=(True, "Factura enviada exitosamente por correo a perfil@cliente.com.")) as mock_send:

        res = client.post(
            "/invoices/inv-999/notify-email",
            json={"email": ""},
        )

        assert res.status_code == 200
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        # Third positional arg is recipient_email
        assert args[2] == "perfil@cliente.com"


def test_mailer_send_via_graph_sets_content_type_and_reply_to(app):
    """Ensure Mailer._send_via_graph properly sets contentType on attachments and adds replyTo."""
    from app.services.mailer import Mailer

    app.config["MAIL_USE_GRAPH_API"] = True
    app.config["MAIL_TENANT_ID"] = "tenant-test"
    app.config["MAIL_CLIENT_ID"] = "client-test"
    app.config["MAIL_CLIENT_SECRET"] = "secret-test"
    app.config["MAIL_GRAPH_USER"] = "support@example.com"
    app.config["MAIL_FROM_INVOICE"] = "efactura@example.com"

    attachments = [
        {"filename": "factura.xml", "data": b"<xml></xml>", "mimetype": "application/xml"},
        {"filename": "factura.pdf", "data": b"%PDF-1.4", "mimetype": "application/pdf"},
    ]

    with patch.object(Mailer, "_get_graph_token", return_value="fake-token"), \
         patch("requests.post") as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_post.return_value = mock_resp

        result = Mailer.send(
            app=app,
            to_email="cliente@test.com",
            subject="Test Subject",
            html_body="<p>Test Body</p>",
            from_name="Empresa Test",
            category="invoice",
            attachments=attachments,
        )

        assert result is True
        mock_post.assert_called_once()
        sent_json = mock_post.call_args.kwargs["json"]
        message = sent_json["message"]

        # Check replyTo
        assert "replyTo" in message
        assert message["replyTo"][0]["emailAddress"]["address"] == "efactura@example.com"

        # Check attachment contentTypes
        atts = message["attachments"]
        assert len(atts) == 2
        assert atts[0]["contentType"] == "application/xml"
        assert atts[1]["contentType"] == "application/pdf"


# =========================================================================
# TESTS: Auto-notificación e-CF al ser Aceptado por DGII
# =========================================================================

def test_auto_notify_success_when_accepted_and_email_present(app):
    """Verifica que auto_notify envía email y marca emailNotified cuando dgiiStatus es ACCEPTED y el cliente tiene correo."""
    from app.web.invoices import auto_notify_invoice_if_accepted

    invoice = {
        "id": "inv-auto-1",
        "encf": "E3100000001",
        "dgiiStatus": "ACCEPTED",
        "status": "Emitida",
        "emisionMode": "API",
        "clientEmail": "cliente@valido.com",
        "clientName": "Cliente VIP SRL",
    }

    with app.app_context():
        with patch("app.web.invoices.send_invoice_email", return_value=(True, "OK")) as mock_send, \
             patch("app.web.invoices.DatabaseService.save_invoice") as mock_save:

            ok, msg = auto_notify_invoice_if_accepted(
                owner_uid="user-1",
                invoice=invoice,
                company_id="comp-1",
                sandbox=True,
            )

            assert ok is True
            assert "enviada automáticamente" in msg
            mock_send.assert_called_once()
            assert mock_send.call_args.kwargs["recipient_email"] == "cliente@valido.com"

            assert invoice.get("emailNotified") is True
            assert invoice.get("autoEmailNotified") is True
            assert invoice.get("emailNotifiedTo") == "cliente@valido.com"
            mock_save.assert_called_once_with("user-1", "inv-auto-1", invoice, company_id="comp-1", sandbox=True)


def test_auto_notify_skips_when_no_client_email(app):
    """Verifica que auto_notify omite el envío si el cliente no posee correo registrado."""
    from app.web.invoices import auto_notify_invoice_if_accepted

    invoice = {
        "id": "inv-auto-2",
        "encf": "E3200000002",
        "dgiiStatus": "ACCEPTED",
        "status": "Emitida",
        "emisionMode": "API",
        "clientId": "client-no-email",
    }

    with app.app_context():
        with patch("app.web.invoices._get_client_email", return_value=""), \
             patch("app.web.invoices.send_invoice_email") as mock_send:

            ok, msg = auto_notify_invoice_if_accepted(
                owner_uid="user-1",
                invoice=invoice,
                company_id="comp-1",
                sandbox=True,
            )

            assert ok is False
            assert "no posee correo electrónico registrado" in msg
            mock_send.assert_not_called()
            assert "emailNotified" not in invoice


def test_auto_notify_skips_when_pending_dgii(app):
    """Verifica que auto_notify omite si la factura está en estado PENDING o Pendiente DGII."""
    from app.web.invoices import auto_notify_invoice_if_accepted

    invoice_pending_status = {
        "id": "inv-auto-3",
        "encf": "E3100000003",
        "dgiiStatus": "PENDING",
        "status": "Pendiente DGII",
        "clientEmail": "cliente@valido.com",
    }

    with app.app_context():
        with patch("app.web.invoices.send_invoice_email") as mock_send:
            ok, msg = auto_notify_invoice_if_accepted("user-1", invoice_pending_status)
            assert ok is False
            assert "no aceptado por DGII" in msg
            mock_send.assert_not_called()


def test_auto_notify_skips_when_rejected_dgii(app):
    """Verifica que auto_notify omite si la factura fue rechazada por la DGII."""
    from app.web.invoices import auto_notify_invoice_if_accepted

    invoice_rejected = {
        "id": "inv-auto-4",
        "encf": "E3100000004",
        "dgiiStatus": "REJECTED",
        "status": "Rechazado DGII",
        "clientEmail": "cliente@valido.com",
    }

    with app.app_context():
        with patch("app.web.invoices.send_invoice_email") as mock_send:
            ok, msg = auto_notify_invoice_if_accepted("user-1", invoice_rejected)
            assert ok is False
            assert "no aceptado por DGII" in msg
            mock_send.assert_not_called()


def test_auto_notify_skips_when_contingency_fallback(app):
    """Verifica que auto_notify omite si la factura está en modo contingencia (FALLBACK)."""
    from app.web.invoices import auto_notify_invoice_if_accepted

    invoice_fallback = {
        "id": "inv-auto-5",
        "encf": "E3100000005",
        "dgiiStatus": "CONTINGENCY",
        "status": "Pendiente DGII",
        "emisionMode": "FALLBACK",
        "clientEmail": "cliente@valido.com",
    }

    with app.app_context():
        with patch("app.web.invoices.send_invoice_email") as mock_send:
            ok, msg = auto_notify_invoice_if_accepted("user-1", invoice_fallback)
            assert ok is False
            mock_send.assert_not_called()


def test_auto_notify_idempotent_skips_already_notified(app):
    """Verifica idempotencia: no reenvía correo si emailNotified ya es True."""
    from app.web.invoices import auto_notify_invoice_if_accepted

    invoice_notified = {
        "id": "inv-auto-6",
        "encf": "E3100000006",
        "dgiiStatus": "ACCEPTED",
        "status": "Emitida",
        "clientEmail": "cliente@valido.com",
        "emailNotified": True,
    }

    with app.app_context():
        with patch("app.web.invoices.send_invoice_email") as mock_send:
            ok, msg = auto_notify_invoice_if_accepted("user-1", invoice_notified)
            assert ok is False
            assert "ya fue notificado previamente" in msg
            mock_send.assert_not_called()


