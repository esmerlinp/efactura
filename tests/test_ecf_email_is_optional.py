from unittest.mock import patch


def _accepted_invoice():
    return {
        "id": "inv-email",
        "dgiiStatus": "ACCEPTED",
        "status": "Emitida",
        "emisionMode": "API",
        "encf": "E320000000001",
        "items": [],
        "total": 100.0,
        "netPayable": 100.0,
        "totalPaid": 0.0,
    }


def test_missing_email_does_not_block_completion(app):
    from app.services.ecf_post_acceptance_service import EcfPostAcceptanceService

    invoice = _accepted_invoice()
    with app.app_context(), \
            patch("app.services.ecf_post_acceptance_service.DatabaseService.save_invoice"), \
            patch("app.web.invoices._get_client_email", return_value="") as get_email, \
            patch("app.web.invoices.send_invoice_email") as send_email, \
            patch("app.services.accounting_service.AccountingService.auto_generate_invoice_entry", return_value={"id": "entry"}):
        result = EcfPostAcceptanceService.process_accepted_invoice(
            "owner", "inv-email", invoice, company_id="company"
        )

    assert result["success"] is True
    assert result["status"] == "completed"
    assert invoice["dgiiStatus"] == "ACCEPTED"
    get_email.assert_called_once()
    send_email.assert_not_called()


def test_email_failure_does_not_block_completion(app):
    from app.services.ecf_post_acceptance_service import EcfPostAcceptanceService

    invoice = _accepted_invoice()
    invoice["clientEmail"] = "client@example.com"
    with app.app_context(), \
            patch("app.services.ecf_post_acceptance_service.DatabaseService.save_invoice"), \
            patch("app.web.invoices.send_invoice_email", side_effect=RuntimeError("SMTP unavailable")), \
            patch("app.services.accounting_service.AccountingService.auto_generate_invoice_entry", return_value={"id": "entry"}):
        result = EcfPostAcceptanceService.process_accepted_invoice(
            "owner", "inv-email", invoice, company_id="company"
        )

    assert result["success"] is True
    assert result["status"] == "completed"
    assert invoice["dgiiStatus"] == "ACCEPTED"
