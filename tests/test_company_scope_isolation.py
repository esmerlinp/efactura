"""Aislamiento estricto por empresa: nunca se adivina la empresa desde el owner.

Reglas cubiertas:
- `_resolve_company_id` (bridge legacy) solo resuelve si el owner tiene
  exactamente UNA empresa; con 0 o >1 devuelve None (fail-closed).
- Los jobs de facturación iteran la colección `companies` y usan el
  company_id de cada documento, nunca la "empresa del owner".
"""

from app.services import db_service, scheduler


class _Doc:
    def __init__(self, doc_id, data=None, exists=True):
        self.id = doc_id
        self._data = data or {}
        self.exists = exists

    def get(self):
        return self

    def to_dict(self):
        return dict(self._data)


class _CompaniesCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def where(self, *args, **kwargs):
        return self

    def get(self):
        return list(self._docs)

    def stream(self):
        return iter(list(self._docs))

    def document(self, doc_id):
        for doc in self._docs:
            if doc.id == doc_id:
                return doc
        return _Doc(doc_id, {}, exists=False)


class _FakeFirestore:
    def __init__(self, docs):
        self._docs = list(docs)

    def collection(self, name):
        assert name == "companies"
        return _CompaniesCollection(self._docs)


def _install(monkeypatch, docs, initialized=True):
    monkeypatch.setattr(db_service, "db_firestore", _FakeFirestore(docs), raising=False)
    monkeypatch.setattr(db_service, "firebase_initialized", initialized, raising=False)


def _company(doc_id, owner_uid, created_at):
    return _Doc(doc_id, {"owner_uid": owner_uid, "created_at": created_at})


# ── Bridge legacy: fail-closed con owner multi-empresa ────────────────────


def test_resolve_single_company_returns_it(monkeypatch):
    _install(monkeypatch, [_company("company-1", "owner-1", "2026-01-01")])
    assert db_service._resolve_company_id("owner-1") == "company-1"


def test_resolve_multiple_companies_fails_closed(monkeypatch):
    _install(
        monkeypatch,
        [
            _company("company-old", "owner-1", "2026-08-05T10:00:00+00:00"),
            _company("company-new", "owner-1", "2026-10-11T10:00:00+00:00"),
        ],
    )
    # Antes devolvía la "más reciente" y mezclaba datos entre empresas.
    assert db_service._resolve_company_id("owner-1") is None


def test_resolve_without_companies_returns_none(monkeypatch):
    _install(monkeypatch, [])
    assert db_service._resolve_company_id("owner-1") is None


def test_resolve_empty_owner_returns_none(monkeypatch):
    _install(monkeypatch, [_company("company-1", "owner-1", "2026-01-01")])
    assert db_service._resolve_company_id("") is None


def test_resolve_read_error_fails_closed(monkeypatch):
    class _Broken:
        def collection(self, name):
            raise RuntimeError("firestore unavailable")

    monkeypatch.setattr(db_service, "db_firestore", _Broken(), raising=False)
    assert db_service._resolve_company_id("owner-1") is None


# ── Scheduler: cada empresa con su propio company_id/owner_uid ────────────


def test_billing_companies_returns_each_company_with_its_owner(monkeypatch):
    _install(
        monkeypatch,
        [
            _company("company-old", "owner-1", "2026-08-05"),
            _company("company-new", "owner-1", "2026-10-11"),
            _company("company-other", "owner-2", "2026-01-01"),
        ],
    )
    companies = scheduler._billing_companies()
    assert {(c["id"], c["owner_uid"]) for c in companies} == {
        ("company-old", "owner-1"),
        ("company-new", "owner-1"),
        ("company-other", "owner-2"),
    }


def test_billing_companies_filters_explicit_company(monkeypatch):
    _install(
        monkeypatch,
        [
            _company("company-old", "owner-1", "2026-08-05"),
            _company("company-new", "owner-1", "2026-10-11"),
        ],
    )
    assert scheduler._billing_companies("company-new") == [
        {"id": "company-new", "owner_uid": "owner-1"}
    ]


def test_billing_companies_skips_company_without_owner(monkeypatch):
    _install(
        monkeypatch,
        [
            _Doc("orphan", {"created_at": "2026-01-01"}),
            _company("company-1", "owner-1", "2026-01-01"),
        ],
    )
    assert scheduler._billing_companies() == [{"id": "company-1", "owner_uid": "owner-1"}]


def test_billing_companies_unknown_explicit_company(monkeypatch):
    _install(monkeypatch, [_company("company-1", "owner-1", "2026-01-01")])
    assert scheduler._billing_companies("missing") == []


def test_billing_companies_without_firestore(monkeypatch):
    _install(monkeypatch, [], initialized=False)
    assert scheduler._billing_companies() == []


# ── Lecturas por owner sin empresa explícita: fail-closed y sin mezclar ────


def test_get_projects_with_ambiguous_owner_returns_empty(monkeypatch):
    _install(
        monkeypatch,
        [
            _company("company-old", "owner-1", "2026-08-05"),
            _company("company-new", "owner-1", "2026-10-11"),
        ],
    )
    assert db_service.DatabaseService.get_projects("owner-1", sandbox=True) == []


def test_get_projects_does_not_fall_back_to_another_company(monkeypatch):
    _install(monkeypatch, [_company("company-1", "owner-1", "2026-01-01")])
    # Con una sola empresa el bridge legacy sí resuelve, pero la lectura debe
    # quedar acotada a esa empresa (no hay datos → lista vacía, sin excepción).
    assert db_service.DatabaseService.get_projects("owner-1", sandbox=True) == []
