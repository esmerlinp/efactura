from app.services.bank_ledger_rebuild_service import BankLedgerRebuildService


def test_summarize_reconstructs_balance():
    result = BankLedgerRebuildService.summarize(
        {"id": "a", "initialBalance": 100, "currentBalance": 125},
        [{"amount": 50}, {"amount": -25}],
    )
    assert result["reconstructed_balance"] == 125
    assert result["difference"] == 0
