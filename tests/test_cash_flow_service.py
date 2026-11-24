from datetime import date

from app.services.cash_flow_service import CashFlowService


def test_cash_flow_excludes_final_consumer_and_pending_expenses(monkeypatch):
    monkeypatch.setattr(CashFlowService, "get_current_liquidity", classmethod(lambda cls, **kwargs: 0.0))
    monkeypatch.setattr(CashFlowService, "_parse_date", staticmethod(lambda value: date.today()))

    projections = CashFlowService.project_cash_flow(
        "owner",
        months=1,
        invoices=[
            {"status": "Emitida", "clientId": "c1", "clientName": "Cliente", "remainingBalance": 100, "dueDate": str(date.today())},
            {"status": "Emitida", "clientId": "c2", "clientName": "Consumidor Final", "remainingBalance": 200, "dueDate": str(date.today())},
        ],
        expenses=[
            {"paymentType": "Crédito", "cxpStatus": "Pendiente", "approvalStatus": "Aprobado", "cxpRemainingBalance": 40, "dueDate": str(date.today())},
            {"paymentType": "Crédito", "cxpStatus": "Pendiente", "approvalStatus": "Pendiente", "cxpRemainingBalance": 80, "dueDate": str(date.today())},
        ],
    )

    assert projections[0].inflow == 100
    assert projections[0].outflow == 40


def test_cash_flow_moves_overdue_items_to_current_month(monkeypatch):
    monkeypatch.setattr(CashFlowService, "get_current_liquidity", classmethod(lambda cls, **kwargs: 0.0))
    overdue = "2000-01-01"
    projections = CashFlowService.project_cash_flow(
        "owner",
        months=1,
        invoices=[{"status": "Emitida", "clientId": "c1", "clientName": "Cliente", "remainingBalance": 75, "dueDate": overdue}],
        expenses=[],
    )

    assert projections[0].inflow == 75
