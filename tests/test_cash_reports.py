"""Pruebas de Fase 4.4 — reportes y controles de caja."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import db_service
from app.services.cash_report_service import CashReportService
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


def _seed_delivery(cash_env, id, shift_id="shift-1", status="PENDING_RECEIPT", dop=0.0, usd=0.0):
    cash_env.collection("comp-1", "sandbox_cash_deliveries").document(id).set({
        "id": id, "shiftId": shift_id, "status": status,
        "amounts": {"dop": dop, "usd": usd},
        "deliveredBy": {"uid": "cajero", "name": "Cajero"},
        "receivedBy": None, "cashDropTransactionIds": [],
    })


def _seed_reconciliation(cash_env, id, shift_id="shift-1", channel="CASH_DOP", status="RECONCILED", difference=0.0):
    cash_env.collection("comp-1", "sandbox_cash_reconciliations").document(id).set({
        "id": id, "shiftId": shift_id, "channel": channel, "status": status,
        "expectedAmount": 100.0, "receivedAmount": 100.0 + difference, "difference": difference,
    })


def test_list_deliveries_filters_by_shift_and_status(cash_env):
    _seed_delivery(cash_env, "d1", shift_id="shift-1", status="PENDING_RECEIPT", dop=1000.0)
    _seed_delivery(cash_env, "d2", shift_id="shift-1", status="RECEIVED", dop=2000.0)
    _seed_delivery(cash_env, "d3", shift_id="shift-2", status="PENDING_RECEIPT", dop=3000.0)

    all_shift1 = CashReportService.list_deliveries("owner", "comp-1", True, shift_id="shift-1")
    assert len(all_shift1) == 2
    pending = CashReportService.list_deliveries("owner", "comp-1", True, shift_id="shift-1", status="PENDING_RECEIPT")
    assert len(pending) == 1 and pending[0]["id"] == "d1"


def test_list_reconciliations_filters_by_channel_and_status(cash_env):
    _seed_reconciliation(cash_env, "r1", channel="CASH_DOP", status="RECONCILED")
    _seed_reconciliation(cash_env, "r2", channel="CARD", status="UNDER_REVIEW", difference=-10.0)
    _seed_reconciliation(cash_env, "r3", channel="CARD", status="RECONCILED")

    cards = CashReportService.list_reconciliations("owner", "comp-1", True, channel="CARD")
    assert len(cards) == 2
    under_review = CashReportService.list_reconciliations("owner", "comp-1", True, status="UNDER_REVIEW")
    assert len(under_review) == 1 and under_review[0]["id"] == "r2"


def test_shift_summary(cash_env):
    _seed_delivery(cash_env, "d1", shift_id="shift-1", status="PENDING_RECEIPT", dop=1000.0)
    _seed_delivery(cash_env, "d2", shift_id="shift-1", status="RECEIVED", dop=2000.0, usd=50.0)
    _seed_reconciliation(cash_env, "r1", shift_id="shift-1", channel="CASH_DOP", status="RECONCILED")
    _seed_reconciliation(cash_env, "r2", shift_id="shift-1", channel="CARD", status="UNDER_REVIEW", difference=-10.0)

    summary = CashReportService.shift_summary("owner", "comp-1", True, "shift-1")
    assert summary["deliveries"]["total"] == 2
    assert summary["deliveries"]["pendingReceipt"] == 1
    assert summary["deliveries"]["pendingReceiptDop"] == 1000.0
    assert summary["deliveries"]["received"] == 1
    assert summary["deliveries"]["receivedDop"] == 2000.0
    assert summary["deliveries"]["receivedUsd"] == 50.0
    assert summary["reconciliations"]["underReview"] == 1
    assert summary["reconciliations"]["reconciled"] == 1
    assert summary["reconciliations"]["totalDifference"] == -10.0


def test_shift_summary_empty(cash_env):
    summary = CashReportService.shift_summary("owner", "comp-1", True, "shift-empty")
    assert summary["deliveries"]["total"] == 0
    assert summary["reconciliations"]["total"] == 0
