from app.services import profitability_service


def test_profitability_receives_company_scoped_data():
    invoices = [{
        "status": "Emitida",
        "date": "2026-11-01",
        "items": [{"code": "A", "name": "Empresa actual", "quantity": 1, "total": 100}],
    }]
    catalog = [{"code": "A", "costPrice": 40}]

    rows, total_revenue, total_cost, total_profit = profitability_service.build_profitability(
        invoices, catalog, year=2026, month=11
    )

    assert [row["name"] for row in rows] == ["Empresa actual"]
    assert (total_revenue, total_cost, total_profit) == (100, 40, 60)
