"""Pruebas de integración de la migración de productos e inventario inicial.

Simula el flujo completo (previsualización → confirmación) con:
- Productos nuevos y existentes (upsert por `code`).
- Precio por monto y por markup.
- Múltiples almacenes.
- Existencias iniciales con valoración.
- Reimportación (idempotencia) y recuperación de fallos parciales.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.product_import_preview import build_preview
from app.services.product_import_processor import ProductImportProcessor
from app.services.product_import_batch_service import ProductImportBatchService


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
                if merge:
                    merged = dict(coll_self._docs.get(doc_id, {}))
                    merged.update(data)
                    coll_self._docs[doc_id] = merged
                else:
                    coll_self._docs[doc_id] = dict(data)
                return True

            def get(self):
                if doc_id in coll_self._docs:
                    return _FakeDoc(doc_id, coll_self._docs[doc_id])
                return _FakeDoc(doc_id, None)

        return _DocRef()

    def stream(self):
        return [_FakeDoc(did, d) for did, d in self._docs.items()]


class _FakeCompany:
    def __init__(self):
        self._colls = {}

    def get_coll(self, coll_name):
        if coll_name not in self._colls:
            self._colls[coll_name] = _FakeColl()
        return self._colls[coll_name]


@pytest.fixture
def env():
    company = _FakeCompany()
    saved = []
    registered = []

    def fake_company_coll(*, company_id=None, coll_name=None, owner_uid=None):
        return company.get_coll(coll_name)

    def fake_save_item(owner_uid, item_id, item_dict, company_id="", sandbox=True):
        saved.append((item_id, dict(item_dict)))
        return item_dict

    def fake_register(owner_uid, company_id, item_id, warehouse_id, quantity,
                      unit_cost, batch_id, row_key, sandbox=True, performed_by="",
                      effective_date="", lot_number="", expiration_date=""):
        registered.append({"item_id": item_id, "warehouse_id": warehouse_id,
                           "quantity": quantity, "unit_cost": unit_cost})
        return {"id": f"tx-{len(registered)}"}

    with patch("app.services.product_import_processor.firebase_initialized", True), \
         patch("app.services.product_import_processor.db_firestore", MagicMock()), \
         patch("app.services.product_import_processor._company_coll", side_effect=fake_company_coll), \
         patch("app.services.product_import_batch_service.firebase_initialized", True), \
         patch("app.services.product_import_batch_service.db_firestore", MagicMock()), \
         patch("app.services.product_import_batch_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.product_import_processor.DatabaseService.save_item", side_effect=fake_save_item), \
         patch("app.services.initial_stock_service.InitialStockService.register", side_effect=fake_register):
        yield {"company": company, "saved": saved, "registered": registered}


def _build_rows(n, *, warehouse="default-almacen-principal"):
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "row": str(i + 1),
            "code": f"PROD-{i:04d}",
            "name": f"Producto {i}",
            "costPrice": "100.00",
            "pricingMode": "PORCENTAJE" if i % 2 == 0 else "MONTO",
            "markupPercentage": "10" if i % 2 == 0 else "",
            "price": "" if i % 2 == 0 else "120.00",
            "initialStock": "10",
            "warehouseId": warehouse,
            "initialUnitCost": "90.00",
        })
    return rows


def test_full_migration_round_trip(env):
    rows = _build_rows(20)
    warehouses = [{"id": "default-almacen-principal", "name": "Principal"},
                  {"id": "wh-2", "name": "Sucursal"}]

    # 1. Previsualización
    preview = build_preview(rows, existing_codes=set(), existing_barcodes=set())
    assert preview["summary"]["newProducts"] == 20
    assert preview["summary"]["inventoryMovements"] == 20
    assert preview["summary"]["totalUnits"] == 200.0

    # 2. Lote creado y validado
    batch = ProductImportBatchService.create_batch("c1", {"filename": "migracion.csv"})
    ProductImportBatchService.mark_validated("c1", batch["id"], preview["summary"])

    # 3. Confirmación
    result = ProductImportProcessor.process_batch(
        "owner", "c1", batch["id"], rows,
        existing_items=[], warehouses=warehouses,
    )
    assert result["summary"]["created"] == 20
    assert result["summary"]["stockMovements"] == 20
    assert result["summary"]["totalUnits"] == 200.0

    # 4. Lote confirmado
    ProductImportBatchService.mark_confirmed("c1", batch["id"], confirmed_by="u@x.com")
    confirmed = ProductImportBatchService.get_batch("c1", batch["id"])
    assert confirmed["status"] == "CONFIRMED"

    # 5. Precio por markup correcto (fila par: 100 × 1.10 = 110)
    even_price = next(d["price"] for _, d in env["saved"] if d["pricingMode"] == "markup")
    assert even_price == 110.0


def test_migration_multiple_warehouses(env):
    rows = [
        {"row": "2", "code": "A", "name": "A", "costPrice": "100",
         "pricingMode": "MONTO", "price": "120", "initialStock": "5", "warehouseId": "Principal"},
        {"row": "3", "code": "B", "name": "B", "costPrice": "100",
         "pricingMode": "MONTO", "price": "120", "initialStock": "7", "warehouseId": "wh-2"},
    ]
    warehouses = [{"id": "wh-1", "name": "Principal"}, {"id": "wh-2", "name": "Sucursal"}]
    result = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], warehouses)
    assert result["summary"]["stockMovements"] == 2
    assert env["registered"][0]["warehouse_id"] == "wh-1"
    assert env["registered"][1]["warehouse_id"] == "wh-2"


def test_reimport_is_idempotent(env):
    rows = _build_rows(5)
    warehouses = [{"id": "default-almacen-principal", "name": "Principal"}]
    first = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], warehouses)
    assert first["summary"]["created"] == 5

    saved_count = len(env["saved"])
    reg_count = len(env["registered"])

    second = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], warehouses)
    assert second["summary"]["created"] == 0
    assert second["summary"]["skipped"] == 5
    assert len(env["saved"]) == saved_count
    assert len(env["registered"]) == reg_count


def test_partial_failure_then_recovery(env):
    rows = [
        {"row": "2", "code": "A", "name": "A", "costPrice": "100",
         "pricingMode": "MONTO", "price": "120", "initialStock": "5", "warehouseId": "NO-EXISTE"},
        {"row": "3", "code": "B", "name": "B", "costPrice": "100",
         "pricingMode": "MONTO", "price": "120", "initialStock": "5", "warehouseId": "Principal"},
    ]
    warehouses = [{"id": "wh-1", "name": "Principal"}]
    result = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], warehouses)
    assert result["summary"]["errors"] == 1
    assert result["summary"]["created"] == 1  # B se creó, A falló por almacén

    # Corregimos el almacén de la fila 2 y reintentamos.
    rows[0]["warehouseId"] = "Principal"
    result2 = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], warehouses)
    assert result2["summary"]["created"] == 1  # solo A
    assert result2["summary"]["skipped"] == 1  # B ya estaba hecha
    assert len(env["registered"]) == 2


def test_scale_2000_products(env):
    rows = _build_rows(2000)
    warehouses = [{"id": "default-almacen-principal", "name": "Principal"}]
    result = ProductImportProcessor.process_batch("owner", "c1", "b1", rows, [], warehouses)
    assert result["summary"]["created"] == 2000
    assert result["summary"]["stockMovements"] == 2000
    assert len(env["saved"]) == 2000
    assert len(env["registered"]) == 2000
