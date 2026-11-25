# app/services/product_import_processor.py
"""
ProductImportProcessor — Procesamiento confirmado de un lote de importación.

Flujo de confirmación (idempotente y reanudable):
    1. Por cada fila válida, determina si es producto nuevo o actualización
       (clave: `code`).
    2. Asigna un `itemId` estable (reutiliza el persistido en el resultado de
       fila para sobrevivir reanudaciones).
    3. Persiste el producto vía `DatabaseService.save_item`.
    4. Si la fila trae existencia inicial > 0, genera el movimiento
       `SALDO_INICIAL` vía `InitialStockService.register` (idempotente).
    5. Registra el resultado por fila en `product_import_rows`.

Garantías:
    - Reintentar una fila no duplica producto (mismo `itemId`) ni movimiento
      (clave de idempotencia estable).
    - Un fallo parcial puede reanudarse: las filas ya completadas se omiten.
"""

import uuid
from datetime import datetime, timezone

from app.services.db_service import (
    DatabaseService,
    db_firestore,
    firebase_initialized,
    _company_coll,
)
from app.services.pricing_service import PricingService
from app.services.product_import_preview import resolve_import_price, sanitize_float
from app.services.initial_stock_service import InitialStockService


class ProductImportProcessor:
    """Motor de confirmación de la importación de productos."""

    @classmethod
    def _row_coll_name(cls, sandbox: bool) -> str:
        return "sandbox_product_import_rows" if sandbox else "product_import_rows"

    @classmethod
    def _row_coll(cls, company_id: str, sandbox: bool = True):
        return _company_coll(company_id=company_id, coll_name=cls._row_coll_name(sandbox))

    @staticmethod
    def normalize_type(value):
        v = (value or "").strip().lower()
        if v in ("servicio", "servicios", "service", "s"):
            return "Servicio"
        return "Bien"

    @staticmethod
    def parse_is_active(value):
        v = (value or "").strip().lower()
        if not v:
            return True
        return v not in ['inactivo', 'false', '0', 'no', 'disabled', 'inactive']

    @classmethod
    def build_item_dict(cls, row, item_id, existing_item=None, pricing_mode="amount", price=0.0):
        """Construye el dict del producto a partir de los valores crudos de la fila."""
        base = {}
        if existing_item:
            base = dict(existing_item)

        item_dict = {
            **base,
            "id": item_id,
            "code": (row.get("code") or "").strip(),
            "barcode": (row.get("barcode") or "").strip(),
            "type": cls.normalize_type(row.get("type")),
            "name": (row.get("name") or "").strip(),
            "price": float(price),
            "costPrice": sanitize_float(row.get("costPrice")),
            "pricingMode": pricing_mode,
            "markupPercentage": (row.get("markupPercentage") or "").strip()
                if pricing_mode == PricingService.MODE_MARKUP else None,
            "priceSource": "import",
            "priceCalculationBase": "costPrice" if pricing_mode == PricingService.MODE_MARKUP else "",
            "unit": (row.get("unit") or "Unidad").strip() or "Unidad",
            "itbisRate": sanitize_float(row.get("itbisRate"), 0.18),
            "minStock": sanitize_float(row.get("minStock")),
            "maxStock": sanitize_float(row.get("maxStock")),
            "rackLocation": (row.get("rackLocation") or "").strip(),
            "categoryId": (row.get("categoryId") or "general").strip(),
            "codigoImpuesto": (row.get("codigoImpuesto") or "").strip(),
            "tasaImpuestoAdicional": sanitize_float(row.get("tasaImpuestoAdicional")),
            "supplierName": (row.get("supplierName") or "").strip(),
            "wholesalePrice": sanitize_float(row.get("wholesalePrice")),
            "brand": (row.get("brand") or "").strip(),
            "imageUrl": (row.get("imageUrl") or "").strip(),
            "isActive": cls.parse_is_active(row.get("isActive")),
        }
        if existing_item:
            item_dict["totalStock"] = float(existing_item.get("totalStock", 0.0))
            item_dict["createdAt"] = existing_item.get("createdAt")
        else:
            item_dict["totalStock"] = 0.0
        return item_dict

    @staticmethod
    def _get_row_result(row_coll, doc_id):
        if row_coll is None or not firebase_initialized or db_firestore is None:
            return None
        try:
            snap = row_coll.document(doc_id).get()
            if snap.exists:
                return snap.to_dict()
        except Exception:
            pass
        return None

    @staticmethod
    def _save_row_result(row_coll, doc_id, data):
        if row_coll is None or not firebase_initialized or db_firestore is None:
            return
        try:
            row_coll.document(doc_id).set(data)
        except Exception as e:
            print(f"⚠️ [import-processor] Error guardando resultado de fila {doc_id}: {e}")

    @classmethod
    def process_batch(cls, owner_uid, company_id, batch_id, rows,
                      existing_items=None, warehouses=None, sandbox=True,
                      performed_by="", effective_date=""):
        """Procesa las filas de un lote y registra productos + existencias iniciales.

        Parámetros:
            rows: lista de dicts con valores crudos de campo (incl. "row").
            existing_items: catálogo actual (para upsert por `code`).
            warehouses: almacenes de la empresa (para resolver el almacén).

        Retorna un dict con resumen y resultados por fila.
        """
        existing_items = existing_items or []
        warehouses = warehouses or []

        code_to_item = {}
        for it in existing_items:
            c = str(it.get("code", "")).strip().lower()
            if c:
                code_to_item.setdefault(c, it)

        row_coll = cls._row_coll(company_id, sandbox)
        summary = {
            "processed": 0, "created": 0, "updated": 0,
            "stockMovements": 0, "skipped": 0, "errors": 0,
            "totalUnits": 0.0, "totalInventoryValue": 0.0,
        }
        results = []
        seen_codes = set()

        for row in rows:
            row_key = str(row.get("row"))
            doc_id = f"{batch_id}_{row_key}"
            name = (row.get("name") or "").strip()
            code = (row.get("code") or "").strip()
            code_key = code.lower()

            existing_result = cls._get_row_result(row_coll, doc_id)
            if existing_result and existing_result.get("status") == "done":
                summary["skipped"] += 1
                results.append(existing_result)
                continue

            cost_price = sanitize_float(row.get("costPrice"))
            pricing_mode = PricingService.normalize_mode(row.get("pricingMode"))
            price, err_col, err_reason = resolve_import_price(
                cost_price, pricing_mode,
                (row.get("markupPercentage") or "").strip(),
                row.get("price"),
            )

            if not name or err_col:
                summary["errors"] += 1
                err = {
                    "batchId": batch_id, "rowNumber": row_key, "code": code,
                    "status": "error",
                    "error": {"column": err_col or "name", "reason": err_reason or "Falta el nombre."},
                }
                cls._save_row_result(row_coll, doc_id, err)
                results.append(err)
                continue

            if code_key and code_key in seen_codes:
                summary["skipped"] += 1
                dup = {
                    "batchId": batch_id, "rowNumber": row_key, "code": code,
                    "status": "skipped",
                    "error": {"column": "code", "reason": f"Código duplicado: '{code}'."},
                }
                results.append(dup)
                continue
            if code_key:
                seen_codes.add(code_key)

            existing_item = code_to_item.get(code_key)
            action = "update" if existing_item else "new"

            # itemId estable para reanudación
            if existing_result and existing_result.get("itemId"):
                item_id = existing_result["itemId"]
            elif existing_item:
                item_id = existing_item.get("id")
            else:
                item_id = str(uuid.uuid4())

            item_dict = cls.build_item_dict(row, item_id, existing_item, pricing_mode, price)

            try:
                DatabaseService.save_item(
                    owner_uid, item_id, item_dict,
                    company_id=company_id, sandbox=sandbox,
                )
            except Exception as e:
                summary["errors"] += 1
                err = {
                    "batchId": batch_id, "rowNumber": row_key, "code": code, "itemId": item_id,
                    "status": "error", "error": {"reason": f"Error guardando producto: {e}"},
                }
                cls._save_row_result(row_coll, doc_id, err)
                results.append(err)
                continue

            result = {
                "batchId": batch_id, "rowNumber": row_key, "code": code,
                "itemId": item_id, "action": action, "status": "done",
                "inventoryTransactionId": "",
            }

            initial_qty = sanitize_float(row.get("initialStock"))
            if initial_qty > 0:
                warehouse_id = InitialStockService.resolve_warehouse_id(
                    row.get("warehouseId"), warehouses)
                if not warehouse_id:
                    summary["errors"] += 1
                    result["status"] = "error"
                    result["error"] = {"column": "warehouseId", "reason": "Almacén no encontrado para la existencia inicial."}
                    cls._save_row_result(row_coll, doc_id, result)
                    results.append(result)
                    continue
                unit_cost = sanitize_float(row.get("initialUnitCost")) or cost_price
                tx = InitialStockService.register(
                    owner_uid, company_id, item_id, warehouse_id,
                    initial_qty, unit_cost, batch_id, row_key,
                    sandbox=sandbox, performed_by=performed_by,
                    effective_date=effective_date,
                    lot_number=(row.get("lotNumber") or "").strip(),
                    expiration_date=(row.get("expirationDate") or "").strip(),
                )
                if tx:
                    result["inventoryTransactionId"] = tx.get("id", "")
                summary["stockMovements"] += 1
                summary["totalUnits"] += initial_qty
                summary["totalInventoryValue"] += round(initial_qty * unit_cost, 2)

            cls._save_row_result(row_coll, doc_id, result)
            summary["processed"] += 1
            if action == "new":
                summary["created"] += 1
            else:
                summary["updated"] += 1
            results.append(result)

        return {"summary": summary, "rows": results}
