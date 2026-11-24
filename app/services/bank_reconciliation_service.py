"""Deterministic reconciliation helpers for bank account balances."""


def reconcile_account(account, transactions):
    initial = float(account.get("initialBalance", 0.0) or 0.0)
    amounts = [float(tx.get("amount", 0.0) or 0.0) for tx in transactions]
    calculated = initial + sum(amounts)
    stored = float(account.get("currentBalance", 0.0) or 0.0)
    statement = account.get("statementBalance")
    statement_balance = float(statement) if statement is not None else None
    difference = (statement_balance - calculated) if statement_balance is not None else stored - calculated
    status = "conciliada" if abs(difference) <= 0.01 else "diferencias_detectadas"
    return {
        "initial_balance": round(initial, 2),
        "inflows": round(sum(amount for amount in amounts if amount > 0), 2),
        "outflows": round(sum(abs(amount) for amount in amounts if amount < 0), 2),
        "calculated_balance": round(calculated, 2),
        "stored_balance": round(stored, 2),
        "statement_balance": round(statement_balance, 2) if statement_balance is not None else None,
        "difference": round(difference, 2),
        "status": status,
        "reconciled_balance": float(account.get("reconciledBalance", 0.0) or 0.0),
        "transaction_count": len(transactions),
        "reconciled_count": sum(1 for tx in transactions if tx.get("reconciled") is True),
        "pending_count": sum(1 for tx in transactions if tx.get("reconciled") is not True),
    }
