"""Servicio de costeo de inventario: FIFO, Promedio Ponderado y Costo Estándar."""

from datetime import datetime, timezone
from typing import Optional


class InventoryCostingService:
    """Calcula y registra costos de inventario por método de costeo."""

    # ── FIFO LEDGER ────────────────────────────────────────────────────────

    @staticmethod
    def get_fifo_ledger(owner_uid, item_id, warehouse_id=None, sandbox=True):
        """Retorna el libro FIFO ordenado por fecha ASC para un item."""
        from app.services.db_service import DatabaseService, db_firestore, firebase_initialized
        rows = []
        if not firebase_initialized:
            return rows
        coll = "sandbox_inventory_cost_ledger" if sandbox else "inventory_cost_ledger"
        try:
            query = db_firestore.collection("users").document(owner_uid).collection(coll)
            docs = query.where("itemId", "==", item_id).get()
            for doc in docs:
                data = doc.to_dict()
                if warehouse_id and data.get("warehouseId") != warehouse_id:
                    continue
                rows.append({
                    "id": doc.id,
                    "itemId": data.get("itemId", ""),
                    "warehouseId": data.get("warehouseId", ""),
                    "date": data.get("date", ""),
                    "qtyIn": float(data.get("qtyIn", 0)),
                    "unitCost": float(data.get("unitCost", 0)),
                    "qtyOut": float(data.get("qtyOut", 0)),
                    "balanceQty": float(data.get("balanceQty", 0)),
                    "referenceId": data.get("referenceId", ""),
                    "referenceType": data.get("referenceType", ""),
                })
            rows.sort(key=lambda r: r["date"])
        except Exception as e:
            print(f"⚠️ Error al leer libro FIFO: {e}")
        return rows

    @staticmethod
    def get_fifo_cost(item_id, warehouse_id, qty_needed, owner_uid, sandbox=True):
        """
        Calcula el costo usando FIFO para una cantidad solicitada.
        Retorna (costo_total, lotes_consumidos).
        lotes_consumidos es lista de {ledger_id, qty_consumed, unit_cost} para actualizar el ledger.
        """
        ledger = InventoryCostingService.get_fifo_ledger(owner_uid, item_id, warehouse_id, sandbox)
        total_cost = 0.0
        remaining = qty_needed
        consumed = []

        for row in ledger:
            available = row["balanceQty"]
            if available <= 0:
                continue
            take = min(remaining, available)
            total_cost += take * row["unitCost"]
            consumed.append({
                "ledger_id": row["id"],
                "qty_consumed": take,
                "unit_cost": row["unitCost"],
            })
            remaining -= take
            if remaining <= 0:
                break

        if remaining > 0:
            # Si no hay suficiente en el ledger, usar el costo más reciente o 0
            last_cost = ledger[-1]["unitCost"] if ledger else 0.0
            total_cost += remaining * last_cost

        return round(total_cost, 2), consumed

    @staticmethod
    def record_fifo_entry(owner_uid, item_id, warehouse_id, qty_in, unit_cost, reference_id="", reference_type="", sandbox=True):
        """Registra una entrada en el libro FIFO."""
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return None
        coll = "sandbox_inventory_cost_ledger" if sandbox else "inventory_cost_ledger"
        import uuid
        entry_id = str(uuid.uuid4())
        data = {
            "id": entry_id,
            "itemId": item_id,
            "warehouseId": warehouse_id,
            "date": datetime.now(timezone.utc).isoformat(),
            "qtyIn": qty_in,
            "unitCost": unit_cost,
            "qtyOut": 0.0,
            "balanceQty": qty_in,
            "referenceId": reference_id,
            "referenceType": reference_type,
        }
        try:
            db_firestore.collection("users").document(owner_uid).collection(coll).document(entry_id).set(data)
            return entry_id
        except Exception as e:
            print(f"⚠️ Error al registrar entrada FIFO: {e}")
            return None

    @staticmethod
    def apply_fifo_consumption(owner_uid, consumed_batches, sandbox=True):
        """Aplica el consumo de lotes FIFO actualizando qtyOut y balanceQty."""
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized or not consumed_batches:
            return
        coll = "sandbox_inventory_cost_ledger" if sandbox else "inventory_cost_ledger"
        try:
            for batch in consumed_batches:
                ref = db_firestore.collection("users").document(owner_uid).collection(coll).document(batch["ledger_id"])
                doc = ref.get()
                if doc.exists:
                    data = doc.to_dict()
                    new_qty_out = float(data.get("qtyOut", 0)) + batch["qty_consumed"]
                    new_balance = float(data.get("balanceQty", 0)) - batch["qty_consumed"]
                    ref.update({"qtyOut": new_qty_out, "balanceQty": max(0, new_balance)})
        except Exception as e:
            print(f"⚠️ Error al aplicar consumo FIFO: {e}")

    # ── PROMEDIO PONDERADO ─────────────────────────────────────────────────

    @staticmethod
    def get_weighted_average_cost(owner_uid, item_id, warehouse_id=None, sandbox=True):
        """
        Calcula el costo promedio ponderado para un item.
        Usa el libro de costos (ledger) para calcular: Σ(qty_in × unit_cost) / Σ(qty_in).
        """
        ledger = InventoryCostingService.get_fifo_ledger(owner_uid, item_id, warehouse_id, sandbox)
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
    def get_item_cost(owner_uid, item_id, warehouse_id, item_dict=None, method="promedio", qty=1.0, sandbox=True):
        """
        Retorna el costo unitario según el método configurado.
        - promedio: costo promedio ponderado del ledger
        - fifo: costo de la unidad más antigua
        - estandar: costPrice del item
        """
        if method == "fifo":
            # Costo unitario promedio de la capa más antigua con balance
            ledger = InventoryCostingService.get_fifo_ledger(owner_uid, item_id, warehouse_id, sandbox)
            for row in ledger:
                if row["balanceQty"] > 0:
                    return row["unitCost"]
            return InventoryCostingService.get_weighted_average_cost(owner_uid, item_id, warehouse_id, sandbox)

        elif method == "promedio":
            return InventoryCostingService.get_weighted_average_cost(owner_uid, item_id, warehouse_id, sandbox)

        elif method == "estandar":
            if item_dict:
                return InventoryCostingService.get_standard_cost(item_dict)
            from app.services.db_service import DatabaseService
            items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
            for it in items:
                if it["id"] == item_id:
                    return InventoryCostingService.get_standard_cost(it)
            return 0.0

        # Default: promedio
        return InventoryCostingService.get_weighted_average_cost(owner_uid, item_id, warehouse_id, sandbox)

    @staticmethod
    def recalculate_item_avg_cost(owner_uid, item_id, warehouse_id=None, sandbox=True):
        """Recalcula y actualiza el costPrice del item usando promedio ponderado."""
        avg = InventoryCostingService.get_weighted_average_cost(owner_uid, item_id, warehouse_id, sandbox)
        if avg <= 0:
            return
        from app.services.db_service import DatabaseService
        items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
        item = next((it for it in items if it["id"] == item_id), None)
        if item:
            item["costPrice"] = avg
            DatabaseService.save_item(owner_uid, item_id, item, sandbox=sandbox)
