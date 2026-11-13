"""Pruebas de la pantalla de transacción manual de inventario (costo unitario editable)."""

from flask import render_template


def test_nueva_transaccion_renders_cost_field_and_item_cost_attrs(app):
    items = [
        {
            "id": "it-1", "name": "Cemento", "code": "CEM-01", "barcode": "",
            "type": "Bien", "price": 500.0, "costPrice": 450.0,
            "avgCost": 470.0, "lastPurchaseCost": 480.0, "trackLots": False,
        }
    ]
    with app.test_request_context("/inventory/transactions/new"):
        with app.app_context():
            html = render_template(
                "inventario/nueva_transaccion.html",
                active_page="inventory",
                items=items,
                warehouses=[{"id": "wh-1", "name": "Principal"}],
                selected_item_id="",
            )

    assert 'id="unit_cost"' in html
    assert 'name="unit_cost"' in html
    assert 'id="grp-unit-cost"' in html
    assert 'id="unit-cost-hint"' in html
    # El selector de producto debe exponer los costos para precargar el campo
    assert 'data-cost="450.0"' in html
    assert 'data-avgcost="470.0"' in html
    assert 'data-lastpurchase="480.0"' in html


def test_movimientos_renders_cost_column_and_reversal_button(app):
    transactions = [
        {
            "id": "tx-1", "itemId": "it-1", "itemName": "Cemento",
            "type": "ENTRADA", "quantity": 10.0, "unitCost": 450.0, "totalValue": 4500.0,
            "reason": "COMPRA", "referenceId": "", "referenceType": "MANUAL_ADJUSTMENT",
            "reversalTxId": "", "reversedBy": "",
            "originWarehouseId": "", "originWarehouseName": "",
            "destinationWarehouseId": "wh-1", "destinationWarehouseName": "Principal",
            "date": "2026-01-01T10:00:00", "performedBy": "admin@test.com",
        },
        {
            "id": "tx-2", "itemId": "it-1", "itemName": "Cemento",
            "type": "ENTRADA", "quantity": 5.0, "unitCost": 460.0, "totalValue": 2300.0,
            "reason": "COMPRA", "referenceId": "", "referenceType": "MANUAL_ADJUSTMENT",
            "reversalTxId": "tx-rev-2", "reversedBy": "admin@test.com",
            "originWarehouseId": "", "originWarehouseName": "",
            "destinationWarehouseId": "wh-1", "destinationWarehouseName": "Principal",
            "date": "2026-01-02T10:00:00", "performedBy": "admin@test.com",
        },
    ]
    with app.test_request_context("/inventory/transactions"):
        with app.app_context():
            html = render_template(
                "inventario/movimientos.html",
                active_page="inventory",
                transactions=transactions,
            )

    assert "Costo unit." in html
    assert "450.00" in html
    assert "Reversión" in html
    assert "/inventory/transactions/tx-1/reverse" in html
    assert "Revertido" in html  # tx-2 ya revertido

