from unittest.mock import patch


def test_pending_status_does_not_reduce_inventory_condition():
    source = open("app/services/db_service.py", encoding="utf-8").read()
    assert '"Pendiente DGII"' not in source[source.index("valid_sale_statuses ="):source.index("valid_sale_statuses =") + 180]


def test_post_acceptance_rejects_non_accepted(app):
    from app.services.ecf_post_acceptance_service import EcfPostAcceptanceService

    result = EcfPostAcceptanceService.process_accepted_invoice(
        "owner", "invoice", {"dgiiStatus": "PENDING"}, company_id="company"
    )

    assert result == {"success": False, "status": "not_accepted"}


def test_pending_query_is_rescheduled(app):
    from app.services.contingency_sync_service import ContingencySyncService

    invoice = {
        "id": "invoice",
        "status": "Pendiente DGII",
        "emisionMode": "API",
        "trackId": "track",
        "pendingSyncAttempts": 0,
    }
    pending = {"success": True, "dgiiStatus": "PENDING"}

    with app.app_context(), \
            patch.object(ContingencySyncService, "schedule_immediate_api_check") as schedule, \
            patch("app.services.contingency_sync_service.DatabaseService.get_invoice", return_value=invoice), \
            patch("app.services.contingency_sync_service.DgiiDirectService.check_status", return_value=pending):
        result = ContingencySyncService.check_pending_invoice_now(
            "owner", "invoice", {"companyRNC": "101000001"}, company_id="company"
        )

    assert result == "pending"
    schedule.assert_called_once()
    assert schedule.call_args.kwargs["delay_seconds"] == 3
