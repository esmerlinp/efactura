"""Informative tax estimates used by the dashboard."""


def build_tax_estimate(invoices, expenses, year, month):
    period = f"{year:04d}-{month:02d}"
    valid_invoices = [
        inv for inv in invoices
        if str(inv.get("date") or inv.get("createdAt") or "")[:7] == period
        and inv.get("status") not in ("Anulada", "Borrador", "Consolidada")
    ]
    valid_expenses = [
        exp for exp in expenses
        if str(exp.get("date") or exp.get("createdAt") or "")[:7] == period
        and exp.get("approvalStatus") not in ("Pendiente", "Rechazado")
    ]
    sales_net = sum(float(inv.get("subtotal", 0) or 0) for inv in valid_invoices)
    expenses_net = sum(
        float(exp.get("amount", 0) or 0) - float(exp.get("itbisAmount", 0) or 0)
        for exp in valid_expenses
    )
    itbis_sales = sum(float(inv.get("totalITBIS", 0) or 0) for inv in valid_invoices)
    itbis_expenses = sum(
        float(exp.get("itbisAmount", 0) or 0)
        for exp in valid_expenses if exp.get("isITBISDeductible", True)
    )
    base = max(0.0, sales_net - expenses_net)
    return {
        "sales_net": sales_net,
        "expenses_net": expenses_net,
        "itbis_sales": itbis_sales,
        "itbis_expenses": itbis_expenses,
        "itbis_to_pay": itbis_sales - itbis_expenses,
        "isr_base": base,
        "isr_estimated": base * 0.27,
        "invoices": valid_invoices,
        "expenses": valid_expenses,
    }
