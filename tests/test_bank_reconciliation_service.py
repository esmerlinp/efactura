from app.services.bank_reconciliation_service import reconcile_account


def test_reconcile_account_includes_adjustment_movements():
    result = reconcile_account(
        {"initialBalance": 100000, "currentBalance": 102500},
        [{"amount": 1800}, {"amount": -300}, {"amount": 1000}],
    )
    assert result["calculated_balance"] == 102500
    assert result["difference"] == 0
