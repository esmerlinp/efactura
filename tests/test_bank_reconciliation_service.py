from app.services.bank_reconciliation_service import reconcile_account


def test_reconcile_account_uses_statement_balance_when_available():
    result = reconcile_account(
        {"initialBalance": 100, "currentBalance": 125, "statementBalance": 130},
        [{"amount": 25}],
    )
    assert result["calculated_balance"] == 125
    assert result["statement_balance"] == 130
    assert result["difference"] == 5
    assert result["status"] == "diferencias_detectadas"
