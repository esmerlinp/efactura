"""Tests para adjuntos de solicitudes (documentos de aval) en vacaciones/licencias.

Cubre la capa de datos `hr_data_service` (guardar/recuperar/eliminar adjuntos
por requestId y requestType) y el filtrado por tipo.
"""

from unittest.mock import patch

import pytest

from app.services import hr_data_service as hr

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


def _attachment(doc_id="a1", request_id="r1", request_type="vacation"):
    return {
        "id": doc_id,
        "requestId": request_id,
        "requestType": request_type,
        "name": "cert.pdf",
        "size": 100,
        "url": "https://storage.googleapis.com/bucket/path/cert.pdf",
        "storagePath": "users/u1/request_attachments/r1/cert.pdf",
        "uploadedAt": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def db():
    return _DB()


def test_save_request_attachment(db):
    with patch.object(hr, "firebase_initialized", True), patch.object(hr, "db_firestore", db):
        hr.save_request_attachment(COMPANY, _attachment("a1", "r1", "vacation"))
    assert db.coll.docs["a1"]["requestId"] == "r1"
    assert db.coll.docs["a1"]["requestType"] == "vacation"


def test_save_assigns_id_when_missing(db):
    data = {k: v for k, v in _attachment().items() if k != "id"}
    with patch.object(hr, "firebase_initialized", True), patch.object(hr, "db_firestore", db):
        hr.save_request_attachment(COMPANY, data)
    (stored,) = db.coll.docs.values()
    assert stored["id"]
    assert stored["requestId"] == "r1"


def test_get_attachments_filters_by_request_id(db):
    db.coll.docs = {
        "a1": _attachment("a1", "r1", "vacation"),
        "a2": _attachment("a2", "r2", "vacation"),
    }
    with patch.object(hr, "firebase_initialized", True), patch.object(hr, "db_firestore", db):
        result = hr.get_request_attachments(COMPANY, request_id="r1")
    assert [a["id"] for a in result] == ["a1"]


def test_get_attachments_filters_by_type(db):
    db.coll.docs = {
        "a1": _attachment("a1", "r1", "vacation"),
        "a2": _attachment("a2", "r2", "leave"),
    }
    with patch.object(hr, "firebase_initialized", True), patch.object(hr, "db_firestore", db):
        result = hr.get_request_attachments(COMPANY, request_type="leave")
    assert [a["id"] for a in result] == ["a2"]


def test_get_attachments_all_when_no_request_id(db):
    db.coll.docs = {
        "a1": _attachment("a1", "r1", "vacation"),
        "a2": _attachment("a2", "r2", "leave"),
    }
    with patch.object(hr, "firebase_initialized", True), patch.object(hr, "db_firestore", db):
        result = hr.get_request_attachments(COMPANY)
    assert len(result) == 2


def test_delete_request_attachment(db):
    db.coll.docs = {"a1": _attachment("a1", "r1", "vacation")}
    with patch.object(hr, "firebase_initialized", True), patch.object(hr, "db_firestore", db):
        hr.delete_request_attachment(COMPANY, "a1")
    assert db.coll.docs == {}


def test_get_attachments_returns_empty_when_firestore_off():
    with patch.object(hr, "firebase_initialized", False):
        assert hr.get_request_attachments(COMPANY) == []
