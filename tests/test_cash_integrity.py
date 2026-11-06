"""Pruebas de integridad transaccional del módulo de caja (Fase 1).

Usan un doble en memoria de Firestore (tests/cash_firestore_double.py) que imita
las primitivas atómicas que usa el código de producción: `create()` (falla si el
documento existe) y `transaction()` con control de concurrencia optimista.

NOTA: este doble no sustituye al emulador de Firestore; verifica la lógica de
guardas de nuestro código (ocupación, bloqueo venta/cierre, idempotencia con
lease) bajo concurrencia determinista. Para validación final en plataforma real,
ejecutar contra el emulador de Firestore (ver scripts/verify_cash_concurrency.md).
"""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.services import db_service
from app.services.db_service import (
    DatabaseService,
    CashRegisterOccupiedError,
    CashShiftLockError,
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


def _open_shift(register_id, user_id, opening_amount=0.0):
    return DatabaseService.open_cash_shift(
        "owner",
        {
            "registerId": register_id,
            "openedByUserId": user_id,
            "openedByUserEmail": f"{user_id}@x.com",
            "openingAmount": opening_amount,
        },
        company_id="comp-1",
        sandbox=True,
    )


# ---------------------------------------------------------------------------
# 1.1 Ocupación de caja física
# ---------------------------------------------------------------------------

def test_second_open_same_register_is_blocked(cash_env):
    r1 = _open_shift("reg-1", "user-1", 100.0)
    assert r1 and r1["id"]

    with pytest.raises(CashRegisterOccupiedError):
        _open_shift("reg-1", "user-2", 50.0)


def test_two_registers_open_independently(cash_env):
    assert _open_shift("reg-a", "user-1")
    assert _open_shift("reg-b", "user-2")


def test_concurrent_open_same_register_only_one_wins(cash_env):
    results = []
    errors = []

    def open_it(user):
        try:
            results.append(_open_shift("reg-1", user))
        except CashRegisterOccupiedError as e:
            errors.append(e)

    threads = [threading.Thread(target=open_it, args=(f"u{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1
    assert len(errors) == 1


def test_register_released_after_close(cash_env):
    _open_shift("reg-1", "user-1", 100.0)
    shift = DatabaseService.get_open_shift_by_register("owner", "reg-1", company_id="comp-1", sandbox=True)
    assert shift is not None and shift["registerId"] == "reg-1"

    # Cerrar libera el lock.
    seed_register = cash_env.collection("comp-1", "sandbox_cash_registers")
    seed_register.document("reg-1").set({"id": "reg-1", "status": "OPEN"})
    res = DatabaseService.close_cash_shift(
        "owner", shift["id"], 100.0, company_id="comp-1", sandbox=True,
        declared_data={"declaredCash": 100.0, "declaredCard": 0.0, "declaredTransfer": 0.0,
                       "declaredUSD": 0.0, "usdExchangeRate": 58.5, "cashDenominations": {}, "cardLoteNumber": ""},
    )
    assert res is not None

    # Ahora se puede reabrir.
    assert _open_shift("reg-1", "user-2")


# ---------------------------------------------------------------------------
# 1.2 Idempotencia
# ---------------------------------------------------------------------------

def test_reserve_idempotency_key_state_machine(cash_env):
    key = "sale-1"
    assert DatabaseService.reserve_idempotency_key("owner", key, company_id="comp-1", sandbox=True)["status"] == "RESERVED"
    assert DatabaseService.reserve_idempotency_key("owner", key, company_id="comp-1", sandbox=True)["status"] == "IN_PROGRESS"

    DatabaseService.complete_idempotency_key(
        "owner", key, {"response": {"ok": True}, "statusCode": 200, "invoiceId": "inv-1"},
        company_id="comp-1", sandbox=True,
    )
    res = DatabaseService.reserve_idempotency_key("owner", key, company_id="comp-1", sandbox=True)
    assert res["status"] == "COMPLETED"
    assert res["record"]["response"]["ok"] is True


def test_reserve_idempotency_failed_state(cash_env):
    key = "sale-fail"
    DatabaseService.reserve_idempotency_key("owner", key, company_id="comp-1", sandbox=True)
    DatabaseService.fail_idempotency_key("owner", key, "boom", company_id="comp-1", sandbox=True)
    res = DatabaseService.reserve_idempotency_key("owner", key, company_id="comp-1", sandbox=True)
    assert res["status"] == "FAILED"
    assert res["record"]["error"] == "boom"


def test_reserve_idempotency_recovers_expired_lease(cash_env):
    key = "sale-expired"
    coll = cash_env.collection("comp-1", "sandbox_idempotency_keys")
    coll.document(key).set({
        "id": key, "status": "PENDING", "leaseOwner": "old",
        "leaseExpiresAt": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
    })
    assert DatabaseService.reserve_idempotency_key("owner", key, company_id="comp-1", sandbox=True)["status"] == "RESERVED"


def test_register_cash_transaction_idempotent_by_key(cash_env):
    tx = {"shiftId": "s1", "type": "IN", "amount": 5.0}
    DatabaseService.register_cash_transaction("owner", dict(tx), company_id="comp-1", sandbox=True, idempotency_key="k1")
    DatabaseService.register_cash_transaction("owner", dict(tx), company_id="comp-1", sandbox=True, idempotency_key="k1")
    docs = cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("shiftId", "==", "s1")).get()
    assert len(docs) == 1


# ---------------------------------------------------------------------------
# 1.3 Cierre transaccional + bloqueo de venta
# ---------------------------------------------------------------------------

def _seed_lock(cash_env, register_id, shift_id, status):
    cash_env.collection("comp-1", "sandbox_cash_register_locks").document(register_id).set({
        "registerId": register_id, "shiftId": shift_id, "status": status,
        "openedByUserId": "user-1",
        "leaseExpiresAt": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
    })


def test_register_sale_cash_writes_when_active(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    txs = [
        {"id": "t1", "shiftId": "shift-1", "type": "SALE", "amount": 70.0, "paymentMethod": "Efectivo"},
        {"id": "t2", "shiftId": "shift-1", "type": "SALE", "amount": 48.0, "paymentMethod": "Tarjeta"},
    ]
    assert DatabaseService.register_sale_cash_transactions("owner", "reg-1", "shift-1", txs, company_id="comp-1", sandbox=True) is True
    docs = cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("shiftId", "==", "shift-1")).get()
    assert len(docs) == 2


def test_register_sale_cash_blocks_when_closing(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1", "CLOSING")
    txs = [{"id": "t1", "shiftId": "shift-1", "type": "SALE", "amount": 100.0, "paymentMethod": "Efectivo"}]
    with pytest.raises(CashShiftLockError):
        DatabaseService.register_sale_cash_transactions("owner", "reg-1", "shift-1", txs, company_id="comp-1", sandbox=True)
    docs = cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("shiftId", "==", "shift-1")).get()
    assert docs == []


def test_register_sale_cash_missing_lock_is_rejected(cash_env):
    """La ausencia de lock NO autoriza la operación una vez activado el mecanismo."""
    txs = [{"id": "t1", "shiftId": "shift-1", "type": "SALE", "amount": 100.0, "paymentMethod": "Efectivo"}]
    with pytest.raises(CashShiftLockError):
        DatabaseService.register_sale_cash_transactions("owner", "reg-1", "shift-1", txs, company_id="comp-1", sandbox=True)
    docs = cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("shiftId", "==", "shift-1")).get()
    assert docs == []


def _seed_close_scenario(cash_env):
    shift_id = "shift-1"
    register_id = "reg-1"
    cash_env.collection("comp-1", "sandbox_cash_shifts").document(shift_id).set({
        "id": shift_id, "registerId": register_id, "openingAmount": 100.0,
        "status": "OPEN", "openedByUserId": "user-1",
        "openingTime": datetime.now(timezone.utc).isoformat(),
    })
    cash_env.collection("comp-1", "sandbox_cash_registers").document(register_id).set({"id": register_id, "status": "OPEN"})
    _seed_lock(cash_env, register_id, shift_id, "ACTIVE")

    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    txs.document("t1").set({"id": "t1", "shiftId": shift_id, "type": "SALE", "amount": 118.0, "paymentMethod": "Efectivo"})
    txs.document("t2").set({"id": "t2", "shiftId": shift_id, "type": "SALE", "amount": 50.0, "paymentMethod": "Tarjeta"})

    inv = cash_env.collection("comp-1", "sandbox_invoices")
    inv.document("inv-individual").set({"id": "inv-individual", "posShiftId": shift_id, "status": "Consolidada",
                                        "ecfType": "Factura de Consumo (E32)", "total": 100.0, "totalITBIS": 15.0})
    inv.document("inv-consolidated").set({"id": "inv-consolidated", "posShiftId": shift_id, "status": "Cobrada",
                                          "ecfType": "Factura de Consumo (E32)", "total": 168.0, "totalITBIS": 18.0,
                                          "isConsolidado": True})
    return shift_id, register_id


def test_close_cash_shift_decimal_and_no_z_double_count(cash_env):
    shift_id, _ = _seed_close_scenario(cash_env)
    res = DatabaseService.close_cash_shift(
        "owner", shift_id, 268.0, company_id="comp-1", sandbox=True,
        declared_data={"declaredCash": 218.0, "declaredCard": 50.0, "declaredTransfer": 0.0,
                       "declaredUSD": 0.0, "usdExchangeRate": 58.5, "cashDenominations": {}, "cardLoteNumber": ""},
    )
    assert res is not None
    assert res["closingAmountExpected"] == 268.0
    assert res["difference"] == 0.0
    # Sin doble conteo: la individual "Consolidada" no se cuenta; solo el consolidado.
    assert res["fiscalSummary"]["E32"]["count"] == 1
    assert res["fiscalSummary"]["E32"]["total"] == 168.0


def test_close_cash_shift_detects_cash_shortage(cash_env):
    shift_id, _ = _seed_close_scenario(cash_env)
    res = DatabaseService.close_cash_shift(
        "owner", shift_id, 258.0, company_id="comp-1", sandbox=True,
        declared_data={"declaredCash": 208.0, "declaredCard": 50.0, "declaredTransfer": 0.0,
                       "declaredUSD": 0.0, "usdExchangeRate": 58.5, "cashDenominations": {}, "cardLoteNumber": ""},
    )
    assert res is not None
    assert res["difference"] == pytest.approx(-10.0)
    assert res["status"] == "PENDING_AUDIT"


def test_close_cash_shift_duplicate_is_idempotent(cash_env):
    shift_id, _ = _seed_close_scenario(cash_env)
    declared = {"declaredCash": 218.0, "declaredCard": 50.0, "declaredTransfer": 0.0,
                "declaredUSD": 0.0, "usdExchangeRate": 58.5, "cashDenominations": {}, "cardLoteNumber": ""}
    first = DatabaseService.close_cash_shift("owner", shift_id, 268.0, company_id="comp-1", sandbox=True, declared_data=declared)
    assert first is not None
    closing_time = first["closingTime"]

    second = DatabaseService.close_cash_shift("owner", shift_id, 999.0, company_id="comp-1", sandbox=True, declared_data=declared)
    assert second is not None
    # No se reescribe el cierre: el declarado original se mantiene.
    assert second["closingAmountDeclared"] == 268.0
    assert second["closingTime"] == closing_time


def test_manual_transaction_blocks_when_closing(cash_env):
    """Todas las operaciones de efectivo (no solo ventas) respetan el lock."""
    _seed_lock(cash_env, "reg-1", "shift-1", "CLOSING")
    tx = {"shiftId": "shift-1", "type": "OUT", "amount": 10.0}
    with pytest.raises(CashShiftLockError):
        DatabaseService.register_cash_transaction(
            "owner", tx, company_id="comp-1", sandbox=True,
            register_id="reg-1", shift_id="shift-1",
        )
    docs = cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("shiftId", "==", "shift-1")).get()
    assert docs == []


def test_manual_transaction_allows_when_active(cash_env):
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    tx = {"shiftId": "shift-1", "type": "IN", "amount": 10.0}
    assert DatabaseService.register_cash_transaction(
        "owner", tx, company_id="comp-1", sandbox=True,
        register_id="reg-1", shift_id="shift-1",
    )
    docs = cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("shiftId", "==", "shift-1")).get()
    assert len(docs) == 1


def test_complete_idempotency_rejects_stale_owner(cash_env):
    """Un proceso cuyo lease fue recuperado no puede confirmar la operación."""
    key = "sale-stale"
    r1 = DatabaseService.reserve_idempotency_key("owner", key, company_id="comp-1", sandbox=True)
    owner1 = r1["record"]["leaseOwner"]
    # Otro proceso toma el control (lease vencido).
    ref = cash_env.collection("comp-1", "sandbox_idempotency_keys").document(key)
    ref.update({"leaseOwner": "owner-2"})

    ok = DatabaseService.complete_idempotency_key(
        "owner", key, {"response": {"ok": 1}, "statusCode": 200, "invoiceId": "x"},
        company_id="comp-1", sandbox=True, lease_owner=owner1,
    )
    assert ok is False
    stored = ref.get().to_dict()
    assert stored["status"] == "PENDING"
    assert "response" not in stored


def test_sale_conflicts_with_concurrent_close_and_aborts(cash_env):
    """Un cierre concurrente (escritura CLOSING) hace abortar la venta tras el reintento."""
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")

    def inject_close(store):
        store.collection("comp-1", "sandbox_cash_register_locks").document("reg-1").update({"status": "CLOSING"})

    cash_env.before_commit_hook = inject_close
    txs = [{"id": "t1", "shiftId": "shift-1", "type": "SALE", "amount": 100.0, "paymentMethod": "Efectivo"}]
    with pytest.raises(CashShiftLockError):
        DatabaseService.register_sale_cash_transactions("owner", "reg-1", "shift-1", txs, company_id="comp-1", sandbox=True)
    docs = cash_env.collection("comp-1", "sandbox_cash_transactions").where(filter=FieldFilter("shiftId", "==", "shift-1")).get()
    assert docs == []
