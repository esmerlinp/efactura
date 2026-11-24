from app.services.bank_ledger_rebuild_service import BankLedgerRebuildService


def test_persist_candidates_dry_run_does_not_write():
    result = BankLedgerRebuildService.persist_candidates(
        object(), "owner", "company", [{"accountId": "a", "amount": 10, "type": "income", "sourceType": "x", "sourceId": "1"}], apply=False
    )
    assert result == {"created": 0, "skipped": 1, "dry_run": True}
