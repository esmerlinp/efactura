from unittest.mock import patch


def _pending_invoice():
    return {
        "id": "inv-1",
        "status": "Pendiente DGII",
        "emisionMode": "API",
        "trackId": "track-1",
        "encf": "E310000000001",
        "dgiiStatus": "PENDING",
        "total": 1180.0,
        "totalPaid": 0.0,
        "items": [],
    }


def test_immediate_check_accepts_and_notifies(app):
    from app.services.contingency_sync_service import ContingencySyncService

    invoice = _pending_invoice()
    accepted = {"success": True, "dgiiStatus": "ACCEPTED", "trackId": "track-1"}

    with app.app_context(), \
            patch("app.services.contingency_sync_service.DatabaseService.get_invoice", return_value=invoice), \
            patch("app.services.contingency_sync_service.DatabaseService.save_invoice"), \
            patch("app.services.contingency_sync_service.DgiiDirectService.check_status", return_value=accepted), \
            patch("app.services.contingency_sync_service.ContingencySyncService._record_sequence_status"), \
            patch("app.web.invoices.auto_notify_invoice_if_accepted") as notify:
        outcome = ContingencySyncService.check_pending_invoice_now(
            "owner-1", "inv-1", {"companyRNC": "101000001"}, company_id="company-1"
        )

    assert outcome == "accepted"
    assert invoice["status"] == "Emitida"
    assert invoice["dgiiStatus"] == "ACCEPTED"
    notify.assert_called_once()


def test_immediate_check_keeps_pending(app):
    from app.services.contingency_sync_service import ContingencySyncService

    invoice = _pending_invoice()
    pending = {"success": True, "dgiiStatus": "PENDING", "trackId": "track-1"}

    with app.app_context(), \
            patch("app.services.contingency_sync_service.DatabaseService.get_invoice", return_value=invoice), \
            patch("app.services.contingency_sync_service.DgiiDirectService.check_status", return_value=pending):
        outcome = ContingencySyncService.check_pending_invoice_now(
            "owner-1", "inv-1", {"companyRNC": "101000001"}
        )

    assert outcome == "pending"
    assert invoice["status"] == "Pendiente DGII"


def test_immediate_check_skips_fallback(app):
    from app.services.contingency_sync_service import ContingencySyncService

    invoice = _pending_invoice()
    invoice["emisionMode"] = "FALLBACK"

    with app.app_context(), \
            patch("app.services.contingency_sync_service.DatabaseService.get_invoice", return_value=invoice), \
            patch("app.services.contingency_sync_service.DgiiDirectService.check_status") as check:
        outcome = ContingencySyncService.check_pending_invoice_now(
            "owner-1", "inv-1", {"companyRNC": "101000001"}
        )

    assert outcome == "skipped"
    check.assert_not_called()
