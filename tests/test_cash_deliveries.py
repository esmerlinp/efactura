"""Pruebas de Fase 4.2 — entrega de fondos (CashDelivery)."""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.services import db_service
from app.services.db_service import DatabaseService, CashShiftLockError
from app.services.cash_delivery_service import (
    CashDeliveryService,
    CashDeliveryError,
    DELIVERY_PENDING_RECEIPT,
    DELIVERY_RECEIVED,
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


def _seed_lock(cash_env, register_id, shift_id, status="ACTIVE"):
    cash_env.collection("comp-1", "sandbox_cash_register_locks").document(register_id).set({
        "registerId": register_id, "shiftId": shift_id, "status": status,
        "openedByUserId": "cajero",
        "leaseExpiresAt": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
    })


def _register(cash_env, key="k1", amounts=None, shift_id="shift-1", register_id="reg-1",
              usd_rate=58.5, denominations=None):
    amounts = amounts if amounts is not None else {"dop": 15000.0, "usd": 0.0}
    return CashDeliveryService.register_delivery(
        "owner", "comp-1", True, shift_id=shift_id, register_id=register_id,
        amounts=amounts, usd_rate=usd_rate,
        denominations=denominations if denominations is not None else {"dop": {}, "usd": {}},
        delivered_by_uid="cajero", delivered_by_name="Cajero",
        notes="", idempotency_key=key,
    )


def _auth(cash_env, delivery_id, receiver_uid):
    return CashDeliveryService.create_receipt_authorization(
        "owner", "comp-1", True, delivery_id, receiver_uid)["authorizationId"]


def _confirm(cash_env, delivery_id, receiver_uid, pin, auth_id, name="Receptor"):
    return CashDeliveryService.confirm_receipt(
        "owner", "comp-1", True, delivery_id, receiver_uid, name, pin, "", auth_id,
    )


def _receiver_pin(cash_env, uid="receptor", pin="1234"):
    CashDeliveryService.set_reception_pin("owner", "comp-1", True, uid, pin)


# ---------------------------------------------------------------------------
# Registro de entrega (creación conjunta CASH_DROP + CashDelivery)
# ---------------------------------------------------------------------------

def test_register_delivery_dop_only_creates_one_drop(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    delivery = _register(cash_env, key="k1", amounts={"dop": 15000.0, "usd": 0.0})["delivery"]
    assert delivery["status"] == DELIVERY_PENDING_RECEIPT
    assert delivery["cashDropTransactionIds"] == [f"dlv-{delivery['id']}-drop-dop"]
    drops = [d.to_dict() for d in cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("type", "==", "CASH_DROP")).get()]
    assert len(drops) == 1 and drops[0]["currency"] == "DOP" and drops[0]["amount"] == 15000.0


def test_register_delivery_usd_only(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _register(cash_env, key="k2", amounts={"dop": 0.0, "usd": 100.0})
    drops = [d.to_dict() for d in cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("type", "==", "CASH_DROP")).get()]
    assert len(drops) == 1 and drops[0]["currency"] == "USD"


def test_combined_amounts_kept_separate(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    delivery = _register(cash_env, key="k3", amounts={"dop": 15000.0, "usd": 100.0})["delivery"]
    assert delivery["amounts"]["dop"] == 15000.0
    assert delivery["amounts"]["usd"] == 100.0
    assert "declaredTotal" not in delivery


def test_negative_amounts_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="n1", amounts={"dop": -10.0, "usd": 0.0})
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="n2", amounts={"dop": 0.0, "usd": -5.0})


# ---------------------------------------------------------------------------
# Integridad monetaria y denominaciones
# ---------------------------------------------------------------------------

def test_fractional_denomination_count_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="d1", amounts={"dop": 1500.0, "usd": 0.0},
                  denominations={"dop": {"1000": 1.5}, "usd": {}})


def test_negative_denomination_count_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="d2", amounts={"dop": 1000.0, "usd": 0.0},
                  denominations={"dop": {"1000": -1}, "usd": {}})


def test_unknown_denomination_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="d3", amounts={"dop": 7.0, "usd": 0.0},
                  denominations={"dop": {"7": 1}, "usd": {}})


def test_denomination_mismatch_with_amount_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="d4", amounts={"dop": 15000.0, "usd": 0.0},
                  denominations={"dop": {"1000": 14}, "usd": {}})  # 14000 != 15000


def test_denomination_coherent_accepted(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    delivery = _register(cash_env, key="d5", amounts={"dop": 15000.0, "usd": 0.0},
                         denominations={"dop": {"1000": 15}, "usd": {}})["delivery"]
    assert delivery["denominations"]["dop"]["1000"] == 15


# ---------------------------------------------------------------------------
# Idempotencia (D2) — firma completa
# ---------------------------------------------------------------------------

def test_retry_same_key_is_idempotent(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    r1 = _register(cash_env, key="k1", amounts={"dop": 15000.0, "usd": 0.0})
    r2 = _register(cash_env, key="k1", amounts={"dop": 15000.0, "usd": 0.0})
    assert r1["already"] is False and r2["already"] is True
    assert r1["delivery"]["id"] == r2["delivery"]["id"]


def test_reuse_key_different_content_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _register(cash_env, key="k1", amounts={"dop": 15000.0, "usd": 0.0})
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="k1", amounts={"dop": 20000.0, "usd": 0.0})
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="k1", register_id="reg-2")
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="k1", usd_rate=59.0)


def test_usd_rate_precision_in_signature(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _register(cash_env, key="r1", amounts={"dop": 0.0, "usd": 100.0}, usd_rate=58.5)
    # mismo valor económico → idempotente (no rechazado)
    r2 = _register(cash_env, key="r1", amounts={"dop": 0.0, "usd": 100.0}, usd_rate=58.5)
    assert r2["already"] is True
    # valor económicamente distinto → rechazado
    with pytest.raises(CashDeliveryError):
        _register(cash_env, key="r1", amounts={"dop": 0.0, "usd": 100.0}, usd_rate=58.51)


# ---------------------------------------------------------------------------
# Autorización de recepción — ciclo de vida
# ---------------------------------------------------------------------------

def test_authorization_flow_success(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env)
    delivery_id = _register(cash_env, key="k1")["delivery"]["id"]
    auth_id = _auth(cash_env, delivery_id, "receptor")
    d = _confirm(cash_env, delivery_id, "receptor", "1234", auth_id)
    assert d["status"] == DELIVERY_RECEIVED
    assert d["receivedBy"]["uid"] == "receptor"


def test_invented_authorization_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env)
    delivery_id = _register(cash_env, key="k1")["delivery"]["id"]
    with pytest.raises(CashDeliveryError):
        _confirm(cash_env, delivery_id, "receptor", "1234", "invented-auth-id")


def test_authorization_of_other_delivery_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env)
    dA = _register(cash_env, key="ka", amounts={"dop": 1000.0, "usd": 0.0})["delivery"]["id"]
    dB = _register(cash_env, key="kb", amounts={"dop": 2000.0, "usd": 0.0})["delivery"]["id"]
    authA = _auth(cash_env, dA, "receptor")
    with pytest.raises(CashDeliveryError):
        _confirm(cash_env, dB, "receptor", "1234", authA)


def test_authorization_of_other_receiver_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env, "receptor", "1234")
    delivery_id = _register(cash_env, key="k1")["delivery"]["id"]
    auth_id = _auth(cash_env, delivery_id, "receptor")
    with pytest.raises(CashDeliveryError):
        _confirm(cash_env, delivery_id, "otro-receptor", "9999", auth_id)


def test_authorization_of_other_company_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env)
    delivery_id = _register(cash_env, key="k1")["delivery"]["id"]
    auth_id = _auth(cash_env, delivery_id, "receptor")
    # Manipular el campo companyId de la autorización.
    auth_ref = cash_env.collection("comp-1", "sandbox_cash_receipt_authorizations").document(auth_id)
    stored = auth_ref.get().to_dict()
    stored["companyId"] = "otra-empresa"
    auth_ref.set(stored)
    with pytest.raises(CashDeliveryError):
        _confirm(cash_env, delivery_id, "receptor", "1234", auth_id)


def test_expired_authorization_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env)
    delivery_id = _register(cash_env, key="k1")["delivery"]["id"]
    auth_id = _auth(cash_env, delivery_id, "receptor")
    auth_ref = cash_env.collection("comp-1", "sandbox_cash_receipt_authorizations").document(auth_id)
    stored = auth_ref.get().to_dict()
    stored["expiresAt"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    auth_ref.set(stored)
    with pytest.raises(CashDeliveryError):
        _confirm(cash_env, delivery_id, "receptor", "1234", auth_id)


def test_consumed_authorization_rejected(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env)
    dA = _register(cash_env, key="ka", amounts={"dop": 1000.0, "usd": 0.0})["delivery"]["id"]
    dB = _register(cash_env, key="kb", amounts={"dop": 2000.0, "usd": 0.0})["delivery"]["id"]
    authA = _auth(cash_env, dA, "receptor")
    _confirm(cash_env, dA, "receptor", "1234", authA)  # consume
    # Reutilizar la misma autorización (consumida) en otra entrega.
    with pytest.raises(CashDeliveryError):
        _confirm(cash_env, dB, "receptor", "1234", authA)


def test_concurrent_consume_single_authorization(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env)
    delivery_id = _register(cash_env, key="k1")["delivery"]["id"]
    auth_id = _auth(cash_env, delivery_id, "receptor")
    results = []
    errors = []

    def do():
        try:
            results.append(_confirm(cash_env, delivery_id, "receptor", "1234", auth_id))
        except CashDeliveryError as e:
            errors.append(e)

    threads = [threading.Thread(target=do) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 2  # una consume, la otra idempotente
    auth_doc = cash_env.collection("comp-1", "sandbox_cash_receipt_authorizations").document(auth_id).get().to_dict()
    assert auth_doc["status"] == "CONSUMED"


def test_failed_pin_does_not_consume_authorization(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1")
    _receiver_pin(cash_env)
    delivery_id = _register(cash_env, key="k1")["delivery"]["id"]
    auth_id = _auth(cash_env, delivery_id, "receptor")
    with pytest.raises(CashDeliveryError):
        _confirm(cash_env, delivery_id, "receptor", "0000", auth_id)
    auth_doc = cash_env.collection("comp-1", "sandbox_cash_receipt_authorizations").document(auth_id).get().to_dict()
    assert auth_doc["status"] == "PENDING"  # no consumida
    assert CashDeliveryService.get_delivery("owner", "comp-1", True, delivery_id)["status"] == DELIVERY_PENDING_RECEIPT


def test_reception_pin_stored_hashed_with_salt(cash_env):
    _receiver_pin(cash_env)
    pin_doc = cash_env.collection("comp-1", "sandbox_cash_reception_pins").document("receptor").get().to_dict()
    assert pin_doc["pinHash"] != "1234" and len(pin_doc["pinHash"]) == 64
