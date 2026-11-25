"""Pruebas del ProductImportProcessor (confirmación, idempotencia y reanudación)."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.product_import_processor import ProductImportProcessor


class _FakeDoc:
    def __init__(self, doc_id, data=None):
        self.id = doc_id
        self._data = data or {}
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class _FakeColl:
    def __init__(self):
        self._docs = {}

    def document(self, doc_id):
        coll_self = self

        class _DocRef:
            def set(self, data, merge=False):
                coll_self._docs[doc_id] = dict(data)
                return True

            def get(self):
                if doc_id in coll_self._docs:
                    return _FakeDoc(doc_id, coll_self._docs[doc_id])
                return _FakeDoc(doc_id, None)

        return _DocRef()


def _row(**fields):
    row = {"row": "2", "name": "Producto", "code": "P1", "costPrice": "100",
           "pricingMode": "MONTO", "price": "120"}
    row.update(fields)
    return row


@pytest.fixture
def ctx():
    saved = []
    registered = []
    coll = _FakeColl()

    def fake_save_item(owner_uid, item_id, item_dict, company_id="", sandbox=True):
        saved.append((item_id, dict(item_dict)))
        return item_dict

    def fake_register(owner_uid, company_id, item_id, warehouse_id, quantity,
                      unit_cost, batch_id, row_key, sandbox=True, performed_by="",
                      effective_date="", lot_number="", expiration_date=""):
        registered.append({
            "item_id": item_id, "warehouse_id": warehouse_id, "quantity": quantity,
            "unit_cost": unit_cost, "batch_id": batch_id, "row_key": row_key,
        })
        return {"id": f"tx-{len(registered)}"}

    with patch("app.services.product_import_processor.firebase_initialized", True), \
         patch("app.services.product_import_processor.db_firestore", MagicMock()), \
         patch("app.services.product_import_processor._company_coll", return_value=coll), \
         patch("app.services.product_import_processor.DatabaseService.save_item", side_effect=fake_save_item), \
         patch("app.services.initial_stock_service.InitialStockService.register", side_effect=fake_register):
        yield {"saved": saved, "registered": registered, "coll": coll}


def test_process_new_product_with_initial_stock(ctx):
    result = ProductImportProcessor.process_batch(
        "owner", "c1", "b1", [_row(initialStock="150", warehouseId="w1", initialUnitCost="90")],
        existing_items=[], warehouses=[{"id": "w1", "name": "Principal"}],
    )
    assert result["summary"]["created"] == 1
    assert result["summary"]["stockMovements"] == 1
    assert result["rows"][0]["status"] == "done"
    assert result["rows"][0]["inventoryTransactionId"] == "tx-1"
    assert len(ctx["saved"]) == 1
    assert ctx["registered"][0]["quantity"] == 150.0
    assert ctx["registered"][0]["unit_cost"] == 90.0


def test_process_update_existing_preserves_item_id(ctx):
    existing = [{"id": "item-1", "code": "P1", "name": "Viejo", "price": 1.0,
                 "costPrice": 100.0, "totalStock": 5.0, "createdAt": "2020-01-01"}]
    result = ProductImportProcessor.process_batch(
        "owner", "c1", "b1", [_row()], existing_items=existing, warehouses=[])
    assert result["summary"]["updated"] == 1
    saved_item_id, saved_dict = ctx["saved"][0]
    assert saved_item_id == "item-1"
    assert saved_dict["totalStock"] == 5.0
    assert saved_dict["createdAt"] == "2020-01-01"


def test_process_resume_skips_done_rows(ctx):
    rows = [_row(initialStock="10", warehouseId="w1")]
    warehouses = [{"id": "w1", "name": "Principal"}]
    first = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], warehouses)
    assert first["summary"]["processed"] == 1

    second = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], warehouses)
    assert second["summary"]["processed"] == 0
    assert second["summary"]["skipped"] == 1
    # No se duplicó producto ni movimiento.
    assert len(ctx["saved"]) == 1
    assert len(ctx["registered"]) == 1


def test_process_row_without_initial_stock(ctx):
    result = ProductImportProcessor.process_batch("owner", "c1", "b1", [_row()], [], [])
    assert result["summary"]["created"] == 1
    assert result["summary"]["stockMovements"] == 0
    assert ctx["registered"] == []


def test_process_duplicate_code_within_batch(ctx):
    rows = [_row(row="2", code="P1"), _row(row="3", code="P1", name="Otro")]
    result = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], [])
    assert result["summary"]["created"] == 1
    assert result["summary"]["skipped"] == 1


def test_process_error_missing_name(ctx):
    rows = [_row(name="", price="10")]
    result = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], [])
    assert result["summary"]["errors"] == 1
    assert ctx["saved"] == []


def test_process_missing_warehouse_for_initial_stock(ctx):
    result = ProductImportProcessor.process_batch(
        "owner", "c1", "b1", [_row(initialStock="10", warehouseId="no-existe")],
        [], [{"id": "w1", "name": "Principal"}])
    assert result["summary"]["errors"] == 1
    assert result["rows"][0]["status"] == "error"
    assert ctx["registered"] == []
