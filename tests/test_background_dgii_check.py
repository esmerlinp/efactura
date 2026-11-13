from unittest.mock import patch


def test_spawn_background_check_runs_poll_in_thread():
    from app.services.contingency_sync_service import ContingencySyncService

    company = {"companyRNC": "101000001"}

    with patch.object(
        ContingencySyncService, "poll_pending_invoice_until_terminal"
    ) as poll:
        poll.return_value = "accepted"
        thread = ContingencySyncService.spawn_background_check(
            "owner-1", "inv-1", company, sandbox=True, company_id="company-1"
        )
        thread.join(timeout=5)

    assert not thread.is_alive()
    poll.assert_called_once()
    kwargs = poll.call_args.kwargs
    assert kwargs["owner_uid"] == "owner-1"
    assert kwargs["invoice_id"] == "inv-1"
    assert kwargs["sandbox"] is True
    assert kwargs["company_id"] == "company-1"
    assert kwargs["max_attempts"] == 20
    assert kwargs["max_seconds"] == 600


def test_spawn_background_check_swallows_poll_errors():
    from app.services.contingency_sync_service import ContingencySyncService

    company = {"companyRNC": "101000001"}

    with patch.object(
        ContingencySyncService, "poll_pending_invoice_until_terminal",
        side_effect=RuntimeError("boom"),
    ) as poll:
        thread = ContingencySyncService.spawn_background_check(
            "owner-1", "inv-1", company, sandbox=True, company_id="company-1"
        )
        thread.join(timeout=5)

    assert not thread.is_alive()
    poll.assert_called_once()
