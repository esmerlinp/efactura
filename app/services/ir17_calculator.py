"""Cálculos puros y deterministas del IR-17."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY = Decimal("0.01")


def money(value):
    try:
        return Decimal(str(value or "0")).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def calculate_ir17(data):
    lines = []
    total_other = Decimal("0.00")
    for item in data.get("line_items", []):
        base = money(item.get("base"))
        rate = Decimal(str(item.get("rate", "0")))
        tax = (base * rate).quantize(MONEY, rounding=ROUND_HALF_UP)
        line = dict(item)
        line.update({"base": str(base), "rate": str(rate), "tax": str(tax)})
        lines.append(line)
        total_other += tax

    conventions = money(data.get("conventions_amount"))
    total_other_with_conventions = (total_other + conventions).quantize(MONEY)
    supplementary_base = money(data.get("supplementary_benefits"))
    raw_supplementary_rate = Decimal(str(data.get("supplementary_rate", "0.27") or "0"))
    supplementary_rate = raw_supplementary_rate / Decimal("100") if raw_supplementary_rate > 1 else raw_supplementary_rate
    supplementary_tax = (supplementary_base * supplementary_rate).quantize(MONEY, rounding=ROUND_HALF_UP)
    tax_due = total_other_with_conventions + supplementary_tax
    credits = sum(money(data.get(key)) for key in ("authorized_credits", "account_payments", "prior_balance"))
    net = tax_due - credits
    difference = max(net, Decimal("0.00"))
    favor = max(-net, Decimal("0.00"))
    surcharges = money(data.get("surcharges"))
    interest = money(data.get("indemnity_interest"))
    total_payable = difference + surcharges + interest
    return {
        "line_items": lines,
        "total_other_withholdings": str(total_other.quantize(MONEY)),
        "conventions_amount": str(conventions),
        "total_other_with_conventions": str(total_other_with_conventions),
        "supplementary_benefits": str(supplementary_base),
        "supplementary_tax": str(supplementary_tax),
        "tax_due": str(tax_due.quantize(MONEY)),
        "authorized_credits": str(money(data.get("authorized_credits"))),
        "account_payments": str(money(data.get("account_payments"))),
        "prior_balance": str(money(data.get("prior_balance"))),
        "difference_to_pay": str(difference.quantize(MONEY)),
        "new_balance_favor": str(favor.quantize(MONEY)),
        "surcharges": str(surcharges),
        "indemnity_interest": str(interest),
        "total_payable": str(total_payable.quantize(MONEY)),
    }
