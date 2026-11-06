"""Pruebas de Fase 2 — taxonomía, autorizaciones, límites y transferencias."""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.services import db_service
from app.services.db_service import (
    DatabaseService,
    normalize_cash_type,
    CashAuthorizationError,
    CashShiftLockError,
    CASH_TYPE_CASH_IN,
    CASH_TYPE_CASH_OUT,
    CASH_TYPE_EXPENSE,
)
from app.services.cash_authorization_service import CashAuthorizationService
from app.services.cash_transfer_service import CashTransferService, CashTransferError
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


def _seed_lock(cash_env, register_id, shift_id, status):
    cash_env.collection("comp-1", "sandbox_cash_register_locks").document(register_id).set({
        "registerId": register_id, "shiftId": shift_id, "status": status,
        "openedByUserId": "user-1",
        "leaseExpiresAt": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
    })


# ---------------------------------------------------------------------------
# Taxonomía
# ---------------------------------------------------------------------------

def test_normalize_cash_type_legacy():
    assert normalize_cash_type("IN") == CASH_TYPE_CASH_IN
    assert normalize_cash_type("out") == CASH_TYPE_CASH_OUT
    assert normalize_cash_type("CASH_DROP") == "CASH_DROP"
    assert normalize_cash_type("") == ""


def test_register_cash_transaction_normalizes_type_and_currency(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    tx = DatabaseService.register_cash_transaction(
        "owner", {"shiftId": "shift-1", "type": "IN", "amount": 10.0, "currency": "USD"},
        company_id="comp-1", sandbox=True, register_id="reg-1", shift_id="shift-1",
    )
    assert tx is not None
    assert tx["type"] == CASH_TYPE_CASH_IN
    assert tx["currency"] == "USD"


# ---------------------------------------------------------------------------
# Matriz de autorización y límites por moneda
# ---------------------------------------------------------------------------

def test_authorization_matrix():
    limits = {
        CASH_TYPE_CASH_IN: {"DOP": None, "USD": None},
        CASH_TYPE_EXPENSE: {"DOP": 50000.0, "USD": None},
        CASH_TYPE_CASH_OUT: {"DOP": None, "USD": None},
    }
    A = CashAuthorizationService
    for t in ("CASH_OUT", "CASH_DROP", "FUND_IN", "FUND_OUT", "TRANSFER_IN", "TRANSFER_OUT"):
        assert A.movement_requires_supervisor(t, 1.0, "DOP", limits)[0] is True
    # CASH_IN sin límite → no requiere
    assert A.movement_requires_supervisor(CASH_TYPE_CASH_IN, 999999.0, "DOP", limits)[0] is False
    # EXPENSE dentro del límite → no requiere
    assert A.movement_requires_supervisor(CASH_TYPE_EXPENSE, 50000.0, "DOP", limits)[0] is False
    # EXPENSE por encima → requiere
    assert A.movement_requires_supervisor(CASH_TYPE_EXPENSE, 50000.01, "DOP", limits)[0] is True
    # EXPENSE en USD sin límite configurado → no requiere (límites independientes)
    assert A.movement_requires_supervisor(CASH_TYPE_EXPENSE, 999999.0, "USD", limits)[0] is False


def test_limit_independent_per_currency():
    limits = {CASH_TYPE_EXPENSE: {"DOP": 50000.0, "USD": 1000.0}}
    A = CashAuthorizationService
    # 1000 USD (≤ límite USD) no requiere; 1001 USD sí.
    assert A.movement_requires_supervisor(CASH_TYPE_EXPENSE, 1000.0, "USD", limits)[0] is False
    assert A.movement_requires_supervisor(CASH_TYPE_EXPENSE, 1001.0, "USD", limits)[0] is True
    # El mismo monto en DOP no se compara contra el límite USD.
    assert A.movement_requires_supervisor(CASH_TYPE_EXPENSE, 1001.0, "DOP", limits)[0] is False


# ---------------------------------------------------------------------------
# PIN vinculado, de un solo uso y SoD
# ---------------------------------------------------------------------------

def test_authorize_rejects_self_authorization(cash_env, monkeypatch):
    monkeypatch.setattr(DatabaseService, "validate_pos_supervisor_pin",
                        lambda *a, **k: {"valid": True, "name": "Sup", "email": "s@x"})
    with pytest.raises(CashAuthorizationError):
        CashAuthorizationService.authorize(
            "owner", "comp-1", True, performer_uid="u1", supervisor_uid="u1", pin="1",
            auth_request_id="r1", movement_type=CASH_TYPE_CASH_OUT, amount=10, currency="DOP",
            register_id="reg-1", shift_id="shift-1",
        )


def test_authorize_rejects_invalid_pin(cash_env, monkeypatch):
    monkeypatch.setattr(DatabaseService, "validate_pos_supervisor_pin",
                        lambda *a, **k: {"valid": False, "name": "Sup", "email": "s@x"})
    with pytest.raises(CashAuthorizationError):
        CashAuthorizationService.authorize(
            "owner", "comp-1", True, "u1", "u2", "wrong", "r1",
            CASH_TYPE_CASH_OUT, 10, "DOP", "reg-1", "shift-1",
        )


def test_authorize_single_use_and_binds_context(cash_env, monkeypatch):
    monkeypatch.setattr(DatabaseService, "validate_pos_supervisor_pin",
                        lambda *a, **k: {"valid": True, "name": "Sup", "email": "s@x"})
    a = CashAuthorizationService.authorize(
        "owner", "comp-1", True, "u1", "u2", "1", "r1",
        CASH_TYPE_CASH_OUT, 10, "DOP", "reg-1", "shift-1",
    )
    assert a["name"] == "Sup"
    # Reutilizar la misma solicitud (auth_request_id) → rechazado (single-use).
    with pytest.raises(CashAuthorizationError):
        CashAuthorizationService.authorize(
            "owner", "comp-1", True, "u1", "u2", "1", "r1",
            CASH_TYPE_CASH_OUT, 10, "DOP", "reg-1", "shift-1",
        )


# ---------------------------------------------------------------------------
# Conciliación por moneda en el cierre
# ---------------------------------------------------------------------------

def test_close_routes_manual_usd_to_expected_usd(cash_env):
    shift_id = "shift-1"
    reg = "reg-1"
    cash_env.collection("comp-1", "sandbox_cash_shifts").document(shift_id).set({
        "id": shift_id, "registerId": reg, "openingAmount": 0.0, "status": "OPEN",
        "openingTime": "2026-01-01T00:00:00+00:00",
    })
    cash_env.collection("comp-1", "sandbox_cash_registers").document(reg).set({"id": reg, "status": "OPEN"})
    _seed_lock(cash_env, reg, shift_id, "ACTIVE")
    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    txs.document("t1").set({"id": "t1", "shiftId": shift_id, "type": "CASH_IN", "amount": 100.0, "currency": "DOP", "paymentMethod": "Efectivo"})
    txs.document("t2").set({"id": "t2", "shiftId": shift_id, "type": "CASH_IN", "amount": 50.0, "currency": "USD", "paymentMethod": "Efectivo"})

    res = DatabaseService.close_cash_shift(
        "owner", shift_id, 3025.0, company_id="comp-1", sandbox=True,
        declared_data={"declaredCash": 100.0, "declaredCard": 0.0, "declaredTransfer": 0.0,
                       "declaredUSD": 50.0, "usdExchangeRate": 58.5, "cashDenominations": {}, "cardLoteNumber": ""},
    )
    assert res is not None
    assert res["expectedCash"] == 100.0
    assert res["expectedUSD"] == 50.0
    assert res["difference"] == 0.0


# ---------------------------------------------------------------------------
# Transferencias atómicas
# ---------------------------------------------------------------------------

def test_transfer_atomic_and_idempotent(cash_env):
    _seed_lock(cash_env, "reg-src", "shift-src", "ACTIVE")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")

    def do_transfer():
        return CashTransferService.register_transfer(
            "owner", "comp-1", True,
            source_shift={"id": "shift-src", "registerId": "reg-src"},
            target_shift={"id": "shift-dst", "registerId": "reg-dst"},
            amount=1000.0, currency="DOP", reason="traspaso",
            performed_by="Cajero", authorized_by="Sup", authorized_by_uid="sup1",
            transfer_id="tr-1",
        )

    res = do_transfer()
    assert res["transferId"] == "tr-1"
    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    first = [d.to_dict() for d in txs.where(filter=FieldFilter("transferId", "==", "tr-1")).get()]
    assert sorted(t["type"] for t in first) == ["TRANSFER_IN", "TRANSFER_OUT"]
    assert len(first) == 2

    # Reintento con el mismo transfer_id: no duplica.
    do_transfer()
    second = [d.to_dict() for d in txs.where(filter=FieldFilter("transferId", "==", "tr-1")).get()]
    assert len(second) == 2


def test_transfer_requires_active_source_and_target(cash_env):
    _seed_lock(cash_env, "reg-src", "shift-src", "CLOSING")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")
    with pytest.raises(CashShiftLockError):
        CashTransferService.register_transfer(
            "owner", "comp-1", True,
            source_shift={"id": "shift-src", "registerId": "reg-src"},
            target_shift={"id": "shift-dst", "registerId": "reg-dst"},
            amount=1000.0, currency="DOP", reason="x",
            performed_by="Cajero", authorized_by="Sup", authorized_by_uid="s",
            transfer_id="tr-2",
        )
    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    assert [d.to_dict() for d in txs.where(filter=FieldFilter("transferId", "==", "tr-2")).get()] == []


# ---------------------------------------------------------------------------
# R1 — Idempotencia de transferencias
# ---------------------------------------------------------------------------

def _do_transfer(transfer_id=None, idempotency_key=None, amount=1000.0, currency="DOP",
                 source=("reg-src", "shift-src"), target=("reg-dst", "shift-dst")):
    return CashTransferService.register_transfer(
        "owner", "comp-1", True,
        source_shift={"id": source[1], "registerId": source[0]},
        target_shift={"id": target[1], "registerId": target[0]},
        amount=amount, currency=currency, reason="x",
        performed_by="Cajero", authorized_by="Sup", authorized_by_uid="s",
        transfer_id=transfer_id, idempotency_key=idempotency_key,
    )


def test_transfer_idempotent_by_key_retry(cash_env):
    _seed_lock(cash_env, "reg-src", "shift-src", "ACTIVE")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")
    r1 = _do_transfer(idempotency_key="transfer-key-1")
    r2 = _do_transfer(idempotency_key="transfer-key-1")  # retry, sin transfer_id

    assert r1["transferId"] == r2["transferId"]
    assert r2.get("idempotentHit") is True
    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    docs = [d.to_dict() for d in txs.where(filter=FieldFilter("transferId", "==", r1["transferId"])).get()]
    assert len(docs) == 2


def test_transfer_key_reuse_with_different_params_rejected(cash_env):
    _seed_lock(cash_env, "reg-src", "shift-src", "ACTIVE")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")
    _do_transfer(idempotency_key="transfer-key-1", amount=1000.0)
    with pytest.raises(CashTransferError):
        _do_transfer(idempotency_key="transfer-key-1", amount=2000.0)  # mismo key, otro importe


def test_transfer_concurrent_same_key_single_result(cash_env):
    _seed_lock(cash_env, "reg-src", "shift-src", "ACTIVE")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")
    errors = []

    def do():
        try:
            _do_transfer(idempotency_key="transfer-key-conc")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    docs = [d.to_dict() for d in txs.where(filter=FieldFilter("idempotencyKey", "==", "transfer-key-conc")).get()]
    assert len(docs) == 2  # una sola transferencia (out+in)


def test_transfer_to_mismatched_target_session_rejected(cash_env):
    _seed_lock(cash_env, "reg-src", "shift-src", "ACTIVE")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")  # lock destino apunta a shift-dst
    with pytest.raises(CashShiftLockError):
        _do_transfer(source=("reg-src", "shift-src"), target=("reg-dst", "shift-otra"),
                     idempotency_key="transfer-mismatch")


# ---------------------------------------------------------------------------
# R2 — Consumo atómico de autorización
# ---------------------------------------------------------------------------

def _authorize(cash_env, monkeypatch, auth_request_id, movement_type="CASH_OUT", amount=100.0):
    monkeypatch.setattr(DatabaseService, "validate_pos_supervisor_pin",
                        lambda *a, **k: {"valid": True, "name": "Sup", "email": "s@x"})
    CashAuthorizationService.authorize(
        "owner", "comp-1", True, "u1", "u2", "1", auth_request_id,
        movement_type, amount, "DOP", "reg-1", "shift-1",
    )


def test_authorization_wrong_context_rejected(cash_env, monkeypatch):
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _authorize(cash_env, monkeypatch, "auth-wrong", "CASH_OUT", 100.0)
    with pytest.raises(CashAuthorizationError):
        DatabaseService.register_cash_transaction(
            "owner", {"shiftId": "shift-1", "type": "CASH_OUT", "amount": 999.0, "currency": "DOP", "reason": "x", "performedBy": "u1"},
            company_id="comp-1", sandbox=True, register_id="reg-1", shift_id="shift-1",
            auth_request_id="auth-wrong", performer_uid="u1",
        )


def test_concurrent_movements_single_authorization_consumption(cash_env, monkeypatch):
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _authorize(cash_env, monkeypatch, "auth-conc", "CASH_OUT", 100.0)
    results = []
    errors = []

    def do():
        try:
            tx = {"shiftId": "shift-1", "type": "CASH_OUT", "amount": 100.0, "currency": "DOP",
                  "reason": "x", "performedBy": "u1"}
            results.append(DatabaseService.register_cash_transaction(
                "owner", tx, company_id="comp-1", sandbox=True,
                register_id="reg-1", shift_id="shift-1",
                auth_request_id="auth-conc", performer_uid="u1",
            ))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    docs = [d.to_dict() for d in txs.where(filter=FieldFilter("shiftId", "==", "shift-1")).get()]
    assert len(docs) == 1   # solo un movimiento consumió la autorización
    assert len(errors) == 1


def test_authorization_consumed_with_movement_atomically(cash_env, monkeypatch):
    """Consumo y movimiento se confirman juntos: si el lock no está ACTIVE, no se consume."""
    _seed_lock(cash_env, "reg-1", "shift-1", "CLOSING")
    _authorize(cash_env, monkeypatch, "auth-lock")
    with pytest.raises(CashShiftLockError):
        DatabaseService.register_cash_transaction(
            "owner", {"shiftId": "shift-1", "type": "CASH_OUT", "amount": 100.0, "currency": "DOP", "reason": "x", "performedBy": "u1"},
            company_id="comp-1", sandbox=True, register_id="reg-1", shift_id="shift-1",
            auth_request_id="auth-lock", performer_uid="u1",
        )
    auth_ref = cash_env.collection("comp-1", "sandbox_cash_authorizations").document("auth-lock")
    assert auth_ref.get().to_dict()["status"] == "PENDING"  # no se consumió


def test_expired_authorization_cannot_be_consumed(cash_env, monkeypatch):
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _authorize(cash_env, monkeypatch, "auth-exp")
    # Forzar expiración del lease de la autorización.
    ref = cash_env.collection("comp-1", "sandbox_cash_authorizations").document("auth-exp")
    ref.update({"expiresAt": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()})
    with pytest.raises(CashAuthorizationError):
        DatabaseService.register_cash_transaction(
            "owner", {"shiftId": "shift-1", "type": "CASH_OUT", "amount": 100.0, "currency": "DOP", "reason": "x", "performedBy": "u1"},
            company_id="comp-1", sandbox=True, register_id="reg-1", shift_id="shift-1",
            auth_request_id="auth-exp", performer_uid="u1",
        )


# ---------------------------------------------------------------------------
# R1 — Idempotencia con transfer_id explícito y ámbito
# ---------------------------------------------------------------------------

def test_transfer_explicit_transfer_id_mismatch_rejected(cash_env):
    _seed_lock(cash_env, "reg-src", "shift-src", "ACTIVE")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")
    with pytest.raises(CashTransferError):
        _do_transfer(transfer_id="tr-otro", idempotency_key="transfer-key-1")


def test_transfer_scope_differs_by_company_and_environment():
    a = CashTransferService._derive_transfer_id("comp-A", True, "k")
    b = CashTransferService._derive_transfer_id("comp-B", True, "k")
    c = CashTransferService._derive_transfer_id("comp-A", False, "k")
    assert a != b
    assert a != c
    assert a == CashTransferService._derive_transfer_id("comp-A", True, "k")  # determinista


# ---------------------------------------------------------------------------
# R2 — Orden de lecturas/escrituras e idempotencia del consumo
# ---------------------------------------------------------------------------

def test_transfer_idempotent_hit_does_not_consume_new_authorization(cash_env, monkeypatch):
    _seed_lock(cash_env, "reg-src", "shift-src", "ACTIVE")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")
    monkeypatch.setattr(DatabaseService, "validate_pos_supervisor_pin",
                        lambda *a, **k: {"valid": True, "name": "Sup", "email": "s@x"})
    CashAuthorizationService.authorize("owner", "comp-1", True, "u1", "u2", "1", "auth-t1",
                                       "TRANSFER_OUT", 1000.0, "DOP", "reg-src", "shift-src")
    CashTransferService.register_transfer(
        "owner", "comp-1", True,
        source_shift={"id": "shift-src", "registerId": "reg-src"},
        target_shift={"id": "shift-dst", "registerId": "reg-dst"},
        amount=1000.0, currency="DOP", reason="x", performed_by="C", authorized_by="S", authorized_by_uid="s",
        idempotency_key="transfer-key-1", auth_request_id="auth-t1", performer_uid="u1",
    )
    # Reintento con una autorización NUEVA: debe devolver la existente sin consumirla.
    CashAuthorizationService.authorize("owner", "comp-1", True, "u1", "u2", "1", "auth-t2",
                                       "TRANSFER_OUT", 1000.0, "DOP", "reg-src", "shift-src")
    res = CashTransferService.register_transfer(
        "owner", "comp-1", True,
        source_shift={"id": "shift-src", "registerId": "reg-src"},
        target_shift={"id": "shift-dst", "registerId": "reg-dst"},
        amount=1000.0, currency="DOP", reason="x", performed_by="C", authorized_by="S", authorized_by_uid="s",
        idempotency_key="transfer-key-1", auth_request_id="auth-t2", performer_uid="u1",
    )
    assert res["idempotentHit"] is True
    auth2 = cash_env.collection("comp-1", "sandbox_cash_authorizations").document("auth-t2").get().to_dict()
    assert auth2["status"] == "PENDING"  # la autorización nueva no se consumió


def test_transfer_partial_preexisting_rejected(cash_env):
    _seed_lock(cash_env, "reg-src", "shift-src", "ACTIVE")
    _seed_lock(cash_env, "reg-dst", "shift-dst", "ACTIVE")
    tid = CashTransferService._derive_transfer_id("comp-1", True, "transfer-key-partial")
    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    txs.document(f"transfer-{tid}-out").set({
        "id": f"transfer-{tid}-out", "transferId": tid, "idempotencyKey": "transfer-key-partial",
        "contentSignature": CashTransferService._content_signature("comp-1", True, 1000.0, "DOP", "reg-src", "reg-dst"),
        "type": "TRANSFER_OUT", "shiftId": "shift-src", "registerId": "reg-src",
    })
    with pytest.raises(CashTransferError):
        _do_transfer(idempotency_key="transfer-key-partial", amount=1000.0)


# ---------------------------------------------------------------------------
# R3 — Almacenamiento y validación de TTL
# ---------------------------------------------------------------------------

def test_authorization_expires_at_stored_as_datetime(cash_env, monkeypatch):
    monkeypatch.setattr(DatabaseService, "validate_pos_supervisor_pin",
                        lambda *a, **k: {"valid": True, "name": "Sup", "email": "s@x"})
    CashAuthorizationService.authorize("owner", "comp-1", True, "u1", "u2", "1", "auth-dt",
                                       "CASH_OUT", 100.0, "DOP", "reg-1", "shift-1")
    rec = cash_env.collection("comp-1", "sandbox_cash_authorizations").document("auth-dt").get().to_dict()
    assert isinstance(rec["expiresAt"], datetime)
    assert isinstance(rec["createdAt"], datetime)
    assert rec["expiresAt"] > rec["createdAt"]


def test_authorization_malformed_expiry_rejected(cash_env, monkeypatch):
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _authorize(cash_env, monkeypatch, "auth-mal")
    ref = cash_env.collection("comp-1", "sandbox_cash_authorizations").document("auth-mal")
    ref.update({"expiresAt": "no-es-una-fecha"})
    with pytest.raises(CashAuthorizationError):
        DatabaseService.register_cash_transaction(
            "owner", {"shiftId": "shift-1", "type": "CASH_OUT", "amount": 100.0, "currency": "DOP", "reason": "x", "performedBy": "u1"},
            company_id="comp-1", sandbox=True, register_id="reg-1", shift_id="shift-1",
            auth_request_id="auth-mal", performer_uid="u1",
        )


def test_authorization_missing_expiry_rejected(cash_env, monkeypatch):
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _authorize(cash_env, monkeypatch, "auth-none")
    ref = cash_env.collection("comp-1", "sandbox_cash_authorizations").document("auth-none")
    stored = ref.get().to_dict()
    stored.pop("expiresAt")
    ref.set(stored)
    with pytest.raises(CashAuthorizationError):
        DatabaseService.register_cash_transaction(
            "owner", {"shiftId": "shift-1", "type": "CASH_OUT", "amount": 100.0, "currency": "DOP", "reason": "x", "performedBy": "u1"},
            company_id="comp-1", sandbox=True, register_id="reg-1", shift_id="shift-1",
            auth_request_id="auth-none", performer_uid="u1",
        )
