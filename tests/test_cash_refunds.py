"""Pruebas de Fase 3 — devoluciones y reembolsos del POS (integridad y recuperación)."""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.services import db_service
from app.services.db_service import DatabaseService, CashShiftLockError
from app.services.cash_refund_service import (
    CashRefundService,
    CashRefundError,
    REFUND_STATUS_RESERVED,
    REFUND_STATUS_COMPLETED,
    REFUND_STATUS_FAILED,
    NC_ACCEPTED,
    NC_PENDING_DGII,
    NC_REJECTED,
    NC_RECONCILING,
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
        "openedByUserId": "user-1",
        "leaseExpiresAt": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
    })


def _seed_invoice(cash_env, inv_id="inv-1", quantity=2.0, returned=0.0):
    cash_env.collection("comp-1", "sandbox_invoices").document(inv_id).set({
        "id": inv_id, "invoiceNumber": "POS-0001", "encf": "E320000000001",
        "items": [
            {"id": "prod-1", "itemId": "prod-1", "catalogId": "prod-1", "name": "Producto",
             "type": "Bien", "price": 100.0, "quantity": quantity, "itbisRate": 0.18,
             "subtotal": 100.0 * quantity, "itbisAmount": 18.0 * quantity,
             "total": 118.0 * quantity, "returnedQty": returned, "originalCost": 50.0},
        ],
    })


OPEN_SHIFT = {"id": "shift-1", "registerId": "reg-1", "status": "OPEN"}


def _mock_profile(monkeypatch):
    monkeypatch.setattr(DatabaseService, "get_company_profile",
                        lambda owner_uid, company_id=None: {"companyName": "Demo", "tradeName": "Demo SRL", "companyRNC": "131880681"})


def _mock_emission(monkeypatch, side_effect):
    from app.services import ecf_emission
    monkeypatch.setattr(ecf_emission.EcfEmissionService, "emit_electronic_comprobante", side_effect)


def _mock_save(monkeypatch, saved):
    monkeypatch.setattr(DatabaseService, "save_invoice", lambda o, i, d, **k: saved.append((i, dict(d))))


def _reserve(cash_env, inv_id="inv-1", items=None, key="k1", method="Efectivo", amount=None, currency="DOP"):
    items = items or [{"itemId": "prod-1", "quantity": 1.0}]
    return CashRefundService.reserve_refund(
        "owner", "comp-1", True, inv_id, method, items,
        performed_by="Cajero", performed_by_uid="u1",
        authorized_by="Sup", authorized_by_uid="u2", authorized_at="",
        refund_amount=amount, currency=currency, idempotency_key=key,
    )


# ---------------------------------------------------------------------------
# Reserva y returnedQty (Fase 3)
# ---------------------------------------------------------------------------

def test_reserve_updates_returned_qty(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, items=[{"itemId": "prod-1", "quantity": 1.0}])
    assert result["already"] is False
    assert result["refund"]["status"] == REFUND_STATUS_RESERVED
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 1.0


def test_refund_cannot_exceed_sold_qty(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    with pytest.raises(CashRefundError):
        _reserve(cash_env, items=[{"itemId": "prod-1", "quantity": 3.0}])


def test_partial_then_second_partial_then_fully_returned(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    _reserve(cash_env, key="k2", items=[{"itemId": "prod-1", "quantity": 1.0}])
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k3", items=[{"itemId": "prod-1", "quantity": 1.0}])


def test_concurrent_refunds_same_units_only_one_wins(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    errors = []
    results = []

    def do(key):
        try:
            results.append(_reserve(cash_env, key=key, items=[{"itemId": "prod-1", "quantity": 2.0}]))
        except CashRefundError as e:
            errors.append(e)

    threads = [threading.Thread(target=do, args=(f"k{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1
    assert len(errors) == 1
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 2.0


def test_retry_same_key_is_idempotent(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    r1 = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    r2 = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    assert r1["already"] is False
    assert r2["already"] is True
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 1.0


# ---------------------------------------------------------------------------
# R2 — Firma de idempotencia completa
# ---------------------------------------------------------------------------

def test_reuse_key_with_different_items_rejected(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 2.0}])


def test_reuse_key_with_different_amount_rejected(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    _reserve(cash_env, key="k1", amount=118.0, items=[{"itemId": "prod-1", "quantity": 1.0}])
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k1", amount=200.0, items=[{"itemId": "prod-1", "quantity": 1.0}])


def test_reuse_key_with_different_currency_rejected(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    _reserve(cash_env, key="k1", currency="DOP", items=[{"itemId": "prod-1", "quantity": 1.0}])
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k1", currency="USD", items=[{"itemId": "prod-1", "quantity": 1.0}])


def test_refund_amount_exceeding_nc_rejected(cash_env):
    _seed_invoice(cash_env, quantity=1.0)
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k1", amount=999.0, items=[{"itemId": "prod-1", "quantity": 1.0}])


# ---------------------------------------------------------------------------
# Flujo completo con estados de NC (R1)
# ---------------------------------------------------------------------------

def _process(cash_env, monkeypatch, emission, key="rf1", allow_pending=False, refund_method="Efectivo"):
    saved = []
    _seed_invoice(cash_env, quantity=2.0)
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _mock_profile(monkeypatch)
    _mock_save(monkeypatch, saved)
    _mock_emission(monkeypatch, emission)
    return CashRefundService.process_refund(
        "owner", "comp-1", True, invoice_id="inv-1",
        items=[{"itemId": "prod-1", "quantity": 1.0}], refund_method=refund_method,
        open_shift=OPEN_SHIFT, performed_by="Cajero", performed_by_uid="u1",
        authorized_by="Sup", authorized_by_uid="u2", authorized_at="",
        currency="DOP", refund_amount=118.0, idempotency_key=key,
        allow_pending_refund=allow_pending,
    ), saved


def test_e34_accepted_allows_refund(cash_env, monkeypatch):
    refund, saved = _process(cash_env, monkeypatch,
                             lambda company, inv, sandbox=True: {"success": True, "encf": "E340000000001", "mode": "API", "status": "ACCEPTED", "trackId": "tr-1"})
    assert refund["status"] == REFUND_STATUS_COMPLETED
    assert refund["ncStatus"] == NC_ACCEPTED


def test_e34_rejected_blocks_refund(cash_env, monkeypatch):
    with pytest.raises(CashRefundError):
        _process(cash_env, monkeypatch,
                 lambda company, inv, sandbox=True: {"success": False, "message": "Rechazado"})
    # Sin reembolso registrado.
    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    assert [d.to_dict() for d in txs.where(filter=FieldFilter("type", "==", "REFUND")).get()] == []


def test_e34_pending_blocks_refund_by_default(cash_env, monkeypatch):
    with pytest.raises(CashRefundError):
        _process(cash_env, monkeypatch,
                 lambda company, inv, sandbox=True: {"success": True, "mode": "FALLBACK", "status": "PENDING", "trackId": "tr-1"})


def test_e34_pending_allows_refund_with_authorized_contingency(cash_env, monkeypatch):
    refund, saved = _process(cash_env, monkeypatch,
                             lambda company, inv, sandbox=True: {"success": True, "mode": "FALLBACK", "status": "PENDING", "trackId": "tr-1"},
                             allow_pending=True)
    assert refund["status"] == REFUND_STATUS_COMPLETED
    assert refund["ncStatus"] == NC_PENDING_DGII


def test_e34_timeout_marks_reconciling_and_blocks(cash_env, monkeypatch):
    def _timeout(*a, **k):
        raise Exception("timeout")
    with pytest.raises(CashRefundError):
        _process(cash_env, monkeypatch, _timeout)
    refund_doc = CashRefundService._derive_refund_id("comp-1", True, "rf1")
    stored = cash_env.collection("comp-1", "sandbox_cash_refunds").document(refund_doc).get().to_dict()
    assert stored["ncStatus"] == NC_RECONCILING


# ---------------------------------------------------------------------------
# R3 — Reconciliación de emisión ambigua
# ---------------------------------------------------------------------------

def test_reconcile_by_track_id_accepted(cash_env, monkeypatch):
    from app.services import dgii_direct
    refund_doc = CashRefundService._derive_refund_id("comp-1", True, "rf-rec")
    cash_env.collection("comp-1", "sandbox_cash_refunds").document(refund_doc).set({
        "id": refund_doc, "trackId": "tr-9", "ncStatus": NC_RECONCILING, "syncAttempts": 0,
    })
    _mock_profile(monkeypatch)
    monkeypatch.setattr(dgii_direct.DgiiDirectService, "check_status",
                        lambda company, track_id, sandbox=True: {"success": True, "dgiiStatus": "ACEPTADO", "eNCF": "E340000000099"})
    refund = {"id": refund_doc, "trackId": "tr-9", "ncStatus": NC_RECONCILING, "syncAttempts": 0}
    refund = CashRefundService.reconcile_credit_note("owner", "comp-1", True, refund)
    assert refund["ncStatus"] == NC_ACCEPTED
    assert refund["creditNoteEncNcf"] == "E340000000099"


def test_reconcile_ambiguous_keeps_reconciling(cash_env, monkeypatch):
    from app.services import dgii_direct
    refund_doc = CashRefundService._derive_refund_id("comp-1", True, "rf-rec2")
    _mock_profile(monkeypatch)
    monkeypatch.setattr(dgii_direct.DgiiDirectService, "check_status",
                        lambda company, track_id, sandbox=True: {"success": True, "dgiiStatus": "PENDING"})
    refund = {"id": refund_doc, "trackId": "tr-9", "ncStatus": NC_RECONCILING, "syncAttempts": 0}
    refund = CashRefundService.reconcile_credit_note("owner", "comp-1", True, refund)
    assert refund["ncStatus"] == NC_PENDING_DGII  # no concluyente → no reemisión


def test_reconcile_by_encf_accepted(cash_env, monkeypatch):
    from app.services import dgii_direct
    _mock_profile(monkeypatch)
    monkeypatch.setattr(dgii_direct.DgiiDirectService, "consultar_estado_ecf",
                        lambda company, rnc, encf, sandbox=True: {"success": True, "responseBody": {"estado": "ACEPTADO"}})
    refund = {"id": "rf-encf", "creditNoteEncNcf": "E340000000099", "ncStatus": NC_RECONCILING, "syncAttempts": 0}
    refund = CashRefundService.reconcile_credit_note("owner", "comp-1", True, refund)
    assert refund["ncStatus"] == NC_ACCEPTED


def test_reconcile_by_encf_pending_stays_pending(cash_env, monkeypatch):
    from app.services import dgii_direct
    _mock_profile(monkeypatch)
    monkeypatch.setattr(dgii_direct.DgiiDirectService, "consultar_estado_ecf",
                        lambda company, rnc, encf, sandbox=True: {"success": True, "responseBody": {"estado": "PENDIENTE"}})
    refund = {"id": "rf-encf2", "creditNoteEncNcf": "E340000000099", "ncStatus": NC_RECONCILING, "syncAttempts": 0}
    refund = CashRefundService.reconcile_credit_note("owner", "comp-1", True, refund)
    assert refund["ncStatus"] == NC_PENDING_DGII  # pendiente → no aceptada


# ---------------------------------------------------------------------------
# R4 — Recuperación cuando la NC se guardó pero no se persistió creditNoteId
# ---------------------------------------------------------------------------

def test_recovery_finds_existing_nc_without_reemit(cash_env, monkeypatch):
    from app.services import ecf_emission, dgii_direct
    _seed_invoice(cash_env, quantity=2.0)
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _mock_profile(monkeypatch)
    saved = []
    _mock_save(monkeypatch, saved)

    # Simular que la NC ya fue emitida (existe con encf + emissionAttempted).
    refund_id = CashRefundService._derive_refund_id("comp-1", True, "rf-recovery")
    nc_id = f"nc-{refund_id}"
    cash_env.collection("comp-1", "sandbox_invoices").document(nc_id).set({
        "id": nc_id, "ecfType": "Nota de Crédito (E34)", "status": "Emitida",
        "encf": "E340000000088", "trackId": "tr-88", "emissionAttempted": True,
    })

    called = []
    monkeypatch.setattr(ecf_emission.EcfEmissionService, "emit_electronic_comprobante",
                        lambda *a, **k: called.append(1) or {"success": True, "encf": "E340000000088"})
    # R1: la recuperación ahora reconcilia por e-NCF (no infiere aceptación).
    monkeypatch.setattr(dgii_direct.DgiiDirectService, "consultar_estado_ecf",
                        lambda company, rnc, encf, sandbox=True: {"success": True, "responseBody": {"estado": "ACEPTADO"}})

    refund = CashRefundService.process_refund(
        "owner", "comp-1", True, invoice_id="inv-1",
        items=[{"itemId": "prod-1", "quantity": 1.0}], refund_method="Efectivo",
        open_shift=OPEN_SHIFT, performed_by="Cajero", performed_by_uid="u1",
        authorized_by="Sup", authorized_by_uid="u2", authorized_at="",
        currency="DOP", refund_amount=118.0, idempotency_key="rf-recovery",
    )
    assert refund["status"] == REFUND_STATUS_COMPLETED
    assert refund["creditNoteEncNcf"] == "E340000000088"
    assert called == []  # no se reemitió


# ---------------------------------------------------------------------------
# Conciliación por canal del reembolso
# ---------------------------------------------------------------------------

def _seed_close_scenario(cash_env, refund_method):
    shift_id = "shift-1"
    reg = "reg-1"
    cash_env.collection("comp-1", "sandbox_cash_shifts").document(shift_id).set({
        "id": shift_id, "registerId": reg, "openingAmount": 0.0, "status": "OPEN",
        "openingTime": "2026-01-01T00:00:00+00:00",
    })
    cash_env.collection("comp-1", "sandbox_cash_registers").document(reg).set({"id": reg, "status": "OPEN"})
    _seed_lock(cash_env, reg, shift_id, "ACTIVE")
    txs = cash_env.collection("comp-1", "sandbox_cash_transactions")
    txs.document("t-sale").set({"id": "t-sale", "shiftId": shift_id, "type": "SALE",
                                "amount": 100.0, "paymentMethod": "Efectivo", "currency": "DOP"})
    txs.document("t-refund").set({"id": "t-refund", "shiftId": shift_id, "type": "REFUND",
                                  "amount": 50.0, "paymentMethod": refund_method, "currency": "DOP"})
    return shift_id


def test_card_refund_does_not_decrease_expected_cash(cash_env):
    shift_id = _seed_close_scenario(cash_env, "Tarjeta")
    res = DatabaseService.close_cash_shift(
        "owner", shift_id, 50.0, company_id="comp-1", sandbox=True,
        declared_data={"declaredCash": 100.0, "declaredCard": -50.0, "declaredTransfer": 0.0,
                       "declaredUSD": 0.0, "usdExchangeRate": 58.5, "cashDenominations": {}, "cardLoteNumber": ""},
    )
    assert res["expectedCash"] == 100.0
    assert res["expectedCard"] == -50.0


def test_cash_refund_decreases_expected_cash(cash_env):
    shift_id = _seed_close_scenario(cash_env, "Efectivo")
    res = DatabaseService.close_cash_shift(
        "owner", shift_id, 50.0, company_id="comp-1", sandbox=True,
        declared_data={"declaredCash": 50.0, "declaredCard": 0.0, "declaredTransfer": 0.0,
                       "declaredUSD": 0.0, "usdExchangeRate": 58.5, "cashDenominations": {}, "cardLoteNumber": ""},
    )
    assert res["expectedCash"] == 50.0


# ---------------------------------------------------------------------------
# Separación E34 ↔ inventario (la NC se guarda Borrador, reingresa solo al aceptar)
# ---------------------------------------------------------------------------

def test_inventory_reentry_only_on_accepted(cash_env, monkeypatch):
    saved = []
    _seed_invoice(cash_env, quantity=2.0)
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _mock_profile(monkeypatch)
    _mock_save(monkeypatch, saved)
    _mock_emission(monkeypatch, lambda company, inv, sandbox=True: {"success": True, "encf": "E340000000001", "mode": "API", "status": "ACCEPTED", "trackId": "tr-1"})

    refund = CashRefundService.process_refund(
        "owner", "comp-1", True, invoice_id="inv-1",
        items=[{"itemId": "prod-1", "quantity": 1.0}], refund_method="Efectivo",
        open_shift=OPEN_SHIFT, performed_by="Cajero", performed_by_uid="u1",
        authorized_by="Sup", authorized_by_uid="u2", authorized_at="",
        currency="DOP", refund_amount=118.0, idempotency_key="rf-inv",
    )
    assert refund["status"] == REFUND_STATUS_COMPLETED
    nc_saves = [d for i, d in saved if d.get("ecfType") == "Nota de Crédito (E34)"]
    assert nc_saves[0]["status"] == "Borrador"   # no reingreso aún
    assert nc_saves[-1]["status"] == "Emitida"   # reingreso solo al aceptar


def test_inventory_not_reentered_on_rejected(cash_env, monkeypatch):
    saved = []
    _seed_invoice(cash_env, quantity=2.0)
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _mock_profile(monkeypatch)
    _mock_save(monkeypatch, saved)
    _mock_emission(monkeypatch, lambda company, inv, sandbox=True: {"success": False, "message": "Rechazado"})

    with pytest.raises(CashRefundError):
        CashRefundService.process_refund(
            "owner", "comp-1", True, invoice_id="inv-1",
            items=[{"itemId": "prod-1", "quantity": 1.0}], refund_method="Efectivo",
            open_shift=OPEN_SHIFT, performed_by="Cajero", performed_by_uid="u1",
            authorized_by="Sup", authorized_by_uid="u2", authorized_at="",
            currency="DOP", refund_amount=118.0, idempotency_key="rf-rej",
        )
    nc_saves = [d for i, d in saved if d.get("ecfType") == "Nota de Crédito (E34)"]
    assert nc_saves[0]["status"] == "Borrador"
    assert all(d["status"] != "Emitida" for d in nc_saves)  # sin reingreso de inventario


# ---------------------------------------------------------------------------
# Resolución manual de NC_RECONCILING (supervisor)
# ---------------------------------------------------------------------------

def test_resolve_reconciling_abandon_releases_qty(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refund_id = result["refund"]["id"]
    refund = CashRefundService.resolve_reconciling("owner", "comp-1", True, refund_id, "abandon", "duplicada", "Sup")
    assert refund["status"] == REFUND_STATUS_FAILED
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 0.0  # liberada


def test_resolve_reconciling_reemit_clears_markers(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refund_id = result["refund"]["id"]
    # Simular que quedó en NC_RECONCILING SIN evidencia de emisión (sin trackId/encf).
    refunds_coll = cash_env.collection("comp-1", "sandbox_cash_refunds")
    stored = refunds_coll.document(refund_id).get().to_dict()
    stored["ncStatus"] = NC_RECONCILING
    refunds_coll.document(refund_id).set(stored)

    refund = CashRefundService.resolve_reconciling("owner", "comp-1", True, refund_id, "reemit", "reintentar", "Sup")
    assert refund["status"] == REFUND_STATUS_RESERVED
    assert refund["creditNoteId"] == ""


def test_resolve_reemit_rejected_with_trackid(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refund_id = result["refund"]["id"]
    refunds_coll = cash_env.collection("comp-1", "sandbox_cash_refunds")
    stored = refunds_coll.document(refund_id).get().to_dict()
    stored["ncStatus"] = NC_RECONCILING
    stored["trackId"] = "tr-9"  # evidencia de emisión sin reconciliar
    refunds_coll.document(refund_id).set(stored)

    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, refund_id, "reemit", "x", "Sup")


def test_resolve_abandon_rejects_with_emission_evidence(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refund_id = result["refund"]["id"]
    refunds_coll = cash_env.collection("comp-1", "sandbox_cash_refunds")
    stored = refunds_coll.document(refund_id).get().to_dict()
    stored["ncStatus"] = NC_PENDING_DGII  # evidencia de emisión pendiente
    refunds_coll.document(refund_id).set(stored)

    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, refund_id, "abandon", "x", "Sup")


def test_resolve_concurrent_single_winner(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refund_id = result["refund"]["id"]
    results = []
    errors = []

    def do(resolution):
        try:
            results.append(CashRefundService.resolve_reconciling("owner", "comp-1", True, refund_id, resolution, "x", "Sup"))
        except CashRefundError as e:
            errors.append(e)

    threads = [threading.Thread(target=do, args=("abandon",)), threading.Thread(target=do, args=("reemit",))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Política de reembolso (config de empresa, no del frontend)
# ---------------------------------------------------------------------------

def test_refund_policy_defaults_blocked(cash_env):
    assert DatabaseService.get_pos_refund_policy("owner", "comp-1") == {"allowPendingRefund": False}


# ---------------------------------------------------------------------------
# R1 — e-NCF asignado pero NO aceptado no habilita reembolso ni inventario
# ---------------------------------------------------------------------------

def test_encf_assigned_but_not_accepted_blocks(cash_env, monkeypatch):
    saved = []
    _seed_invoice(cash_env, quantity=2.0)
    _seed_lock(cash_env, "reg-1", "shift-1", "ACTIVE")
    _mock_profile(monkeypatch)
    _mock_save(monkeypatch, saved)
    # encf devuelto pero estado PENDING → NO es aceptación concluyente.
    _mock_emission(monkeypatch, lambda company, inv, sandbox=True: {"success": True, "encf": "E340000000001", "mode": "FALLBACK", "status": "PENDING", "trackId": "tr-1"})

    with pytest.raises(CashRefundError):
        CashRefundService.process_refund(
            "owner", "comp-1", True, invoice_id="inv-1",
            items=[{"itemId": "prod-1", "quantity": 1.0}], refund_method="Efectivo",
            open_shift=OPEN_SHIFT, performed_by="Cajero", performed_by_uid="u1",
            authorized_by="Sup", authorized_by_uid="u2", authorized_at="",
            currency="DOP", refund_amount=118.0, idempotency_key="rf-encf-pending",
        )
    nc_saves = [d for i, d in saved if d.get("ecfType") == "Nota de Crédito (E34)"]
    assert all(d["status"] != "Emitida" for d in nc_saves)  # sin reingreso de inventario


# ---------------------------------------------------------------------------
# R2 — reemit protegido
# ---------------------------------------------------------------------------

def test_resolve_reemit_rejected_with_encf(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refund_id = result["refund"]["id"]
    refunds_coll = cash_env.collection("comp-1", "sandbox_cash_refunds")
    stored = refunds_coll.document(refund_id).get().to_dict()
    stored["ncStatus"] = NC_RECONCILING
    stored["creditNoteEncNcf"] = "E340000000001"  # e-NCF sin confirmar
    refunds_coll.document(refund_id).set(stored)

    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, refund_id, "reemit", "x", "Sup")


# ---------------------------------------------------------------------------
# R3 — abandon endurecido
# ---------------------------------------------------------------------------

def _seed_refund_doc(cash_env, refund_id="rf-x", invoice_id="inv-1", items=None):
    cash_env.collection("comp-1", "sandbox_cash_refunds").document(refund_id).set({
        "id": refund_id, "invoiceId": invoice_id, "status": REFUND_STATUS_RESERVED,
        "ncStatus": NC_RECONCILING, "items": items or [{"itemId": "prod-1", "quantity": 1.0}],
    })


def test_resolve_abandon_nonexistent_invoice(cash_env):
    _seed_refund_doc(cash_env, refund_id="rf-1", invoice_id="inv-missing")
    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-1", "abandon", "x", "Sup")


def test_resolve_abandon_nonexistent_line(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    _seed_refund_doc(cash_env, refund_id="rf-2", invoice_id="inv-1", items=[{"itemId": "prod-desconocido", "quantity": 1.0}])
    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-2", "abandon", "x", "Sup")


def test_resolve_abandon_insufficient_returned_qty(cash_env):
    _seed_invoice(cash_env, quantity=2.0, returned=0.0)  # returnedQty = 0
    _seed_refund_doc(cash_env, refund_id="rf-3", invoice_id="inv-1", items=[{"itemId": "prod-1", "quantity": 2.0}])
    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-3", "abandon", "x", "Sup")
    # No se modificó el inventario.
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 0.0


def test_resolve_abandon_releases_exactly_once(cash_env):
    _seed_invoice(cash_env, quantity=2.0, returned=1.0)
    _seed_refund_doc(cash_env, refund_id="rf-4", invoice_id="inv-1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-4", "abandon", "x", "Sup", resolution_key="rk-1")
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 0.0
    # Reintento idempotente con la misma key: no libera de nuevo (retorna existente).
    again = CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-4", "abandon", "x", "Sup", resolution_key="rk-1")
    assert again["status"] == REFUND_STATUS_FAILED
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 0.0


# ---------------------------------------------------------------------------
# R4 — múltiples ciclos de resolución con trazabilidad
# ---------------------------------------------------------------------------

def test_multiple_resolution_cycles_preserve_history(cash_env):
    _seed_invoice(cash_env, quantity=2.0, returned=1.0)
    _seed_refund_doc(cash_env, refund_id="rf-5", invoice_id="inv-1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-5", "reemit", "primer intento", "Sup", resolution_key="rk-a")
    # Vuelve a quedar ambigua tras un nuevo intento.
    refunds_coll = cash_env.collection("comp-1", "sandbox_cash_refunds")
    stored = refunds_coll.document("rf-5").get().to_dict()
    stored["ncStatus"] = NC_RECONCILING
    refunds_coll.document("rf-5").set(stored)
    refund = CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-5", "abandon", "segundo", "Sup", resolution_key="rk-b")
    assert len(refund["resolutionHistory"]) == 2
    assert refund["resolutionAttempts"] == 2


# ---------------------------------------------------------------------------
# R5 — defensa de inventario en CreditNoteInventoryService
# ---------------------------------------------------------------------------

def test_credit_note_inventory_fiscal_acceptance_gate():
    from app.services.credit_note_inventory_service import CreditNoteInventoryService
    assert CreditNoteInventoryService._is_fiscally_accepted({"ncStatus": "NC_ACCEPTED"}) is True
    assert CreditNoteInventoryService._is_fiscally_accepted({"isSyncedWithDGII": True}) is True
    assert CreditNoteInventoryService._is_fiscally_accepted({"dgiiStatus": "ACCEPTED"}) is True
    assert CreditNoteInventoryService._is_fiscally_accepted({"status": "Emitida", "encf": "E340..."}) is True  # legacy aceptado
    assert CreditNoteInventoryService._is_fiscally_accepted({"status": "Pendiente DGII"}) is False
    assert CreditNoteInventoryService._is_fiscally_accepted({"status": "Rechazado DGII"}) is False
    assert CreditNoteInventoryService._is_fiscally_accepted({"status": "Borrador"}) is False
    assert CreditNoteInventoryService._is_fiscally_accepted({"ncStatus": "NC_RECONCILING"}) is False
    assert CreditNoteInventoryService._is_fiscally_accepted({"ncStatus": "NC_PENDING_DGII"}) is False
    assert CreditNoteInventoryService._is_fiscally_accepted({"dgiiStatus": "REJECTED"}) is False


def test_credit_note_inventory_skips_non_accepted(cash_env, monkeypatch):
    from app.services.credit_note_inventory_service import CreditNoteInventoryService
    called = []
    monkeypatch.setattr("app.services.credit_note_inventory_service.InventoryTransactionService.execute_transaction",
                        lambda **k: called.append(k) or {})
    monkeypatch.setattr(DatabaseService, "get_items", lambda *a, **k: [{"id": "prod-1", "name": "P", "costPrice": 10.0}])
    monkeypatch.setattr(DatabaseService, "get_default_warehouse", lambda *a, **k: "wh-1")
    doc = {
        "ecfType": "Nota de Crédito (E34)", "status": "Pendiente DGII",
        "items": [{"id": "prod-1", "itemId": "prod-1", "type": "Bien", "quantity": 1.0, "reingresoStock": True}],
        "referenceInvoiceId": "inv-1",
    }
    assert CreditNoteInventoryService.process_credit_note_stock_reentry("owner", "comp-1", doc, sandbox=True) == []
    assert called == []


# ---------------------------------------------------------------------------
# R2 — reemit/abandon bloqueados por evidencia en el documento NC
# ---------------------------------------------------------------------------

def test_resolve_reemit_blocked_with_emission_attempted(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refund_id = result["refund"]["id"]
    # NC con emissionAttempted=True pero SIN trackId/encf (crash antes del POST).
    cash_env.collection("comp-1", "sandbox_invoices").document(f"nc-{refund_id}").set({
        "id": f"nc-{refund_id}", "ecfType": "Nota de Crédito (E34)", "status": "Borrador", "emissionAttempted": True,
    })
    refunds_coll = cash_env.collection("comp-1", "sandbox_cash_refunds")
    stored = refunds_coll.document(refund_id).get().to_dict()
    stored["ncStatus"] = NC_RECONCILING
    refunds_coll.document(refund_id).set(stored)

    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, refund_id, "reemit", "evidencia", "Sup")


def test_resolve_abandon_blocked_with_ambiguous_nc(cash_env):
    _seed_invoice(cash_env, quantity=2.0, returned=1.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refund_id = result["refund"]["id"]
    # NC con emissionAttempted (evidencia ambigua), aunque el refund no tenga creditNoteId.
    cash_env.collection("comp-1", "sandbox_invoices").document(f"nc-{refund_id}").set({
        "id": f"nc-{refund_id}", "ecfType": "Nota de Crédito (E34)", "status": "Borrador", "emissionAttempted": True,
    })
    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, refund_id, "abandon", "evidencia", "Sup")


# ---------------------------------------------------------------------------
# R3 — cantidades fraccionarias con Decimal
# ---------------------------------------------------------------------------

def test_fractional_quantities_precision(cash_env):
    _seed_invoice(cash_env, quantity=2.0)
    result = _reserve(cash_env, key="k1", items=[{"itemId": "prod-1", "quantity": 1.125}])
    assert result["refund"]["items"][0]["quantity"] == 1.125
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 1.125


# ---------------------------------------------------------------------------
# R5 — error técnico NO es rechazo fiscal
# ---------------------------------------------------------------------------

def test_timeout_classified_reconciling_not_rejected():
    assert CashRefundService._classify_emission({"success": False, "message": "timeout de red"})[0] == NC_RECONCILING
    assert CashRefundService._classify_emission({"success": False, "message": "Error de conexión"})[0] == NC_RECONCILING
    assert CashRefundService._classify_emission({"success": False, "message": "Rechazado por DGII"})[0] == NC_REJECTED


# ---------------------------------------------------------------------------
# R6 — validación de importe de reembolso
# ---------------------------------------------------------------------------

def test_refund_amount_must_be_positive_and_match(cash_env):
    _seed_invoice(cash_env, quantity=1.0)  # total = 118.0
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k1", amount=-10.0, items=[{"itemId": "prod-1", "quantity": 1.0}])
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k2", amount=0.0, items=[{"itemId": "prod-1", "quantity": 1.0}])
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k3", amount=50.0, items=[{"itemId": "prod-1", "quantity": 1.0}])


def test_refund_amount_one_cent_difference_rejected(cash_env):
    _seed_invoice(cash_env, quantity=1.0)  # total = 118.0
    with pytest.raises(CashRefundError):
        _reserve(cash_env, key="k1", amount=117.99, items=[{"itemId": "prod-1", "quantity": 1.0}])


# ---------------------------------------------------------------------------
# R2 — evidencia de emisión en el documento refund (no solo en la NC)
# ---------------------------------------------------------------------------

def test_resolve_blocked_with_refund_emission_attempted(cash_env):
    _seed_invoice(cash_env, quantity=2.0, returned=1.0)
    _seed_refund_doc(cash_env, refund_id="rf-a", invoice_id="inv-1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refunds_coll = cash_env.collection("comp-1", "sandbox_cash_refunds")
    stored = refunds_coll.document("rf-a").get().to_dict()
    stored["emissionAttempted"] = True
    refunds_coll.document("rf-a").set(stored)
    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-a", "reemit", "evidencia", "Sup")
    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-a", "abandon", "evidencia", "Sup")


def test_resolve_blocked_with_refund_emission_completed(cash_env):
    _seed_invoice(cash_env, quantity=2.0, returned=1.0)
    _seed_refund_doc(cash_env, refund_id="rf-b", invoice_id="inv-1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    refunds_coll = cash_env.collection("comp-1", "sandbox_cash_refunds")
    stored = refunds_coll.document("rf-b").get().to_dict()
    stored["emissionCompleted"] = True
    refunds_coll.document("rf-b").set(stored)
    with pytest.raises(CashRefundError):
        CashRefundService.resolve_reconciling("owner", "comp-1", True, "rf-b", "reemit", "evidencia", "Sup")


# ---------------------------------------------------------------------------
# R1/R5 — consulta DGII ambigua nunca produce aceptación
# ---------------------------------------------------------------------------

def test_reconcile_failed_query_with_acceptance_looking_body(cash_env, monkeypatch):
    from app.services import dgii_direct
    _mock_profile(monkeypatch)
    monkeypatch.setattr(dgii_direct.DgiiDirectService, "consultar_estado_ecf",
                        lambda company, rnc, encf, sandbox=True: {"success": False, "responseBody": {"estado": "ACEPTADO"}})
    refund = {"id": "rf-x", "creditNoteEncNcf": "E340000000099", "ncStatus": NC_RECONCILING, "syncAttempts": 0}
    refund = CashRefundService.reconcile_credit_note("owner", "comp-1", True, refund)
    assert refund["ncStatus"] == NC_RECONCILING  # fallo de consulta → nunca aceptación


def test_reconcile_no_conclusive_status(cash_env, monkeypatch):
    from app.services import dgii_direct
    _mock_profile(monkeypatch)
    monkeypatch.setattr(dgii_direct.DgiiDirectService, "check_status",
                        lambda company, track_id, sandbox=True: {"success": True, "dgiiStatus": ""})
    refund = {"id": "rf-y", "trackId": "tr-1", "ncStatus": NC_RECONCILING, "syncAttempts": 0}
    refund = CashRefundService.reconcile_credit_note("owner", "comp-1", True, refund)
    assert refund["ncStatus"] == NC_RECONCILING


# ---------------------------------------------------------------------------
# R5 — estado desconocido bloquea reingreso
# ---------------------------------------------------------------------------

def test_credit_note_unknown_status_blocked():
    from app.services.credit_note_inventory_service import CreditNoteInventoryService
    assert CreditNoteInventoryService._is_fiscally_accepted({"status": "Emitida"}) is True
    assert CreditNoteInventoryService._is_fiscally_accepted({"status": "Cobrada"}) is True
    assert CreditNoteInventoryService._is_fiscally_accepted({"status": "Desconocido"}) is False
    assert CreditNoteInventoryService._is_fiscally_accepted({"status": "Pagada"}) is False  # no en el allow-list legacy


# ---------------------------------------------------------------------------
# R4 — reingreso idempotente tras interrupción
# ---------------------------------------------------------------------------

def test_finalize_inventory_idempotent_skips_already_reentered(cash_env, monkeypatch):
    saved = []
    _mock_save(monkeypatch, saved)
    refund = {"id": "rf-z", "creditNoteId": "nc-rf-z"}
    cash_env.collection("comp-1", "sandbox_invoices").document("nc-rf-z").set({
        "id": "nc-rf-z", "ecfType": "Nota de Crédito (E34)", "status": "Emitida",
        "stockReentered": True, "ncStatus": "NC_ACCEPTED",
    })
    CashRefundService._finalize_credit_note_inventory("owner", "comp-1", True, refund, "E340000000001")
    assert not any(d.get("ecfType") == "Nota de Crédito (E34)" for i, d in saved)  # no se re-guardó


# ---------------------------------------------------------------------------
# R4 — resoluciones concurrentes con la misma clave (idempotente)
# ---------------------------------------------------------------------------

def test_resolve_concurrent_same_key_idempotent(cash_env):
    _seed_invoice(cash_env, quantity=2.0, returned=1.0)
    _seed_refund_doc(cash_env, refund_id="rf-c", invoice_id="inv-1", items=[{"itemId": "prod-1", "quantity": 1.0}])
    results = []

    def do():
        try:
            results.append(CashRefundService.resolve_reconciling(
                "owner", "comp-1", True, "rf-c", "abandon", "x", "Sup", resolution_key="rk-same"))
        except CashRefundError:
            pass

    threads = [threading.Thread(target=do) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 2  # ambas idempotentes
    inv = cash_env.collection("comp-1", "sandbox_invoices").document("inv-1").get().to_dict()
    assert inv["items"][0]["returnedQty"] == 0.0  # liberado exactamente una vez
