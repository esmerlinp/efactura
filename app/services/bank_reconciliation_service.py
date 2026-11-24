"""Deterministic reconciliation helpers for bank account balances."""


def reconcile_account(account, transactions):
    initial = float(account.get("initialBalance", 0.0) or 0.0)
    amounts = [float(tx.get("amount", 0.0) or 0.0) for tx in transactions]
    calculated = initial + sum(amounts)
    stored = float(account.get("currentBalance", 0.0) or 0.0)
    return {
        "initial_balance": round(initial, 2),
        "inflows": round(sum(amount for amount in amounts if amount > 0), 2),
        "outflows": round(sum(abs(amount) for amount in amounts if amount < 0), 2),
        "calculated_balance": round(calculated, 2),
        "stored_balance": round(stored, 2),
        "difference": round(stored - calculated, 2),
        "transaction_count": len(transactions),
    }
