"""Pruebas de ruta para movimientos manuales de caja (Fase 2)."""
from unittest.mock import patch

import pytest

from app import create_app


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
        "name": "Cajero",
    }
    session["selected_company_id"] = "comp-1"
    session["is_sandbox_mode"] = True


MOCK_SHIFT = {"id": "shift-1", "registerId": "reg-1", "status": "OPEN"}


def _call(app, json_payload):
    with app.test_request_context("/pos/shift/transaction", method="POST", json=json_payload):
        _session(app)
        resp = app.view_functions["web_pos.add_manual_transaction"]()
        body = resp[0] if isinstance(resp, tuple) else resp
        status = resp[1] if isinstance(resp, tuple) else 200
        return body.get_json(), status


def test_manual_cash_in_no_authorization(app):
    captured = []

    def fake_register(o, tx, **k):
        tx["id"] = tx.get("id") or "tx-test"
        captured.append(dict(tx))
        return tx

    with patch("app.utils.decorators.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=MOCK_SHIFT), \
         patch("app.web.pos.DatabaseService.register_cash_transaction", side_effect=fake_register), \
         patch("app.services.audit_service.AuditService.log_from_request"):
        data, status = _call(app, {"type": "CASH_IN", "amount": "100.00", "currency": "DOP", "reason": "fondo"})

    assert status == 200
    assert data["success"] is True
    assert captured[0]["type"] == "CASH_IN"
    assert captured[0]["currency"] == "DOP"
    assert captured[0]["performedBy"] == "Cajero"


def test_manual_cash_out_requires_supervisor(app):
    with patch("app.utils.decorators.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=MOCK_SHIFT), \
         patch("app.web.pos.DatabaseService.register_cash_transaction"):
        data, status = _call(app, {"type": "CASH_OUT", "amount": "100.00", "currency": "DOP"})

    assert status == 403
    assert data["success"] is False


def test_manual_expense_above_limit_requires_supervisor(app):
    with patch("app.utils.decorators.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=MOCK_SHIFT), \
         patch("app.web.pos.DatabaseService.register_cash_transaction"), \
         patch("app.web.pos.CashAuthorizationService.get_limits",
               return_value={"EXPENSE": {"DOP": 100.0, "USD": None}}):
        data, status = _call(app, {"type": "EXPENSE", "amount": "200.00", "currency": "DOP"})

    assert status == 403
    assert data["success"] is False


def test_manual_legacy_in_is_normalized(app):
    captured = []

    def fake_register(o, tx, **k):
        tx["id"] = tx.get("id") or "tx-test"
        captured.append(dict(tx))
        return tx

    with patch("app.utils.decorators.check_permission", return_value=True), \
         patch("app.web.pos.DatabaseService.get_open_shift", return_value=MOCK_SHIFT), \
         patch("app.web.pos.DatabaseService.register_cash_transaction", side_effect=fake_register), \
         patch("app.services.audit_service.AuditService.log_from_request"):
        data, status = _call(app, {"type": "IN", "amount": "50.00", "currency": "DOP"})

    assert status == 200
    assert data["success"] is True
    assert captured[0]["type"] == "CASH_IN"
