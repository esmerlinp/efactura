"""Tests para Autorización de Descuento de Nómina (documentos y firmas).

Cubre el mapeo de montos del movimiento a la plantilla, la elegibilidad
(solo deducción regular/préstamo, no embargo) y la capa de datos de los
documentos de autorización vinculados a un movimiento recurrente.
"""

from unittest.mock import patch

import pytest

from app.services import hr_data_service as hr
from app.services.deduction_authorization_service import (
    authorization_context,
    can_generate_authorization,
)

COMPANY = "company-test"


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


class _DocRef:
    def __init__(self, coll, doc_id):
        self.coll = coll
        self.doc_id = doc_id

    def set(self, data):
        self.coll.docs[self.doc_id] = data

    def delete(self):
        self.coll.docs.pop(self.doc_id, None)


class _Coll:
    def __init__(self):
        self.docs = {}

    def where(self, field, op, value):
        return _Query(self, field, value)

    def document(self, doc_id):
        return _DocRef(self, doc_id)

    def get(self):
        return [_Doc(k, v) for k, v in self.docs.items()]


class _DB:
    def __init__(self):
        self.coll = _Coll()

    def collection(self, path):
        return self.coll


@pytest.fixture
def db():
    return _DB()


# ── Elegibilidad ──

def test_can_authorize_regular_deduction():
    assert can_generate_authorization({"movementType": "deduction", "isGarnishment": False})


def test_can_authorize_loan():
    assert can_generate_authorization({"movementType": "deduction", "isLoan": True, "isGarnishment": False})


def test_cannot_authorize_garnishment():
    assert not can_generate_authorization({"movementType": "deduction", "isGarnishment": True})


def test_cannot_authorize_earning():
    assert not can_generate_authorization({"movementType": "earning", "isGarnishment": False})


# ── Mapeo de montos ──

def test_authorization_context_loan():
    ctx = authorization_context({
        "isLoan": True,
        "totalAmount": 50000,
        "totalInstallments": 10,
        "installmentAmount": 5000,
        "description": "Préstamo de vehículo",
    })
    assert ctx["valor_total"] == 50000
    assert ctx["n_cuotas"] == 10
    assert ctx["valor_cuota"] == 5000
    assert ctx["concepto"] == "Préstamo de vehículo"
    assert "cincuenta mil" in ctx["valor_en_letras"]


def test_authorization_context_regular():
    ctx = authorization_context({
        "isLoan": False,
        "amount": 2500,
        "description": "Ahorro cooperativa",
    })
    assert ctx["valor_total"] == 2500
    assert ctx["n_cuotas"] == 1
    assert ctx["valor_cuota"] == 2500
    assert ctx["concepto"] == "Ahorro cooperativa"


def test_authorization_context_falls_back_to_concept_code():
    ctx = authorization_context({"isLoan": False, "amount": 1000, "description": "", "conceptCode": "DED-001"})
    assert ctx["concepto"] == "DED-001"


def test_authorization_context_periodo_mensual():
    ctx = authorization_context({"isLoan": False, "amount": 1000}, employee={"paymentFrequency": "mensual"})
    assert ctx["periodo_adj"] == "mensuales"


def test_authorization_context_periodo_quincenal():
    ctx = authorization_context({"isLoan": True, "totalAmount": 10000, "totalInstallments": 8, "installmentAmount": 1250},
                                employee={"paymentFrequency": "quincenal"})
    assert ctx["periodo_adj"] == "quincenales"
    assert ctx["n_cuotas"] == 8


def test_authorization_context_periodo_ambos_fallback():
    ctx = authorization_context({"isLoan": False, "amount": 1000}, employee={"paymentFrequency": "ambos"})
    assert ctx["periodo_adj"] == ""


def test_authorization_context_periodo_empty_employee():
    ctx = authorization_context({"isLoan": False, "amount": 1000})
    assert ctx["periodo_adj"] == ""


# ── Capa de datos ──

def _doc(doc_id="d1", movement_id="m1"):
    return {
        "id": doc_id,
        "employeeId": "e1",
        "recurringMovementId": movement_id,
        "category": "authorization",
        "name": "autorizacion.pdf",
        "url": "https://storage.googleapis.com/bucket/employee_documents/e1/autorizacion.pdf",
        "uploadedAt": "2026-01-01T00:00:00Z",
    }


def test_get_deduction_authorization_docs_filters_by_movement(db):
    db.coll.docs = {
        "d1": _doc("d1", "m1"),
        "d2": _doc("d2", "m2"),
    }
    with patch.object(hr, "firebase_initialized", True), patch.object(hr, "db_firestore", db):
        result = hr.get_deduction_authorization_docs(COMPANY, "m1")
    assert [d["id"] for d in result] == ["d1"]


def test_get_deduction_authorization_docs_empty_when_firestore_off():
    with patch.object(hr, "firebase_initialized", False):
        assert hr.get_deduction_authorization_docs(COMPANY, "m1") == []
