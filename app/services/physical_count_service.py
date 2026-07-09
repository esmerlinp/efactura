"""Servicio de conteos físicos de inventario."""

import uuid
from datetime import datetime, timezone


class PhysicalCountService:
    """Gestiona sesiones de conteo físico con snapshot y ajustes automáticos."""

    @classmethod
    def _get_coll(cls, owner_uid, sandbox=True):
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return None
        coll_name = "sandbox_physical_counts" if sandbox else "physical_counts"
        return db_firestore.collection("users").document(owner_uid).collection(coll_name)

    @classmethod
    def get_counts(cls, owner_uid, sandbox=True):
        counts = []
        coll = cls._get_coll(owner_uid, sandbox)
        if not coll:
            return counts
        try:
            docs = coll.get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                counts.append(data)
            counts.sort(key=lambda c: c.get("startedDate", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener conteos: {e}")
        return counts

    @classmethod
    def get_count(cls, owner_uid, count_id, sandbox=True):
        coll = cls._get_coll(owner_uid, sandbox)
        if not coll:
            return None
        try:
            doc = coll.document(count_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener conteo: {e}")
        return None

    @classmethod
    def start_count(cls, owner_uid, warehouse_id, warehouse_name, started_by, sandbox=True):
        """Inicia un conteo físico y toma snapshot del stock actual."""
        from app.services.db_service import DatabaseService

        items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
        goods = [it for it in items if it.get("type", "Bien") == "Bien"]
        stocks = DatabaseService.get_inventory_stock(owner_uid, sandbox=sandbox)

        # Snapshot: stock esperado por item en este almacén
        lines = []
        stock_map = {}
        for st in stocks:
            if st["warehouseId"] == warehouse_id:
                stock_map[st["itemId"]] = st["quantity"]

        for item in goods:
            expected = stock_map.get(item["id"], 0.0)
            lines.append({
                "itemId": item["id"],
                "itemName": item["name"],
                "lotId": "",
                "lotNumber": "",
                "expectedQty": expected,
                "countedQty": 0.0,
                "difference": 0.0,
                "notes": "",
            })

        count_id = str(uuid.uuid4())
        data = {
            "id": count_id,
            "warehouseId": warehouse_id,
            "warehouseName": warehouse_name,
            "status": "en_progreso",
            "startedBy": started_by,
            "startedDate": datetime.now(timezone.utc).isoformat(),
            "finalizedDate": "",
            "finalizedBy": "",
            "notes": "",
            "lines": lines,
            "totalLines": len(lines),
            "linesWithDifference": 0,
            "totalSurplus": 0.0,
            "totalShortage": 0.0,
        }

        coll = cls._get_coll(owner_uid, sandbox)
        if coll:
            coll.document(count_id).set(data)
        return count_id

    @classmethod
    def record_count_line(cls, owner_uid, count_id, item_id, counted_qty, notes="", sandbox=True):
        """Actualiza una línea de conteo con la cantidad contada."""
        count = cls.get_count(owner_uid, count_id, sandbox)
        if not count or count["status"] != "en_progreso":
            return False

        for line in count["lines"]:
            if line["itemId"] == item_id:
                line["countedQty"] = counted_qty
                line["difference"] = round(counted_qty - line["expectedQty"], 4)
                if notes:
                    line["notes"] = notes
                break

        coll = cls._get_coll(owner_uid, sandbox)
        if coll:
            coll.document(count_id).set(count)
        return True

    @classmethod
    def finalize_count(cls, owner_uid, count_id, finalized_by, tolerance=0.01, sandbox=True):
        """
        Finaliza el conteo y genera ajustes automáticos para diferencias > tolerancia.
        Retorna (success, summary_dict).
        """
        from app.services.db_service import DatabaseService

        count = cls.get_count(owner_uid, count_id, sandbox)
        if not count or count["status"] != "en_progreso":
            return False, "Conteo no encontrado o ya finalizado."

        surplus = 0.0
        shortage = 0.0
        lines_with_diff = 0
        adjustments = 0
        adjusted_items = []

        for line in count["lines"]:
            diff = line["difference"]
            if abs(diff) > tolerance:
                lines_with_diff += 1
                if diff > 0:
                    surplus += diff
                else:
                    shortage += abs(diff)
                adjustments += 1

                # Generar ajuste automático
                tx_type = "ENTRADA" if diff > 0 else "SALIDA"
                DatabaseService.register_inventory_transaction(owner_uid, {
                    "type": tx_type,
                    "itemId": line["itemId"],
                    "itemName": line["itemName"],
                    "quantity": abs(diff),
                    "destinationWarehouseId": count["warehouseId"] if diff > 0 else "",
                    "originWarehouseId": count["warehouseId"] if diff <= 0 else "",
                    "reason": "AJUSTE_POR_CONTEO",
                    "referenceId": count_id,
                    "notes": f"Ajuste automático: conteo #{count_id[:8]}, diferencia {diff:+.4f}",
                    "performedBy": finalized_by,
                }, sandbox=sandbox)

                adjusted_items.append({
                    "itemId": line["itemId"],
                    "name": line["itemName"],
                    "quantity": diff,
                    "qtyDiff": diff,
                    "costPrice": 0,
                })

        if adjusted_items:
            try:
                from app.services.accounting_service import AccountingService
                AccountingService.auto_generate_inventory_entry(
                    owner_uid, "ajuste", adjusted_items,
                    reference_id=count_id, performed_by=finalized_by,
                    sandbox=sandbox
                )
            except Exception as e:
                print(f"⚠️ Error al generar asiento de inventario para conteo {count_id}: {e}")

        count["status"] = "ajustado" if adjustments > 0 else "finalizado"
        count["finalizedDate"] = datetime.now(timezone.utc).isoformat()
        count["finalizedBy"] = finalized_by
        count["linesWithDifference"] = lines_with_diff
        count["totalSurplus"] = round(surplus, 2)
        count["totalShortage"] = round(shortage, 2)

        coll = cls._get_coll(owner_uid, sandbox)
        if coll:
            coll.document(count_id).set(count)

        return True, {
            "totalLines": len(count["lines"]),
            "linesWithDifference": lines_with_diff,
            "totalSurplus": round(surplus, 2),
            "totalShortage": round(shortage, 2),
            "adjustments": adjustments,
        }
