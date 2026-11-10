from unittest.mock import patch

import pytest

from app import create_app
from app.services.dgii import DGIIService
from app.services.db_service import CashShiftLockError
from app.web.pos import _pos_apply_available_stock, _pos_build_items, _pos_normalize_payments
from app.services.dgii_direct import DgiiDirectService


CATALOG = [
    {
        "id": "prod-1", "code": "P-1", "name": "Producto gravado",
        "price": 100.0, "itbisRate": 0.18, "isActive": True,
        "type": "Bien", "unit": "Unidad",
    },
    {
        "id": "prod-2", "code": "P-2", "name": "Producto exento",
        "price": 50.0, "itbisRate": 0.0, "isActive": True,
        "type": "Bien", "unit": "Unidad",
    },
]


@pytest.fixture()
def app():
    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _session(app):
    from flask import session
    session["user"] = {
        "ownerUID": "owner-1", "uid": "user-1",
        "email": "test@vyk.com", "role": "owner",
    }
    session["selected_company_id"] = "comp-1"
    session["is_sandbox_mode"] = True


def test_available_stock_uses_active_warehouse_and_exempts_services():
    items = [
        {"id": "bien", "type": "Bien", "totalStock": 99.0},
        {"id": "servicio", "type": "Servicio", "totalStock": 0.0},
        {"id": "sin-registro", "type": "Bien", "totalStock": 7.0},
        {"id": "demo", "type": "Bien", "totalStock": 3.0, "isDemo": True},
    ]
    stock = [
        {"itemId": "bien", "warehouseId": "wh-1", "quantity": 0.0},
        {"itemId": "sin-registro", "warehouseId": "otro-wh", "quantity": 5.0},
    ]
    result = _pos_apply_available_stock(items, stock, "wh-1")
    by_id = {item["id"]: item["availableStock"] for item in result}
    assert by_id["bien"] == pytest.approx(0.0)
    assert by_id["servicio"] == pytest.approx(0.0)
    assert by_id["sin-registro"] == pytest.approx(0.0)
    assert by_id["demo"] == pytest.approx(3.0)


def test_available_stock_falls_back_to_total_without_inventory_records():
    items = [{"id": "bien", "type": "Bien", "totalStock": 7.0}]
    assert _pos_apply_available_stock(items, [], "wh-1")[0]["availableStock"] == pytest.approx(7.0)
    assert _pos_apply_available_stock(items, [], "")[0]["availableStock"] == pytest.approx(7.0)


def test_build_items_uses_catalog_prices_and_discounts():
    payload = [{"id": "prod-1", "price": 1.0, "quantity": 2, "discountRate": 0.10}]
    items = _pos_build_items(payload, CATALOG, sandbox=True)
    assert items[0]["price"] == 100.0
    calcs = DGIIService.calculate_invoice_totals(items, discount_rate=0.05)
    assert calcs["total_discount"] == pytest.approx(29.0)
    assert calcs["total"] == pytest.approx(201.78)


def test_normalize_payments_supports_mixed_and_rejects_mismatch():
    info = _pos_normalize_payments({
        "payments": [
            {"method": "Efectivo", "amount": 60.0},
            {"method": "Tarjeta", "amount": 58.0, "reference": "AUTH-1"},
        ]
    }, 118.0, is_consumer_final=True)
    assert info["primary_method"] == "Efectivo"
    assert info["credit_amount"] == 0.0
    assert len(info["payments"]) == 2

    with pytest.raises(ValueError):
        _pos_normalize_payments({"payments": [{"method": "Efectivo", "amount": 100.0}]}, 118.0, True)


def test_normalize_credit_requires_registered_client_and_creates_no_cash():
    info = _pos_normalize_payments({"paymentMethod": "Crédito"}, 118.0, is_consumer_final=False)
    assert info["credit_amount"] == 118.0
    assert info["paid_amount"] == 0.0
    assert info["payment_type"] == "02 - Crédito"

    with pytest.raises(ValueError):
        _pos_normalize_payments({"paymentMethod": "Crédito"}, 118.0, is_consumer_final=True)


def test_normalize_mixed_credit_payment_splits_paid_and_credit():
    info = _pos_normalize_payments({
        "payments": [
            {"method": "Efectivo", "amount": 50.0},
            {"method": "Crédito", "amount": 68.0},
        ]
    }, 118.0, is_consumer_final=False)
    assert info["credit_amount"] == pytest.approx(68.0)
    assert info["paid_amount"] == pytest.approx(50.0)
    assert info["payment_type"] == "02 - Crédito"
    assert info["primary_method"] == "Crédito"


def test_quote_endpoint_matches_backend_totals(app):
    with patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value={"id": "shift-123", "status": "OPEN"}), \
         patch("app.web.pos.check_permission", return_value=True):
        with app.test_request_context("/pos/cart/quote", method="POST", json={
            "items": [
                {"id": "prod-1", "price": 1.0, "quantity": 1},
                {"id": "prod-2", "quantity": 2},
            ],
            "discountRate": 0.10,
        }):
            _session(app)
            from flask import session
            session["user"]["uid"] = "user-1"
            resp = app.view_functions["web_pos.pos_cart_quote"]()
            data = resp.get_json()
            expected = DGIIService.calculate_invoice_totals(
                _pos_build_items(
                    [{"id": "prod-1", "quantity": 1}, {"id": "prod-2", "quantity": 2}],
                    CATALOG, sandbox=True,
                ),
                discount_rate=0.10,
            )
            assert data["success"] is True
            assert data["total"] == expected["total"]
            assert data["totalITBIS"] == expected["total_itbis"]


def test_pos_client_lookup_uses_local_client_before_dgii(app):
    local = {"id": "cli-1", "name": "Local SRL", "rnc": "131880681"}
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_client_by_rnc", return_value=local) as local_lookup, \
         patch("app.web.pos.DGIIService.validate_and_fetch_rnc") as dgii_lookup:
        with app.test_request_context("/pos/client/lookup", method="POST", json={"rnc": "131-880681"}):
            _session(app)
            resp = app.view_functions["web_pos.pos_client_lookup"]()
        data = (resp[0] if isinstance(resp, tuple) else resp).get_json()
        assert data["success"] is True
        assert data["source"] == "local"
        assert data["client"] == local
        local_lookup.assert_called_once()
        dgii_lookup.assert_not_called()


def test_pos_client_lookup_returns_dgii_result_without_auto_registering(app):
    dgii = {"razon_social": "DGII Comercial SRL", "email": "ventas@example.com"}
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_client_by_rnc", return_value=None), \
         patch("app.web.pos.DGIIService.validate_and_fetch_rnc", return_value=dgii), \
         patch("app.web.pos.DatabaseService.save_client") as save_client:
        with app.test_request_context("/pos/client/lookup", method="POST", json={"rnc": "131880681"}):
            _session(app)
            resp = app.view_functions["web_pos.pos_client_lookup"]()
        data = (resp[0] if isinstance(resp, tuple) else resp).get_json()
        assert data["success"] is True
        assert data["source"] == "dgii"
        assert data["requiresRegistration"] is True
        assert data["client"]["name"] == "DGII Comercial SRL"
        assert data["client"]["isDgiiLookup"] is True
        save_client.assert_not_called()


def test_sale_persists_mixed_payments_and_one_cash_tx_per_non_credit_payment(app):
    captured_invoice = {}
    cash_txs = []
    idempotency_store = {}

    def fake_save(owner_uid, invoice_id, inv_dict, **kwargs):
        captured_invoice.clear()
        captured_invoice.update(inv_dict)

    def fake_sale_txs(owner_uid, register_id, shift_id, txs, **kwargs):
        cash_txs.extend(dict(t) for t in txs)
        return True

    def fake_get_idem(owner_uid, key, **kwargs):
        return idempotency_store.get(key)

    def fake_reserve_idem(owner_uid, key, **kwargs):
        rec = idempotency_store.get(key)
        if rec and rec.get("status") == "COMPLETED":
            return {"status": "COMPLETED", "record": rec}
        idempotency_store[key] = {"status": "PENDING"}
        return {"status": "RESERVED", "record": {"status": "PENDING"}}

    def fake_complete_idem(owner_uid, key, payload, **kwargs):
        idempotency_store[key] = {
            "status": "COMPLETED",
            "response": payload.get("response"),
            "statusCode": payload.get("statusCode", 200),
            "invoiceId": payload.get("invoiceId"),
        }
        return True

    mock_shift = {"id": "shift-123", "registerId": "reg-1", "status": "OPEN"}
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", side_effect=fake_get_idem), \
         patch("app.web.pos.DatabaseService.reserve_idempotency_key", side_effect=fake_reserve_idem), \
         patch("app.web.pos.DatabaseService.complete_idempotency_key", side_effect=fake_complete_idem), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "warehouseId": "wh-1"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": True, "consolidationThreshold": 999999}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.get_client", return_value={"id": "cli-1", "name": "Cliente", "rnc": "131880681"}), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=fake_save), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions", side_effect=fake_sale_txs), \
         patch("app.services.audit_service.AuditService.log_from_request"):

        payload = {
            "clientId": "cli-1",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [
                {"method": "Efectivo", "amount": 70.0},
                {"method": "Tarjeta", "amount": 48.0, "reference": "AUTH-9"},
            ],
        }
        headers = {"Idempotency-Key": "sale-1"}

        with app.test_request_context("/pos/invoice/new", method="POST", json=payload, headers=headers):
            _session(app)
            resp = app.view_functions["web_pos.create_pos_sale"]()
            data = resp.get_json()

        assert data["success"] is True
        assert captured_invoice["total"] == pytest.approx(118.0)
        assert captured_invoice["paymentMethod"] == "Efectivo"
        assert captured_invoice["totalPaid"] == pytest.approx(118.0)
        assert captured_invoice["remainingBalance"] == pytest.approx(0.0)
        assert len(captured_invoice["payments"]) == 2
        assert len(cash_txs) == 2
        assert {tx["paymentMethod"] for tx in cash_txs} == {"Efectivo", "Tarjeta"}
        assert {tx["id"] for tx in cash_txs} == {
            f"{data['invoiceId']}-pay-1",
            f"{data['invoiceId']}-pay-2",
        }

        # Reintento idempotente: no duplica factura ni movimientos de caja.
        with app.test_request_context("/pos/invoice/new", method="POST", json=payload, headers=headers):
            _session(app)
            resp2 = app.view_functions["web_pos.create_pos_sale"]()
            resp2_json = resp2[0].get_json() if isinstance(resp2, tuple) else resp2.get_json()
            assert resp2_json["invoiceId"] == data["invoiceId"]
        assert len(cash_txs) == 2


def test_ephemeral_dgii_client_can_pay_without_registration(app):
    captured_invoice = {}
    mock_shift = {"id": "shift-123", "registerId": "reg-1", "status": "OPEN"}
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "warehouseId": "wh-1"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=lambda o, i, d, **k: captured_invoice.update(d)), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions"), \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", return_value=None), \
         patch("app.web.pos._pos_register_credit_client") as register_client, \
         patch("app.services.audit_service.AuditService.log_from_request"):

        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "dgii-lookup",
            "clientRnc": "131880681",
            "clientName": "VYKCORE AUTOMATIONS SRL",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [{"method": "Efectivo", "amount": 118.0}],
        }):
            _session(app)
            resp = app.view_functions["web_pos.create_pos_sale"]()
            data = resp.get_json()

        assert data["success"] is True
        assert data["clientRegistered"] is False
        assert captured_invoice["clientId"] == ""
        assert captured_invoice["clientRNC"] == "131880681"
        assert captured_invoice["clientName"] == "VYKCORE AUTOMATIONS SRL"
        register_client.assert_not_called()


def test_ephemeral_dgii_client_is_registered_for_credit_sale(app):
    captured_invoice = {}
    mock_shift = {"id": "shift-123", "registerId": "reg-1", "status": "OPEN"}
    registered_client = {
        "id": "cli-registered", "razonSocial": "VYKCORE AUTOMATIONS SRL",
        "rnc": "131880681", "email": "",
    }
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "warehouseId": "wh-1"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=lambda o, i, d, **k: captured_invoice.update(d)), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions") as register_cash, \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", return_value=None), \
         patch("app.web.pos._pos_register_credit_client", return_value=registered_client) as register_client, \
         patch("app.services.audit_service.AuditService.log_from_request"):

        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "dgii-lookup",
            "clientRnc": "131880681",
            "clientName": "VYKCORE AUTOMATIONS SRL",
            "ecfType": "Factura de Crédito Fiscal (E31)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [{"method": "Crédito", "amount": 118.0}],
        }):
            _session(app)
            resp = app.view_functions["web_pos.create_pos_sale"]()
            data = resp.get_json()

        assert data["success"] is True
        assert data["clientRegistered"] is True
        assert captured_invoice["clientId"] == "cli-registered"
        assert captured_invoice["remainingBalance"] == pytest.approx(118.0)
        assert captured_invoice["paymentType"] == "02 - Crédito"
        register_client.assert_called_once()
        assert register_client.call_args.args[3] == "131880681"
        register_cash.assert_not_called()


def test_ephemeral_dgii_client_mixed_cash_and_credit_registers_client(app):
    captured_invoice = {}
    cash_txs = []
    registered_client = {
        "id": "cli-registered", "razonSocial": "VYKCORE AUTOMATIONS SRL",
        "rnc": "131880681", "email": "",
    }
    mock_shift = {"id": "shift-123", "registerId": "reg-1", "status": "OPEN"}
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "warehouseId": "wh-1"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=lambda o, i, d, **k: captured_invoice.update(d)), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions", side_effect=lambda o, r, s, txs, **k: cash_txs.extend(txs)), \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", return_value=None), \
         patch("app.web.pos._pos_register_credit_client", return_value=registered_client) as register_client, \
         patch("app.services.audit_service.AuditService.log_from_request"):

        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "dgii-lookup",
            "clientRnc": "131880681",
            "clientName": "VYKCORE AUTOMATIONS SRL",
            "ecfType": "Factura de Crédito Fiscal (E31)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [
                {"method": "Efectivo", "amount": 50.0},
                {"method": "Crédito", "amount": 68.0},
            ],
        }):
            _session(app)
            resp = app.view_functions["web_pos.create_pos_sale"]()
            data = resp.get_json()

        assert data["success"] is True
        assert data["clientRegistered"] is True
        assert captured_invoice["clientId"] == "cli-registered"
        assert captured_invoice["status"] == "Parcialmente Cobrada"
        assert captured_invoice["paymentType"] == "02 - Crédito"
        assert captured_invoice["paidAmount"] == pytest.approx(50.0)
        assert captured_invoice["creditAmount"] == pytest.approx(68.0)
        assert captured_invoice["remainingBalance"] == pytest.approx(68.0)
        assert len(captured_invoice["payments"]) == 2
        assert len(cash_txs) == 1
        assert cash_txs[0]["paymentMethod"] == "Efectivo"
        assert cash_txs[0]["amount"] == pytest.approx(50.0)
        register_client.assert_called_once()


def test_ephemeral_dgii_client_rejects_invalid_rnc(app):
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value={"id": "shift-123", "registerId": "reg-1", "status": "OPEN"}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG):
        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "dgii-lookup",
            "clientRnc": "123",
            "clientName": "Cliente inválido",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [{"method": "Efectivo", "amount": 118.0}],
        }):
            _session(app)
            resp = app.view_functions["web_pos.create_pos_sale"]()
            body, status = resp if isinstance(resp, tuple) else (resp, 200)
            data = body.get_json()

        assert status == 400
        assert data["success"] is False


def test_credit_sale_does_not_register_cash(app):
    captured_invoice = {}
    cash_txs = []

    mock_shift = {"id": "shift-123", "registerId": "reg-1", "status": "OPEN"}
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "warehouseId": "wh-1"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.get_client", return_value={"id": "cli-1", "name": "Cliente", "rnc": "131880681", "email": ""}), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=lambda o, i, d, **k: captured_invoice.update(d)), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions", side_effect=lambda o, r, s, txs, **k: cash_txs.extend(txs)), \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", return_value=None), \
         patch("app.services.audit_service.AuditService.log_from_request"):

        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "cli-1",
            "ecfType": "Factura de Crédito Fiscal (E31)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "paymentMethod": "Crédito",
        }):
            _session(app)
            resp = app.view_functions["web_pos.create_pos_sale"]()
            data = resp.get_json()

        assert data["success"] is True
        assert cash_txs == []
        assert captured_invoice["status"] == "Emitida"
        assert captured_invoice["remainingBalance"] == pytest.approx(118.0)
        assert captured_invoice["paymentType"] == "02 - Crédito"


def test_sale_reverts_invoice_when_cash_registration_blocked(app):
    saved_states = []
    failed = []
    emitted = []

    def fake_save(o, i, d, **k):
        saved_states.append((i, d.get("status")))

    mock_shift = {"id": "shift-1", "registerId": "reg-1", "status": "OPEN"}
    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.reserve_idempotency_key", return_value={"status": "RESERVED", "record": {"leaseOwner": "L1"}}), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "warehouseId": "wh-1"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=fake_save), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions", side_effect=CashShiftLockError("La caja no está activa para esta sesión.")), \
         patch("app.web.pos.DatabaseService.fail_idempotency_key", side_effect=lambda *a, **k: failed.append(a)), \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", side_effect=lambda *a, **k: emitted.append(1)), \
         patch("app.services.audit_service.AuditService.log_from_request"):

        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "default",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [{"method": "Efectivo", "amount": 118.0}],
        }, headers={"Idempotency-Key": "sale-rev"}):
            _session(app)
            resp = app.view_functions["web_pos.create_pos_sale"]()
            body, status = resp if isinstance(resp, tuple) else (resp, 200)
            data = body.get_json()

    assert status == 409
    assert data["success"] is False
    # Se guarda dos veces: primero como venta, luego revertida a Anulada.
    assert len(saved_states) == 2
    assert saved_states[-1][1] == "Anulada"
    # No se emite e-CF a DGII antes de confirmar la caja.
    assert emitted == []
    assert len(failed) == 1


def test_sale_reverts_invoice_when_cash_registration_returns_false(app):
    saved_states = []
    emitted = []
    mock_shift = {"id": "shift-1", "registerId": "reg-1", "status": "OPEN"}

    def fake_save(o, i, data, **kwargs):
        saved_states.append(data.get("status"))

    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.consume_next_sequence", return_value=("E320000000043", "log-43")), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=fake_save), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions", return_value=False), \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", side_effect=lambda *a, **k: emitted.append(1)), \
         patch("app.services.audit_service.AuditService.log_from_request"):
        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "default",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [{"method": "Efectivo", "amount": 118.0}],
        }):
            _session(app)
            response = app.view_functions["web_pos.create_pos_sale"]()

    body, status = response if isinstance(response, tuple) else (response, 200)
    data = body.get_json()
    assert status == 409
    assert data["success"] is False
    assert "transacciones del turno" in data["error"]
    assert saved_states == ["Cobrada", "Anulada"]
    assert emitted == []


def test_sale_returns_dgii_rejection_instead_of_success(app):
    saved = {}
    failed = []
    mock_shift = {"id": "shift-1", "registerId": "reg-1", "status": "OPEN"}

    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.reserve_idempotency_key", return_value={"status": "RESERVED", "record": {"leaseOwner": "L1"}}), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=lambda o, i, d, **k: saved.update(d)), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions"), \
         patch("app.web.pos.DatabaseService.fail_idempotency_key", side_effect=lambda *a, **k: failed.append(a)), \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", return_value={
             "success": False,
             "error": "XML rechazado por DGII",
             "dgiiStatus": "REJECTED",
         }), \
         patch("app.services.audit_service.AuditService.log_from_request"):
        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "default",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [{"method": "Efectivo", "amount": 118.0}],
        }, headers={"Idempotency-Key": "sale-rejected"}):
            _session(app)
            response = app.view_functions["web_pos.create_pos_sale"]()

    body, status = response if isinstance(response, tuple) else (response, 200)
    data = body.get_json()
    assert status == 422
    assert data["success"] is False
    assert data["error"] == "XML rechazado por DGII"
    assert data["dgiiStatus"] == "REJECTED"
    assert saved["status"] == "Rechazado DGII"
    assert saved["dgiiError"] == "XML rechazado por DGII"
    assert failed


def test_sale_preserves_rfce_rejection_details(app):
    saved = {}
    mock_shift = {"id": "shift-1", "registerId": "reg-1", "status": "OPEN"}
    rfce_response = {"codigo": 2, "estado": "Rechazado", "mensaje": "XML inválido"}

    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=lambda o, i, d, **k: saved.update(d)), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions"), \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", return_value={
             "success": False,
             "error": "XML inválido",
             "message": "XML inválido",
             "dgiiStatus": "REJECTED",
             "responseBody": rfce_response,
             "codigoRFCE": 2,
             "estadoRFCE": "Rechazado",
         }), \
         patch("app.services.audit_service.AuditService.log_from_request"):
        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "default",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [{"method": "Efectivo", "amount": 118.0}],
        }):
            _session(app)
            response = app.view_functions["web_pos.create_pos_sale"]()

    body, status = response if isinstance(response, tuple) else (response, 200)
    data = body.get_json()
    assert status == 422
    assert data["responseBody"] == rfce_response
    assert data["rfceCode"] == 2
    assert saved["dgiiResponse"] == rfce_response


def test_rfce_duplicate_is_recovered_without_resubmitting():
    invoice = {
        "encf": "E320000000001",
        "clientRNC": "000000000",
        "total": 118.0,
    }
    response = {
        "codigo": 2,
        "estado": "Rechazado",
        "mensaje": "La combinación e-NCF y código de seguridad ya han sido utilizados previamente.",
    }
    with patch.object(DgiiDirectService, "consultar_estado_ecf", return_value={
        "success": True,
        "responseBody": {"estado": "Aceptado", "trackId": "TRACK-1"},
        "statusCode": 200,
    }) as query:
        assert DgiiDirectService._is_rfce_duplicate(response, "")
        recovered = DgiiDirectService._recover_rfce_duplicate(
            {"companyRNC": "131880681"}, invoice, "ABC123", sandbox=True,
        )

    query.assert_called_once()
    assert recovered["success"] is True
    assert recovered["recoveredDuplicate"] is True
    assert recovered["trackId"] == "TRACK-1"


def test_rfce_duplicate_without_recovery_is_terminal_rejection():
    response = {
        "codigo": 2,
        "estado": "Rechazado",
        "mensaje": "La combinación e-NCF y código de seguridad ya han sido utilizados previamente.",
    }
    assert DgiiDirectService._rfce_duplicate_is_terminal_rejection(response, "")


def test_pos_reserves_sequence_before_emission(app):
    captured = {}
    mock_shift = {"id": "shift-1", "registerId": "reg-1", "status": "OPEN"}

    with patch("app.web.pos.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=mock_shift), \
         patch("app.web.pos.DatabaseService.get_idempotency_record", return_value=None), \
         patch("app.web.pos.DatabaseService.reserve_idempotency_key", return_value={"status": "RESERVED", "record": {"leaseOwner": "L1"}}), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"consolidationEnabled": False}), \
         patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.consume_next_sequence", return_value=("E320000000042", "log-42")) as consume, \
         patch("app.web.pos.DatabaseService.save_invoice", side_effect=lambda o, i, d, **k: captured.update(d)), \
         patch("app.web.pos.DatabaseService.register_sale_cash_transactions"), \
         patch("app.web.pos.EcfEmissionService.emit_electronic_comprobante", return_value=None) as emit, \
         patch("app.services.audit_service.AuditService.log_from_request"):
        with app.test_request_context("/pos/invoice/new", method="POST", json={
            "clientId": "default",
            "ecfType": "Factura de Consumo (E32)",
            "items": [{"id": "prod-1", "quantity": 1}],
            "payments": [{"method": "Efectivo", "amount": 118.0}],
        }):
            _session(app)
            app.view_functions["web_pos.create_pos_sale"]()

    consume.assert_called_once()
    assert consume.call_args.args[1] == "E32"
    assert captured["encf"] == "E320000000042"
    assert captured["sequenceLogId"] == "log-42"
    assert emit.call_args.args[1]["encf"] == "E320000000042"


def test_terminal_renders_standalone_shell(app):
    with patch("app.web.pos.DatabaseService.get_items", return_value=CATALOG), \
         patch("app.web.pos.DatabaseService.get_categories", return_value=[]), \
         patch("app.web.pos.DatabaseService.get_branches", return_value=[{"id": "default-sucursal-principal", "name": "Principal"}]), \
         patch("app.web.pos.DatabaseService.get_company_profile", return_value={"name": "Demo SRL"}), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value={"id": "shift-1", "registerId": "reg-1", "status": "OPEN"}), \
         patch("app.web.pos.DatabaseService.get_cash_registers", return_value=[{"id": "reg-1", "name": "Caja 01", "warehouseId": "wh-1", "branchId": "default-sucursal-principal"}]), \
         patch("app.web.pos.DatabaseService.get_warehouses", return_value=[{"id": "wh-1", "name": "Almacén principal", "branchId": "default-sucursal-principal"}]), \
         patch("app.web.pos.DatabaseService.get_default_warehouse", return_value="wh-1"), \
         patch("app.web.pos.DatabaseService.get_user_profile", return_value={"name": "Owner"}), \
         patch("app.web.pos.DatabaseService.get_team_members", return_value=[]), \
         patch("app.web.pos.check_permission", return_value=True):
        with app.test_request_context("/pos/terminal"):
            _session(app)
            html = app.view_functions["web_pos.pos_terminal"]()
            assert "pos-app" in html
            assert "pos-bootstrap" in html
            assert "Producto gravado" in html

            import json
            import re
            match = re.search(r'<script id="pos-bootstrap" type="application/json">(.*?)</script>', html, re.S)
            assert match
            boot = json.loads(match.group(1))
            assert boot["items"][0]["name"] == "Producto gravado"
            assert boot["config"]["branchId"]
