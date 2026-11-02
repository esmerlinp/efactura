from datetime import datetime

from app.services.dashboard_metrics_service import build_dashboard_metrics


def test_dashboard_metrics_exclude_drafts_and_filter_period():
    invoices = [
        {"status": "Emitida", "date": "2026-11-02", "total": 100, "netPayable": 100, "totalITBIS": 18},
        {"status": "Borrador", "date": "2026-11-02", "total": 999},
        {"status": "Emitida", "date": "2026-10-02", "total": 50, "netPayable": 50},
    ]
    expenses = [
        {"date": "2026-11-02", "amount": 25, "paymentType": "Contado"},
        {"date": "2026-10-02", "amount": 90, "paymentType": "Contado"},
    ]

    result = build_dashboard_metrics(
        invoices, expenses, datetime(2026, 11, 2), "month"
    )

    assert result["total_invoiced"] == 100
    assert result["total_expenses"] == 25
    assert result["total_itbis"] == 18
    assert len(result["real_invoices"]) == 2


def test_dashboard_metrics_cxc_and_cxp_are_lifetime_values():
    invoices = [
        {"status": "Emitida", "date": "2026-01-01", "total": 100, "netPayable": 40},
        {"status": "Pagado", "date": "2026-01-01", "total": 80, "netPayable": 80},
    ]
    expenses = [
        {"date": "2026-01-01", "amount": 50, "paymentType": "Crédito", "cxpStatus": "Pendiente", "cxpRemainingBalance": 30},
    ]

    result = build_dashboard_metrics(
        invoices, expenses, datetime(2026, 11, 2), "month"
    )

    assert result["total_cxc"] == 40
    assert result["total_cxp"] == 30
