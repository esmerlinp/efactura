from app.services.profitability_service import build_profitability


def test_profitability_uses_line_total_and_treats_zero_cost_as_full_margin():
    invoices = [{
        "status": "Emitida",
        "date": "2026-11-10",
        "items": [
            {"code": "A", "name": "Producto A", "quantity": 2, "total": 300},
            {"code": "B", "name": "Servicio B", "quantity": 1, "total": 100},
        ],
    }]
    catalog = [{"code": "A", "name": "Producto A", "costPrice": 50}]

    rows, total_revenue, total_cost, total_profit = build_profitability(
        invoices, catalog, year=2026, month=11
    )

    assert rows[0]["revenue"] == 300
    assert rows[0]["cost"] == 100
    assert rows[0]["profit"] == 200
    assert rows[1]["cost_known"] is True
    assert rows[1]["cost"] == 0
    assert rows[1]["profit"] == 100
    assert rows[1]["margin"] == 100
    assert total_revenue == 400
    assert total_cost == 100
    assert total_profit == 200


def test_profitability_prefers_historical_line_cost_over_catalog_cost():
    invoices = [{
        "status": "Emitida",
        "date": "2026-11-10",
        "items": [{"code": "A", "name": "Producto A", "quantity": 1, "total": 300, "originalCost": 125}],
    }]
    catalog = [{"code": "A", "costPrice": 50}]

    rows, _, total_cost, total_profit = build_profitability(invoices, catalog, year=2026, month=11)

    assert rows[0]["cost"] == 125
    assert total_cost == 125
    assert total_profit == 175
