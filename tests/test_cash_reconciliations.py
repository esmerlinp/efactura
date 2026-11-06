"""Pruebas de Fase 4.3 — conciliación de fondos (CashReconciliation)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import db_service
from app.services.db_service import DatabaseService
from app.services.cash_authorization_service import CashAuthorizationService
from app.services.cash_delivery_service import CashDeliveryService
from app.services.cash_reconciliation_service import (
    CashReconciliationService,
    CashReconciliationError,
    RECONCILIATION_OPEN,
    RECONCILIATION_RECONCILED,
    RECONCILIATION_UNDER_REVIEW,
)
from tests.cash_firestore_double import Store, FieldFilter


class _FirestoreNS:
    transactional = staticmethod(Store.transactional)
    FieldFilter = FieldFilter


@pytest.fixture
def cash_env(monkeypatch):
    store = Store()
    monkeypatch.setattr(db_service, "firebase_initialized", True)
    monkeypatch.setattr(db_service, "db_firestore", store)
    monkeypatch.setattr(db_service, "firestore", _FirestoreNS)
    monkeypatch.setattr(
        db_service, "_company_coll",
        lambda company_id=None, owner_uid=None, coll_name=None: store.collection(
            company_id or "comp-1", coll_name
        ),
    )
    return store


def _seed_lock(cash_env, register_id="reg-1", shift_id="shift-1"):
    cash_env.collection("comp-1", "sandbox_cash_register_locks").document(register_id).set({
        "registerId": register_id, "shiftId": shift_id, "status": "ACTIVE",
        "openedByUserId": "cajero",
        "leaseExpiresAt": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
    })


def _seed_delivery(cash_env, key="dlv-1", amounts=None):
    _seed_lock(cash_env)
    return CashDeliveryService.register_delivery(
        "owner", "comp-1", True, "shift-1", "reg-1",
        amounts=amounts or {"dop": 15000.0, "usd": 0.0}, usd_rate=58.5,
        denominations={"dop": {}, "usd": {}},
        delivered_by_uid="cajero", delivered_by_name="Cajero",
        notes="", idempotency_key=key,
    )["delivery"]


def _seed_shift(cash_env, shift_id="shift-1", expected_card=1000.0, expected_transfer=500.0):
    cash_env.collection("comp-1", "sandbox_cash_shifts").document(shift_id).set({
        "id": shift_id, "expectedCard": expected_card, "expectedTransfer": expected_transfer, "status": "CLOSED",
    })


# ---------------------------------------------------------------------------
# Conciliación de efectivo (CASH_DOP / CASH_USD)
# ---------------------------------------------------------------------------

def test_reconcile_cash_no_difference(cash_env):
    d = _seed_delivery(cash_env, amounts={"dop": 15000.0, "usd": 0.0})
    rec = CashReconciliationService.reconcile_cash(
        "owner", "comp-1", True, d["id"], "CASH_DOP", 15000.0, "", "cajero", "Cajero", "", "rec-1",
    )["reconciliation"]
    assert rec["status"] == RECONCILIATION_RECONCILED
    assert rec["difference"] == 0.0
    assert rec["expectedAmount"] == 15000.0


def test_reconcile_cash_with_difference_under_review(cash_env):
    d = _seed_delivery(cash_env, amounts={"dop": 15000.0, "usd": 0.0})
    rec = CashReconciliationService.reconcile_cash(
        "owner", "comp-1", True, d["id"], "CASH_DOP", 14000.0, "", "cajero", "Cajero", "", "rec-2",
    )["reconciliation"]
    assert rec["status"] == RECONCILIATION_UNDER_REVIEW
    assert rec["difference"] == -1000.0


def test_reconcile_cash_usd(cash_env):
    d = _seed_delivery(cash_env, amounts={"dop": 0.0, "usd": 100.0})
    rec = CashReconciliationService.reconcile_cash(
        "owner", "comp-1", True, d["id"], "CASH_USD", 100.0, "", "cajero", "Cajero", "", "rec-3",
    )["reconciliation"]
    assert rec["status"] == RECONCILIATION_RECONCILED
    assert rec["expectedAmount"] == 100.0


def test_reconcile_cash_invalid_channel(cash_env):
    d = _seed_delivery(cash_env)
    with pytest.raises(CashReconciliationError):
        CashReconciliationService.reconcile_cash(
            "owner", "comp-1", True, d["id"], "CARD", 100.0, "", "cajero", "Cajero", "", "rec-x")


def test_reconcile_cash_delivery_without_currency(cash_env):
    d = _seed_delivery(cash_env, amounts={"dop": 15000.0, "usd": 0.0})
    with pytest.raises(CashReconciliationError):
        CashReconciliationService.reconcile_cash(
            "owner", "comp-1", True, d["id"], "CASH_USD", 100.0, "", "cajero", "Cajero", "", "rec-y")


# ---------------------------------------------------------------------------
# Conciliación de canales (CARD / TRANSFER)
# ---------------------------------------------------------------------------

def test_reconcile_channel_card(cash_env):
    _seed_shift(cash_env, expected_card=1000.0, expected_transfer=500.0)
    rec = CashReconciliationService.reconcile_channel(
        "owner", "comp-1", True, "shift-1", "CARD", 950.0, "lote-1", "cajero", "Cajero", "", "rec-4",
    )["reconciliation"]
    assert rec["status"] == RECONCILIATION_UNDER_REVIEW
    assert rec["difference"] == -50.0
    assert rec["expectedAmount"] == 1000.0


def test_reconcile_channel_transfer(cash_env):
    _seed_shift(cash_env, expected_card=1000.0, expected_transfer=500.0)
    rec = CashReconciliationService.reconcile_channel(
        "owner", "comp-1", True, "shift-1", "TRANSFER", 500.0, "dep-1", "cajero", "Cajero", "", "rec-5",
    )["reconciliation"]
    assert rec["status"] == RECONCILIATION_RECONCILED


# ---------------------------------------------------------------------------
# Idempotencia
# ---------------------------------------------------------------------------

def test_reconcile_idempotent(cash_env):
    d = _seed_delivery(cash_env)
    r1 = CashReconciliationService.reconcile_cash("owner", "comp-1", True, d["id"], "CASH_DOP", 15000.0, "", "cajero", "Cajero", "", "rec-6")
    r2 = CashReconciliationService.reconcile_cash("owner", "comp-1", True, d["id"], "CASH_DOP", 15000.0, "", "cajero", "Cajero", "", "rec-6")
    assert r1["already"] is False
    assert r2["already"] is True
    assert r1["reconciliation"]["id"] == r2["reconciliation"]["id"]


def test_reconcile_reuse_key_different_received_rejected(cash_env):
    d = _seed_delivery(cash_env)
    CashReconciliationService.reconcile_cash("owner", "comp-1", True, d["id"], "CASH_DOP", 15000.0, "", "cajero", "Cajero", "", "rec-7")
    with pytest.raises(CashReconciliationError):
        CashReconciliationService.reconcile_cash("owner", "comp-1", True, d["id"], "CASH_DOP", 14000.0, "", "cajero", "Cajero", "", "rec-7")


# ---------------------------------------------------------------------------
# Aprobación de diferencias (autorización single-use de supervisor)
# ---------------------------------------------------------------------------

def _authorize(monkeypatch, performer_uid, supervisor_uid, auth_request_id, amount, register_id, shift_id):
    monkeypatch.setattr(DatabaseService, "validate_pos_supervisor_pin",
                        lambda *a, **k: {"valid": True, "name": "Sup", "email": "s@x"})
    CashAuthorizationService.authorize(
        "owner", "comp-1", True, performer_uid, supervisor_uid, "1", auth_request_id,
        "RECONCILIATION_APPROVE", amount, "DOP", register_id, shift_id)


def test_approve_difference(cash_env, monkeypatch):
    d = _seed_delivery(cash_env, amounts={"dop": 15000.0, "usd": 0.0})
    rec = CashReconciliationService.reconcile_cash("owner", "comp-1", True, d["id"], "CASH_DOP", 14000.0, "", "cajero", "Cajero", "", "rec-8")["reconciliation"]
    _authorize(monkeypatch, "cajero", "sup", "ap-1", abs(rec["difference"]), rec["deliveryId"], rec["shiftId"])
    updated = CashReconciliationService.approve_difference(
        "owner", "comp-1", True, rec["id"], "justificacion", "cajero", "Cajero", "ap-1", "cajero")
    assert updated["status"] == RECONCILIATION_RECONCILED
    assert updated["approvedBy"]["uid"] == "sup"
    assert updated["approvalJustification"] == "justificacion"


def test_approve_already_reconciled_idempotent(cash_env, monkeypatch):
    d = _seed_delivery(cash_env, amounts={"dop": 15000.0, "usd": 0.0})
    rec = CashReconciliationService.reconcile_cash("owner", "comp-1", True, d["id"], "CASH_DOP", 15000.0, "", "cajero", "Cajero", "", "rec-9")["reconciliation"]
    assert rec["status"] == RECONCILIATION_RECONCILED
    updated = CashReconciliationService.approve_difference(
        "owner", "comp-1", True, rec["id"], "x", "cajero", "Cajero", "ap-x", "cajero")
    assert updated["status"] == RECONCILIATION_RECONCILED


def test_approve_reuse_authorization_rejected(cash_env, monkeypatch):
    d = _seed_delivery(cash_env, amounts={"dop": 15000.0, "usd": 0.0})
    rec1 = CashReconciliationService.reconcile_cash("owner", "comp-1", True, d["id"], "CASH_DOP", 14000.0, "", "cajero", "Cajero", "", "rec-10")["reconciliation"]
    rec2 = CashReconciliationService.reconcile_cash("owner", "comp-1", True, d["id"], "CASH_DOP", 13000.0, "", "cajero", "Cajero", "", "rec-11")["reconciliation"]
    _authorize(monkeypatch, "cajero", "sup", "ap-reuse", abs(rec1["difference"]), rec1["deliveryId"], rec1["shiftId"])
    CashReconciliationService.approve_difference("owner", "comp-1", True, rec1["id"], "j", "cajero", "Cajero", "ap-reuse", "cajero")
    # Reutilizar la misma autorización para otra conciliación → rechazada.
    with pytest.raises(CashReconciliationError):
        CashReconciliationService.approve_difference("owner", "comp-1", True, rec2["id"], "j", "cajero", "Cajero", "ap-reuse", "cajero")
