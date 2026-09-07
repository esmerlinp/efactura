"""Tests de regresión para la promoción automática scheduled → active.

Cuando un movimiento recurrente en estado "scheduled" se aplica por primera
vez en una corrida de nómina real (apply_recurring_for_employee), debe pasar
a "active". Las excepciones de período (skip) y los montos 0 no deben
promocionarlo; un préstamo que se salda pasa a "completed".
"""

from unittest.mock import patch

import app.services.recurring_service as rs


COMPANY = "company-test"
EMP = "EMP1"


class _FakeTx:
    """Sustituto determinista de PayrollTransaction (pydantic está mockeado
    a nivel de sesión en conftest.py y su clase mockeada no es reinstanciable)."""

    def __init__(self, **kwargs):
        self._kwargs = kwargs

    def model_dump(self):
        return dict(self._kwargs)


def _movement(**overrides):
    mv = {
        "id": "MV1",
        "employeeId": EMP,
        "conceptCode": "DESC001",
        "movementType": "deduction",
        "description": "Descuento cooperativa",
        "status": "scheduled",
        "amountType": "fixed",
        "amount": 1000.0,
        "percentage": 0.0,
        "formula": "",
        "isLoan": False,
        "isGarnishment": False,
        "startDate": "",
        "endDate": "",
        "priority": 50,
    }
    mv.update(overrides)
    return mv


def _apply(mv, exc=None, period_revision=1):
    with patch.object(rs, "get_exception", return_value=exc), \
            patch.object(rs, "save_recurring_movement") as mock_save, \
            patch.object(rs, "PayrollTransaction", _FakeTx):
        txs, apps = rs.apply_recurring_for_employee(
            COMPANY, EMP, "", 50000.0,
            "P1", "2026-01", "2026-01-01", "2026-01-31", period_revision,
            {EMP: [mv]}, sandbox=True,
        )
    return txs, apps, mock_save


def test_scheduled_se_promueve_a_active_al_aplicarse():
    mv = _movement()
    txs, apps, mock_save = _apply(mv)
    assert len(txs) == 1
    assert apps[0]["action"] == "applied"
    assert mv["status"] == "active"
    mock_save.assert_called_once()
    saved = mock_save.call_args[0][2]
    assert saved["status"] == "active"


def test_scheduled_con_skip_no_se_promueve():
    mv = _movement()
    txs, apps, mock_save = _apply(mv, exc={"action": "skip"})
    assert len(txs) == 0
    assert apps[0]["action"] == "skipped"
    assert mv["status"] == "scheduled"
    mock_save.assert_not_called()


def test_prestamo_scheduled_que_se_salda_pasa_a_completed():
    mv = _movement(
        isLoan=True, amount=0.0, installmentAmount=2500.0,
        remainingBalance=2500.0, paidInstallments=0, autoComplete=True,
    )
    txs, apps, mock_save = _apply(mv)
    assert len(txs) == 1
    assert mv["status"] == "completed"
    saved = mock_save.call_args[0][2]
    assert saved["status"] == "completed"


def test_active_no_genera_guardado_extra():
    mv = _movement(status="active")
    txs, apps, mock_save = _apply(mv)
    assert len(txs) == 1
    mock_save.assert_not_called()


# ── get_applications_by_employee (ficha del empleado) ──

class _Doc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class _Query:
    def __init__(self, coll, field, value):
        self.coll = coll
        self.field = field
        self.value = value

    def get(self):
        return [
            _Doc(k, v) for k, v in self.coll.docs.items()
            if v.get(self.field) == self.value
        ]


class _Coll:
    def __init__(self):
        self.docs = {}

    def where(self, field, op, value):
        return _Query(self, field, value)

    def get(self):
        return [_Doc(k, v) for k, v in self.docs.items()]


class _DB:
    def __init__(self):
        self.coll = _Coll()

    def collection(self, path):
        return self.coll


def _app(doc_id, emp, mv, applied_at, amount=1000.0, action="applied"):
    return {
        "id": doc_id,
        "employeeId": emp,
        "recurringMovementId": mv,
        "periodId": "P1",
        "periodKey": "2026-01",
        "appliedAmount": amount,
        "remainingAfter": 0.0,
        "action": action,
        "appliedAt": applied_at,
    }


def test_get_applications_by_employee_filtra_y_ordena():
    db = _DB()
    db.coll.docs = {
        "a1": _app("a1", EMP, "MV1", "2026-01-31T00:00:00"),
        "a2": _app("a2", "EMP2", "MV9", "2026-02-28T00:00:00"),
        "a3": _app("a3", EMP, "MV1", "2026-02-28T00:00:00"),
    }
    with patch.object(rs, "firebase_initialized", True), \
            patch.object(rs, "db_firestore", db):
        result = rs.get_applications_by_employee(COMPANY, EMP)
    assert [a["id"] for a in result] == ["a3", "a1"]
    assert all(a["employeeId"] == EMP for a in result)


def test_get_applications_by_employee_vacio_sin_firestore():
    with patch.object(rs, "firebase_initialized", False):
        assert rs.get_applications_by_employee(COMPANY, EMP) == []
