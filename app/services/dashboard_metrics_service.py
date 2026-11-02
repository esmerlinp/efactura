"""Cached deterministic metrics used by the main dashboard."""

from datetime import datetime

from app.services.cache_service import CacheService


def _parse_date(value):
    try:
        value = str(value or "")
        if "T" in value:
            return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _in_kpi_period(value, selected_date, kpi_period):
    date_value = _parse_date(value)
    if not date_value:
        return False
    if kpi_period == "month":
        return date_value.month == selected_date.month and date_value.year == selected_date.year
    if kpi_period == "prev_month":
        year = selected_date.year if selected_date.month > 1 else selected_date.year - 1
        month = selected_date.month - 1 or 12
        return date_value.month == month and date_value.year == year
    if kpi_period == "year":
        return date_value.year == selected_date.year
    return True


def build_dashboard_metrics(invoices, expenses, selected_date, kpi_period):
    """Build values that depend only on invoice and expense snapshots."""
    real_invoices = [
        invoice for invoice in invoices
        if not invoice.get("isQuotation")
        and invoice.get("status") not in ("Anulada", "Borrador")
    ]
    kpi_invoices = [
        invoice for invoice in real_invoices
        if _in_kpi_period(invoice.get("date"), selected_date, kpi_period)
    ]
    kpi_expenses = [
        expense for expense in expenses
        if _in_kpi_period(expense.get("date"), selected_date, kpi_period)
    ]

    total_invoiced = sum(float(invoice.get("total", 0)) for invoice in kpi_invoices)
    total_expenses = sum(float(expense.get("amount", 0)) for expense in kpi_expenses)
    total_itbis = sum(float(invoice.get("totalITBIS", 0)) for invoice in kpi_invoices)
    total_cxc = sum(
        float(invoice.get("netPayable", 0))
        for invoice in real_invoices
        if invoice.get("status") in ("Emitida", "Vencida")
    )
    cxp_expenses = [
        expense for expense in expenses
        if expense.get("paymentType") == "Crédito"
        and expense.get("cxpStatus") != "Pagado"
    ]
    total_cxp = sum(float(expense.get("cxpRemainingBalance", 0)) for expense in cxp_expenses)
    margin_net = ((total_invoiced - total_expenses) / total_invoiced * 100) if total_invoiced else 0.0

    return {
        "real_invoices": real_invoices,
        "total_invoiced": total_invoiced,
        "total_expenses": total_expenses,
        "total_cxc": total_cxc,
        "total_itbis": total_itbis,
        "total_cxp": total_cxp,
        "margin_net": margin_net,
        "kpi_invoice_count": len(kpi_invoices),
        "kpi_expense_count": len(kpi_expenses),
    }


def get_dashboard_metrics(company_id, sandbox, branch_id, project_id, scale,
                          selected_date, kpi_period, invoices, expenses):
    """Return cached dashboard metrics for the current sales data version."""
    cache = CacheService.get_cache()
    key = CacheService.domain_key(
        "sales", company_id, sandbox, branch_id, project_id, scale,
        selected_date.strftime("%Y-%m-%d"), kpi_period,
    )
    cached = CacheService.get_with_stats(key)
    if cached is not None:
        return cached

    result = build_dashboard_metrics(invoices, expenses, selected_date, kpi_period)
    CacheService.set_with_stats(key, result, timeout=60)
    return result
