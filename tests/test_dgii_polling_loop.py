from unittest.mock import patch


def test_poll_loop_runs_until_acceptance(app):
    from app.services.contingency_sync_service import ContingencySyncService

    invoice = {"status": "Pendiente DGII", "trackId": "track", "emisionMode": "API"}
    responses = iter([
        {"success": True, "dgiiStatus": "PENDING"},
        {"success": True, "dgiiStatus": "ACCEPTED"},
    ])

    with app.app_context(), \
            patch("app.services.contingency_sync_service.DatabaseService.get_invoice", return_value=invoice), \
            patch("app.services.contingency_sync_service.DgiiDirectService.check_status", side_effect=lambda *a, **k: next(responses)), \
            patch.object(ContingencySyncService, "_apply_status_resolution", side_effect=["pending", "accepted"]):
        result = ContingencySyncService.poll_pending_invoice_until_terminal(
            "owner", "invoice", {}, max_attempts=3, max_seconds=20, sleep_fn=lambda _: None
        )

    assert result == "accepted"


def test_poll_loop_stops_on_error(app):
    from app.services.contingency_sync_service import ContingencySyncService

    invoice = {"status": "Pendiente DGII", "trackId": "track", "emisionMode": "API"}
    with app.app_context(), \
            patch("app.services.contingency_sync_service.DatabaseService.get_invoice", return_value=invoice), \
            patch("app.services.contingency_sync_service.DgiiDirectService.check_status", return_value={"success": False}), \
            patch.object(ContingencySyncService, "_apply_status_resolution", return_value="pending"):
        result = ContingencySyncService.poll_pending_invoice_until_terminal(
            "owner", "invoice", {}, max_attempts=3, max_seconds=20, sleep_fn=lambda _: None
        )

    assert result == "error"
