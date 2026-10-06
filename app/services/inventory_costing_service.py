"""Servicio de costeo de inventario: FIFO, Promedio Ponderado y Costo Estándar."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple


class InventoryCostingService:
    """Calcula y registra costos de inventario por método de costeo (FIFO, Promedio Ponderado, Estándar)."""

    # ── FIFO LEDGER ────────────────────────────────────────────────────────

    @staticmethod
    def get_fifo_ledger(company_id, item_id, warehouse_id=None, sandbox=True):
        """Retorna el libro FIFO ordenado por fecha ASC para un item."""
        from app.services.db_service import db_firestore, firebase_initialized, _company_coll
        rows = []
        if not firebase_initialized:
            return rows
        coll = "sandbox_inventory_cost_ledger" if sandbox else "inventory_cost_ledger"
        try:
            query = _company_coll(company_id=company_id, coll_name=coll)
            docs = []
            try:
                from google.cloud import firestore
                if hasattr(firestore, "FieldFilter"):
                    query_res = query.where(filter=firestore.FieldFilter("itemId", "==", item_id))
                else:
                    query_res = query.where("itemId", "==", item_id)
                docs = query_res.stream() if hasattr(query_res, "stream") else query_res.get()
            except Exception:
                try:
                    docs = query.where("itemId", "==", item_id).get()
                except Exception:
                    docs = query.stream() if hasattr(query, "stream") else query.get()
            for doc in docs:
                data = doc.to_dict()
                if warehouse_id and data.get("warehouseId") != warehouse_id:
                    continue
                rows.append({
                    "id": doc.id,
                    "itemId": data.get("itemId", ""),
                    "warehouseId": data.get("warehouseId", ""),
                    "date": data.get("date", ""),
                    "createdAt": data.get("createdAt", ""),
                    "qtyIn": float(data.get("qtyIn", 0)),
                    "unitCost": float(data.get("unitCost", 0)),
                    "qtyOut": float(data.get("qtyOut", 0)),
                    "balanceQty": float(data.get("balanceQty", 0)),
                    "referenceId": data.get("referenceId", ""),
                    "referenceType": data.get("referenceType", ""),
                    "txId": data.get("txId", ""),
                })
            rows.sort(key=lambda r: str(r.get("date") or r.get("createdAt") or ""))
        except Exception as e:
            print(f"⚠️ Error al leer libro FIFO: {e}")
        return rows

    @staticmethod
    def calculate_fifo_consumption(
        active_layers: List[Dict[str, Any]],
        qty_needed: float,
        item_catalog_cost: float = 0.0,
        available_physical_stock: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Calcula de forma determinista el consumo de capas FIFO para una salida.
        
        Retorna un diccionario estructurado con:
        - totalCost: float (COGS total de la salida)
        - unitCost: float (costo unitario ponderado)
        - costLayers: list[dict] (detalle inmutable de cada capa consumida)
        - layerUpdates: list[dict] (actualizaciones a aplicar a capas existentes)
        - openingLayer: Optional[dict] (capa de apertura creada si hay stock sin capas)
        - uncoveredQty: float (cantidad remanente no cubierta)
        """
        qty_needed = float(qty_needed)
        if qty_needed <= 0:
            return {
                "totalCost": 0.0,
                "unitCost": 0.0,
                "costLayers": [],
                "layerUpdates": [],
                "openingLayer": None,
                "uncoveredQty": 0.0,
            }

        # Filtrar capas con saldo disponible y ordenar por fecha ASC (FIFO)
        sorted_layers = sorted(
            [l for l in active_layers if float(l.get("balanceQty", 0.0)) > 0],
            key=lambda x: str(x.get("date") or x.get("createdAt") or "")
        )

        total_cost = 0.0
        remaining = qty_needed
        consumed = []
        layer_updates = []

        for row in sorted_layers:
            avail = float(row.get("balanceQty", 0.0))
            if avail <= 0:
                continue
            take = min(remaining, avail)
            layer_cost = float(row.get("unitCost", 0.0))
            line_cost = round(take * layer_cost, 4)
            total_cost += line_cost

            consumed.append({
                "layerId": row.get("id", ""),
                "quantity": take,
                "unitCost": layer_cost,
                "totalCost": round(take * layer_cost, 2),
                "referenceId": row.get("referenceId", ""),
                "referenceType": row.get("referenceType", ""),
            })

            new_qty_out = float(row.get("qtyOut", 0.0)) + take
            new_balance = avail - take
            layer_updates.append({
                "id": row.get("id"),
                "qtyOut": new_qty_out,
                "balanceQty": max(0.0, round(new_balance, 4)),
            })

            remaining -= take
            if remaining <= 0:
                break

        opening_layer = None
        # Si las capas existentes no cubren la cantidad solicitada pero hay stock físico
        if remaining > 0 and available_physical_stock >= qty_needed:
            unit_cost = float(item_catalog_cost or 0.0)
            line_cost = round(remaining * unit_cost, 4)
            total_cost += line_cost
            
            opening_layer_id = f"open-{uuid.uuid4().hex[:12]}"
            # El stock inicial que faltaba registrar en capas
            total_in_layers = sum(float(l.get("balanceQty", 0.0)) for l in sorted_layers)
            opening_qty = max(remaining, available_physical_stock - total_in_layers)

            opening_layer = {
                "id": opening_layer_id,
                "qtyIn": opening_qty,
                "unitCost": unit_cost,
                "qtyOut": remaining,
                "balanceQty": max(0.0, opening_qty - remaining),
                "referenceType": "OPENING_BALANCE",
                "referenceId": "MIGRACION_FIFO"
            }

            consumed.append({
                "layerId": opening_layer_id,
                "quantity": remaining,
                "unitCost": unit_cost,
                "totalCost": round(remaining * unit_cost, 2),
                "referenceId": "MIGRACION_FIFO",
                "referenceType": "OPENING_BALANCE"
            })
            remaining = 0.0

        unit_cost_weighted = round(total_cost / qty_needed, 4) if qty_needed > 0 else 0.0

        return {
            "totalCost": round(total_cost, 2),
            "unitCost": unit_cost_weighted,
            "costLayers": consumed,
            "layerUpdates": layer_updates,
            "openingLayer": opening_layer,
            "uncoveredQty": remaining
        }

    @staticmethod
    def get_fifo_cost(item_id, warehouse_id, qty_needed, company_id, sandbox=True):
        """
        Calcula el costo usando FIFO para una cantidad solicitada.
        Retorna (costo_total, lotes_consumidos).
        """
        ledger = InventoryCostingService.get_fifo_ledger(company_id, item_id, warehouse_id, sandbox)
        res = InventoryCostingService.calculate_fifo_consumption(
            active_layers=ledger,
            qty_needed=qty_needed
        )
        return res["totalCost"], res["costLayers"]

    @staticmethod
    def record_fifo_entry(company_id, item_id, warehouse_id, qty_in, unit_cost, reference_id="", reference_type="", sandbox=True):
        """Registra una entrada en el libro FIFO."""
        from app.services.db_service import db_firestore, firebase_initialized, _company_coll
        if not firebase_initialized:
            return None
        coll = "sandbox_inventory_cost_ledger" if sandbox else "inventory_cost_ledger"
        entry_id = str(uuid.uuid4())
        data = {
            "id": entry_id,
            "itemId": item_id,
            "warehouseId": warehouse_id,
            "date": datetime.now(timezone.utc).isoformat(),
            "qtyIn": float(qty_in),
            "unitCost": float(unit_cost),
            "qtyOut": 0.0,
            "balanceQty": float(qty_in),
            "referenceId": reference_id,
            "referenceType": reference_type,
        }
        try:
            _company_coll(company_id=company_id, coll_name=coll).document(entry_id).set(data)
            return entry_id
        except Exception as e:
            print(f"⚠️ Error al registrar entrada FIFO: {e}")
            return None

    @staticmethod
    def apply_fifo_consumption(company_id, consumed_batches, sandbox=True):
        """Aplica el consumo de lotes FIFO actualizando qtyOut y balanceQty."""
        from app.services.db_service import db_firestore, firebase_initialized, _company_coll
        if not firebase_initialized or not consumed_batches:
            return
        coll = "sandbox_inventory_cost_ledger" if sandbox else "inventory_cost_ledger"
        try:
            for batch in consumed_batches:
                layer_id = batch.get("layerId") or batch.get("ledger_id")
                qty = float(batch.get("quantity") or batch.get("qty_consumed") or 0.0)
                if not layer_id or qty <= 0:
                    continue
                ref = _company_coll(company_id=company_id, coll_name=coll).document(layer_id)
                doc = ref.get()
                if doc.exists:
                    data = doc.to_dict()
                    new_qty_out = float(data.get("qtyOut", 0)) + qty
                    new_balance = float(data.get("balanceQty", 0)) - qty
                    ref.update({"qtyOut": new_qty_out, "balanceQty": max(0.0, new_balance)})
        except Exception as e:
            print(f"⚠️ Error al aplicar consumo FIFO: {e}")

    # ── PROMEDIO PONDERADO ─────────────────────────────────────────────────

    @staticmethod
    def get_weighted_average_cost(company_id, item_id, warehouse_id=None, sandbox=True):
        """
        Calcula el costo promedio ponderado para un item.
        Usa el libro de costos (ledger) para calcular: Σ(qty_in × unit_cost) / Σ(qty_in).
        """
        ledger = InventoryCostingService.get_fifo_ledger(company_id, item_id, warehouse_id, sandbox)
        total_value = 0.0
        total_qty = 0.0
        for row in ledger:
            total_value += row["qtyIn"] * row["unitCost"]
            total_qty += row["qtyIn"]

        if total_qty > 0:
            return round(total_value / total_qty, 2)
        return 0.0

    # ── COSTO ESTÁNDAR ─────────────────────────────────────────────────────

    @staticmethod
    def get_standard_cost(item_dict):
        """Retorna el costo estándar definido en el item (campo costPrice)."""
        return float(item_dict.get("costPrice", 0.0) or 0.0)

    # ── MÉTODO PRINCIPAL ───────────────────────────────────────────────────

    @staticmethod
    def get_item_cost(company_id, item_id, warehouse_id, item_dict=None, method="promedio", qty=1.0, sandbox=True, owner_uid=""):
        """
        Retorna el costo unitario según el método configurado.
        - promedio: costo promedio ponderado del ledger
        - fifo: costo de la unidad más antigua
        - estandar: costPrice del item
        """
        if method == "fifo":
            ledger = InventoryCostingService.get_fifo_ledger(company_id, item_id, warehouse_id, sandbox)
            for row in ledger:
                if row["balanceQty"] > 0:
                    return row["unitCost"]
            return InventoryCostingService.get_weighted_average_cost(company_id, item_id, warehouse_id, sandbox)

        elif method == "promedio":
            return InventoryCostingService.get_weighted_average_cost(company_id, item_id, warehouse_id, sandbox)

        elif method == "estandar":
            if item_dict:
                return InventoryCostingService.get_standard_cost(item_dict)
            from app.services.db_service import DatabaseService
            items = DatabaseService.get_items(owner_uid=owner_uid, company_id=company_id, sandbox=sandbox)
            for it in items:
                if it["id"] == item_id:
                    return InventoryCostingService.get_standard_cost(it)
            return 0.0

        return InventoryCostingService.get_weighted_average_cost(company_id, item_id, warehouse_id, sandbox)

    @staticmethod
    def recalculate_item_avg_cost(company_id, item_id, warehouse_id=None, sandbox=True, owner_uid=""):
        """Recalcula y actualiza el costPrice del item usando promedio ponderado."""
        avg = InventoryCostingService.get_weighted_average_cost(company_id, item_id, warehouse_id, sandbox)
        if avg <= 0:
            return
        from app.services.db_service import DatabaseService
        items = DatabaseService.get_items(owner_uid=owner_uid, company_id=company_id, sandbox=sandbox)
        item = next((it for it in items if it["id"] == item_id), None)
        if item:
            item["costPrice"] = avg
            DatabaseService.save_item(owner_uid=owner_uid, company_id=company_id, item_id=item_id, item_dict=item, sandbox=sandbox)
