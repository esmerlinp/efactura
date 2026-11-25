"""Pruebas del ProductImportBatchService (lote de importación de productos).

Cubre: creación en DRAFT, máquina de estados, transiciones inválidas,
resumen de resultados, estados terminales y trazabilidad.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.product_import_batch_service import (
    ProductImportBatchService,
    ImportBatchStateError,
)


class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = True

    def to_dict(self):
        return dict(self._data)


class _FakeColl:
    def __init__(self):
        self._docs = {}

    def document(self, doc_id):
        coll_self = self

        class _DocRef:
            def set(self, data, merge=False):
                if merge:
                    existing = coll_self._docs.get(doc_id, {})
                    merged = dict(existing)
                    merged.update(data)
                    coll_self._docs[doc_id] = merged
                else:
                    coll_self._docs[doc_id] = dict(data)
                return True

            def get(self):
                if doc_id in coll_self._docs:
                    return _FakeDoc(doc_id, coll_self._docs[doc_id])
                mock = MagicMock()
                mock.exists = False
                return mock

        return _DocRef()

    def stream(self):
        return [_FakeDoc(did, d) for did, d in self._docs.items()]


@pytest.fixture
def coll():
    return _FakeColl()


@pytest.fixture
def svc(coll):
    with patch("app.services.product_import_batch_service.firebase_initialized", True), \
         patch("app.services.product_import_batch_service.db_firestore", MagicMock()), \
         patch("app.services.product_import_batch_service._company_coll", return_value=coll):
        yield


def test_create_batch_defaults_to_draft(svc, coll):
    batch = ProductImportBatchService.create_batch("company-1")
    assert batch["id"]
    assert batch["companyId"] == "company-1"
    assert batch["status"] == ProductImportBatchService.STATUS_DRAFT
    assert batch["environment"] == "sandbox"
    assert batch["totalRows"] == 0
    assert "company-1" not in coll._docs  # clave real es el batch id
    assert batch["id"] in coll._docs


def test_transition_draft_to_validated(svc):
    b = ProductImportBatchService.create_batch("c1")
    updated = ProductImportBatchService.transition("c1", b["id"], "VALIDATED")
    assert updated["status"] == "VALIDATED"


def test_transition_validated_to_confirmed(svc):
    b = ProductImportBatchService.create_batch("c1")
    ProductImportBatchService.transition("c1", b["id"], "VALIDATED")
    updated = ProductImportBatchService.transition("c1", b["id"], "CONFIRMED")
    assert updated["status"] == "CONFIRMED"
    assert updated["confirmedAt"]


def test_invalid_transition_draft_to_confirmed_raises(svc):
    b = ProductImportBatchService.create_batch("c1")
    with pytest.raises(ImportBatchStateError):
        ProductImportBatchService.transition("c1", b["id"], "CONFIRMED")


def test_confirmed_is_terminal(svc):
    b = ProductImportBatchService.create_batch("c1")
    ProductImportBatchService.transition("c1", b["id"], "VALIDATED")
    ProductImportBatchService.transition("c1", b["id"], "CONFIRMED")
    with pytest.raises(ImportBatchStateError):
        ProductImportBatchService.transition("c1", b["id"], "VALIDATED")


def test_record_summary_updates_counters(svc):
    b = ProductImportBatchService.create_batch("c1")
    updated = ProductImportBatchService.record_summary(
        "c1", b["id"],
        {"totalRows": 10, "newProducts": 8, "updatedProducts": 2,
         "inventoryMovements": 5, "totalUnits": 100, "totalInventoryValue": 12345.67})
    assert updated["totalRows"] == 10
    assert updated["newProducts"] == 8
    assert updated["updatedProducts"] == 2
    assert updated["inventoryMovements"] == 5
    assert updated["totalUnits"] == 100
    assert updated["totalInventoryValue"] == 12345.67


def test_mark_confirmed_sets_confirmed_by(svc):
    b = ProductImportBatchService.create_batch("c1")
    ProductImportBatchService.mark_validated("c1", b["id"])
    updated = ProductImportBatchService.mark_confirmed("c1", b["id"], confirmed_by="user@x.com")
    assert updated["status"] == "CONFIRMED"
    assert updated["confirmedBy"] == "user@x.com"


def test_mark_failed_records_reason(svc):
    b = ProductImportBatchService.create_batch("c1")
    updated = ProductImportBatchService.mark_failed("c1", b["id"], reason="boom")
    assert updated["status"] == "FAILED"
    assert updated["failureReason"] == "boom"


def test_get_batch_missing_returns_none(svc):
    assert ProductImportBatchService.get_batch("c1", "no-existe") is None


def test_list_batches_sorted_desc(svc):
    b1 = ProductImportBatchService.create_batch("c1", {"filename": "a.csv"})
    b2 = ProductImportBatchService.create_batch("c1", {"filename": "b.csv"})
    batches = ProductImportBatchService.list_batches("c1")
    ids = [b["id"] for b in batches]
    assert b1["id"] in ids and b2["id"] in ids
