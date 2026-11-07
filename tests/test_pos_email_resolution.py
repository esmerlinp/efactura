from unittest.mock import patch


def test_post_acceptance_uses_persisted_pos_email(app):
    from app.services.ecf_post_acceptance_service import EcfPostAcceptanceService

    invoice = {
        "id": "pos-invoice",
        "dgiiStatus": "ACCEPTED",
        "status": "Emitida",
        "emisionMode": "API",
        "encf": "E320000000001",
        "clientEmail": "client@example.com",
        "items": [],
        "total": 100.0,
        "netPayable": 100.0,
    }

    with app.app_context(), \
            patch("app.services.ecf_post_acceptance_service.DatabaseService.save_invoice"), \
            patch("app.services.accounting_service.AccountingService.auto_generate_invoice_entry", return_value={"id": "entry"}), \
            patch("app.web.invoices.send_invoice_email", return_value=(True, "sent")) as send_email:
        result = EcfPostAcceptanceService.process_accepted_invoice(
            "owner", "pos-invoice", invoice, company_id="company"
        )

    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["effects"]["email"] is True
    assert invoice["clientEmail"] == "client@example.com"
    send_email.assert_called_once()
    assert send_email.call_args.kwargs["recipient_email"] == "client@example.com"
