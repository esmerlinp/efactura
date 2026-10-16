"""
Regresión del flujo Orden de Compra ↔ Recepción de Mercancía ↔ Inventario.

Cubre las inconsistencias corregidas:
1. Validación de sobre-recepción real (antes era código muerto).
2. Ítem de catálogo obligatorio por partida recibida.
3. Almacén de destino obligatorio.
4. Transiciones de estado de OC permitidas/prohibidas.
5. Compensación (rollback) de transacciones al fallar el registro de inventario.
6. El endpoint JSON /receive queda deprecado (410).
"""

import pytest
from unittest.mock import patch

from app.services.goods_receipt_service import GoodsReceiptService
from app.services.purchase_order_service import PurchaseOrderService


def _po():
    return {
        "id": "po-1",
        "poNumber": "OC-2026-0001",
        "status": "aprobada",
        "items": [
            {"id": "line-1", "name": "Taladro", "quantity": 10, "receivedQuantity": 0,
             "unitPrice": 100, "unit": "Unidad"},
            {"id": "line-2", "name": "Martillo", "quantity": 5, "receivedQuantity": 2,
             "unitPrice": 50, "unit": "Unidad"},
        ],
    }


def _receipt(**over):
    data = {
        "receiptNumber": "RM-2026-0001",
        "poId": "po-1",
        "warehouseId": "wh-1",
        "warehouseName": "Principal",
        "items": [
            {"poItemId": "line-1", "itemId": "cat-1", "receivedQuantity": 4, "unitPrice": 100},
        ],
    }
    data.update(over)
    return data


# ── validate_receipt ─────────────────────────────────────────────────────

def test_validate_receipt_ok():
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=_po()):
        assert GoodsReceiptService.validate_receipt(
            "comp-1", _receipt(), sandbox=True, owner_uid="own-1"
        ) is True


def test_validate_receipt_requires_warehouse():
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=_po()):
        with pytest.raises(ValueError) as err:
            GoodsReceiptService.validate_receipt("comp-1", _receipt(warehouseId=""))
        assert "almacén" in str(err.value).lower()


def test_validate_receipt_requires_catalog_item():
    payload = _receipt(items=[{"poItemId": "line-1", "itemId": "", "receivedQuantity": 4}])
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=_po()):
        with pytest.raises(ValueError) as err:
            GoodsReceiptService.validate_receipt("comp-1", payload)
        assert "catálogo" in str(err.value)


def test_validate_receipt_blocks_over_receipt():
    # line-2 ya recibió 2 de 5; intentar 4 => 6 > 5
    payload = _receipt(items=[{"poItemId": "line-2", "itemId": "cat-2", "receivedQuantity": 4}])
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=_po()):
        with pytest.raises(ValueError) as err:
            GoodsReceiptService.validate_receipt("comp-1", payload)
        assert "excede" in str(err.value)


def test_validate_receipt_allows_exact_remaining():
    payload = _receipt(items=[{"poItemId": "line-2", "itemId": "cat-2", "receivedQuantity": 3}])
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=_po()):
        assert GoodsReceiptService.validate_receipt("comp-1", payload) is True


def test_validate_receipt_rejects_unknown_line():
    payload = _receipt(items=[{"poItemId": "ghost", "itemId": "cat-9", "receivedQuantity": 1}])
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=_po()):
        with pytest.raises(ValueError) as err:
            GoodsReceiptService.validate_receipt("comp-1", payload)
        assert "no pertenece" in str(err.value)


def test_validate_receipt_allows_service_without_warehouse_or_item_id():
    service_po = {
        "id": "po-serv",
        "poNumber": "OC-2026-0002",
        "status": "aprobada",
        "items": [
            {"id": "line-serv", "name": "Flete y Transporte", "quantity": 1, "receivedQuantity": 0,
             "unitPrice": 500, "unit": "Servicio", "isInventoriable": False}
        ],
    }
    payload = {
        "receiptNumber": "RC-2026-0002",
        "poId": "po-serv",
        "warehouseId": "",  # Sin almacén porque es servicio
        "items": [
            {"poItemId": "line-serv", "itemId": "", "receivedQuantity": 1, "isInventoriable": False}
        ],
    }
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=service_po):
        assert GoodsReceiptService.validate_receipt(
            "comp-1", payload, sandbox=True, owner_uid="own-1"
        ) is True


def test_validate_receipt_still_requires_warehouse_and_item_if_physical_item_present():
    mixed_po = {
        "id": "po-mixed",
        "poNumber": "OC-2026-0003",
        "status": "aprobada",
        "items": [
            {"id": "line-phys", "name": "Cemento", "quantity": 10, "receivedQuantity": 0,
             "unitPrice": 400, "isInventoriable": True},
            {"id": "line-serv", "name": "Descarga", "quantity": 1, "receivedQuantity": 0,
             "unitPrice": 100, "isInventoriable": False},
        ],
    }
    # Falta almacén con ítem físico presente
    payload_no_wh = {
        "receiptNumber": "RC-2026-0003",
        "poId": "po-mixed",
        "warehouseId": "",
        "items": [
            {"poItemId": "line-phys", "itemId": "cat-cemento", "receivedQuantity": 5, "isInventoriable": True},
            {"poItemId": "line-serv", "itemId": "", "receivedQuantity": 1, "isInventoriable": False},
        ],
    }
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=mixed_po):
        with pytest.raises(ValueError) as err:
            GoodsReceiptService.validate_receipt("comp-1", payload_no_wh)
        assert "almacén" in str(err.value).lower()

    # Falta ítem de catálogo para la partida física
    payload_no_cat = {
        "receiptNumber": "RC-2026-0003",
        "poId": "po-mixed",
        "warehouseId": "wh-1",
        "items": [
            {"poItemId": "line-phys", "itemId": "", "receivedQuantity": 5, "isInventoriable": True},
            {"poItemId": "line-serv", "itemId": "", "receivedQuantity": 1, "isInventoriable": False},
        ],
    }
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=mixed_po):
        with pytest.raises(ValueError) as err:
            GoodsReceiptService.validate_receipt("comp-1", payload_no_cat)
        assert "catálogo" in str(err.value).lower()


# ── Transiciones de estado ───────────────────────────────────────────────

def test_can_transition_rules():
    assert PurchaseOrderService.can_transition("borrador", "aprobada")
    assert PurchaseOrderService.can_transition("aprobada", "recibida_parcial")
    assert PurchaseOrderService.can_transition("recibida_parcial", "recibida_completa")
    assert not PurchaseOrderService.can_transition("recibida_completa", "cancelada")
    assert not PurchaseOrderService.can_transition("cancelada", "aprobada")
    assert not PurchaseOrderService.can_transition("recibida_completa", "recibida_parcial")


def test_update_status_rejects_invalid_transition():
    po = _po()
    po["status"] = "recibida_completa"
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po), \
         patch.object(PurchaseOrderService, "save_purchase_order") as save:
        with pytest.raises(ValueError):
            PurchaseOrderService.update_status(
                owner_uid="o", po_id="po-1", new_status="cancelada", company_id="c"
            )
        save.assert_not_called()


def test_update_status_allows_valid_transition():
    po = _po()
    po["status"] = "aprobada"
    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po), \
         patch.object(PurchaseOrderService, "save_purchase_order") as save:
        res = PurchaseOrderService.update_status(
            owner_uid="o", po_id="po-1", new_status="recibida_parcial",
            company_id="c", user="tester",
        )
        assert res["status"] == "recibida_parcial"
        save.assert_called_once()


# ── Rollback de transacciones ────────────────────────────────────────────

def test_reverse_registered_transactions_emits_salida():
    txs = [{
        "id": "tx1", "itemId": "cat-1", "quantity": 4,
        "destinationWarehouseId": "wh-1", "referenceId": "RM-2026-0001",
        "performedBy": "tester",
    }]
    with patch(
        "app.services.inventory_transaction_service.InventoryTransactionService.execute_transaction"
    ) as ex:
        ex.return_value = {"id": "rev1"}
        n = GoodsReceiptService.reverse_registered_transactions(
            "comp-1", txs, sandbox=True, owner_uid="o"
        )
    assert n == 1
    sent = ex.call_args.kwargs["tx_dict"]
    assert sent["type"] == "SALIDA"
    assert sent["originWarehouseId"] == "wh-1"
    assert sent["quantity"] == 4


# ── Endpoint deprecado (a nivel de vista) ────────────────────────────────

def test_receive_view_returns_410(app):
    """El handler del endpoint JSON /receive ya no mueve stock: responde 410."""
    from flask import session

    user = {
        "uid": "owner-1", "ownerUID": "owner-1", "role": "owner",
        "name": "Admin", "email": "a@b.com", "status": "active",
    }
    with patch("app.web.purchase_orders.PurchaseOrderService.save_purchase_order") as save:
        with app.test_request_context("/purchase-orders/po-1/receive", method="POST"):
            session["user"] = user
            view = app.view_functions["web_purchase_orders.receive_purchase_order"]
            body, status = view("po-1")
    assert status == 410
    save.assert_not_called()


# ── Registro de inventario (moneda base, servicios y proyectos) ───────────

def test_register_receipt_inventory_skips_services_and_converts_fx():
    po = {
        "id": "po-cur",
        "poNumber": "OC-2026-0004",
        "status": "aprobada",
        "currency": "USD",
        "exchangeRate": 60.0,
        "projectId": "proj-101",
        "branchId": "br-principal",
        "items": [
            {
                "id": "line-phys",
                "name": "Servidor Dell",
                "quantity": 2,
                "receivedQuantity": 0,
                "unitPrice": 100.0,
                "discount": 10.0,  # 10% de descuento
                "isInventoriable": True,
            },
            {
                "id": "line-serv",
                "name": "Configuración en sitio",
                "quantity": 1,
                "receivedQuantity": 0,
                "unitPrice": 80.0,
                "discount": 0.0,
                "isInventoriable": False,
            },
        ],
    }
    receipt = {
        "id": "rc-cur-1",
        "receiptNumber": "RC-2026-0004",
        "poId": "po-cur",
        "warehouseId": "wh-central",
        "warehouseName": "Almacén Central",
        "currency": "USD",
        "exchangeRate": 60.0,
        "projectId": "proj-101",
        "branchId": "br-principal",
        "items": [
            {
                "poItemId": "line-phys",
                "itemId": "item-server",
                "itemName": "Servidor Dell",
                "receivedQuantity": 2,
                "unitPrice": 100.0,
                "discount": 10.0,
                "isInventoriable": True,
            },
            {
                "poItemId": "line-serv",
                "itemId": "",
                "itemName": "Configuración en sitio",
                "receivedQuantity": 1,
                "unitPrice": 80.0,
                "discount": 0.0,
                "isInventoriable": False,
            },
        ],
    }

    with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po), \
         patch("app.services.inventory_transaction_service.InventoryTransactionService.execute_transaction") as mock_exec, \
         patch("app.services.inventory_costing_service.InventoryCostingService.recalculate_item_avg_cost") as mock_cost, \
         patch("app.services.inventory_accounting_service.InventoryAccountingService.post_inventory_transaction"):

        mock_exec.return_value = {"id": "tx-1", "itemId": "item-server"}

        registered = GoodsReceiptService.register_receipt_inventory(
            "comp-1", receipt, sandbox=True, owner_uid="own-1"
        )

        # 1. Solo debe registrar movimiento físico para el servidor (el servicio se omite del almacén)
        assert len(registered) == 1
        assert mock_exec.call_count == 1

        tx_sent = mock_exec.call_args.kwargs["tx_dict"]
        assert tx_sent["itemId"] == "item-server"
        assert tx_sent["quantity"] == 2
        assert tx_sent["destinationWarehouseId"] == "wh-central"
        assert tx_sent["projectId"] == "proj-101"
        assert tx_sent["branchId"] == "br-principal"

        # 2. Costo unitario neto en DOP: 100 * (1 - 0.10) * 60 = 5400.0
        assert tx_sent["unitCost"] == 5400.0

        # 3. Recálculo de costo promedio invocado para el ítem de inventario
        mock_cost.assert_called_once_with(
            "comp-1", "item-server", "wh-central", sandbox=True, owner_uid="own-1"
        )

