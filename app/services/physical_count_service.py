"""Servicio de conteos físicos de inventario."""

import uuid
from datetime import datetime, timezone


class PhysicalCountService:
    """Gestiona sesiones de conteo físico con snapshot y ajustes automáticos."""

    @classmethod
    def _get_coll(cls, company_id, sandbox=True):
        from app.services.db_service import db_firestore, firebase_initialized, _company_coll
        if not firebase_initialized:
            return None
        coll_name = "sandbox_physical_counts" if sandbox else "physical_counts"
        return _company_coll(company_id=company_id, coll_name=coll_name)

    @classmethod
    def get_counts(cls, company_id, sandbox=True):
        counts = []
        coll = cls._get_coll(company_id, sandbox)
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
    def get_count(cls, company_id, count_id, sandbox=True):
        coll = cls._get_coll(company_id, sandbox)
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
    def start_count(cls, company_id, warehouse_id, warehouse_name, started_by, sandbox=True, owner_uid=""):
        """Inicia un conteo físico y toma snapshot del stock actual."""
        from app.services.db_service import DatabaseService

        items = DatabaseService.get_items(owner_uid=owner_uid, company_id=company_id, sandbox=sandbox)
        goods = [it for it in items if it.get("type", "Bien") == "Bien"]
        stocks = DatabaseService.get_inventory_stock(owner_uid=owner_uid, company_id=company_id, sandbox=sandbox)

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

        coll = cls._get_coll(company_id, sandbox)
        if coll:
            coll.document(count_id).set(data)
        return count_id

    @classmethod
    def save_count_lines(cls, company_id, count_id, qty_map, sandbox=True):
        """Persiste las cantidades contadas de varias líneas en una sola lectura/escritura.

        qty_map: {itemId: counted_qty}. Solo actualiza las líneas presentes en el mapa.
        """
        count = cls.get_count(company_id, count_id, sandbox)
        if not count or count["status"] != "en_progreso":
            return False

        for line in count["lines"]:
            item_id = line["itemId"]
            if item_id in qty_map:
                counted_qty = float(qty_map[item_id])
                line["countedQty"] = counted_qty
                line["difference"] = round(counted_qty - line["expectedQty"], 4)

        coll = cls._get_coll(company_id, sandbox)
        if coll:
            coll.document(count_id).set(count)
        return True

    @classmethod
    def record_count_line(cls, company_id, count_id, item_id, counted_qty, notes="", sandbox=True):
        """Actualiza una línea de conteo con la cantidad contada."""
        count = cls.get_count(company_id, count_id, sandbox)
        if not count or count["status"] != "en_progreso":
            return False

        for line in count["lines"]:
            if line["itemId"] == item_id:
                line["countedQty"] = counted_qty
                line["difference"] = round(counted_qty - line["expectedQty"], 4)
                if notes:
                    line["notes"] = notes
                break

        coll = cls._get_coll(company_id, sandbox)
        if coll:
            coll.document(count_id).set(count)
        return True

    @classmethod
    def finalize_count(cls, company_id, count_id, finalized_by, tolerance=0.01, sandbox=True, owner_uid=""):
        """
        Finaliza el conteo y genera ajustes automáticos para diferencias > tolerancia.
        Retorna (success, summary_dict).
        """
        from app.services.db_service import DatabaseService

        count = cls.get_count(company_id, count_id, sandbox)
        if not count or count["status"] != "en_progreso":
            return False, "Conteo no encontrado o ya finalizado."

        # Cada finalización usa un intento incremental; permite re-finalizar tras una reapertura
        # sin que la idempotencia devuelva los movimientos ya revertidos.
        attempt = int(count.get("finalizeAttempt", 0) or 0) + 1

        surplus = 0.0
        shortage = 0.0
        lines_with_diff = 0
        adjustments = 0
        adjusted_items = []

        from app.services.inventory_transaction_service import InventoryTransactionService
        items_catalog = DatabaseService.get_items(owner_uid=owner_uid, company_id=company_id, sandbox=sandbox)
        item_cost_map = {it.get("id"): float(it.get("costPrice", 0.0) or 0.0) for it in items_catalog}

        for line in count["lines"]:
            if "countedQty" in line and "expectedQty" in line:
                diff = round(float(line.get("countedQty", 0.0) or 0.0) - float(line.get("expectedQty", 0.0) or 0.0), 4)
                line["difference"] = diff
            else:
                diff = float(line.get("difference", 0.0) or 0.0)
            if abs(diff) > tolerance:
                lines_with_diff += 1
                if diff > 0:
                    surplus += diff
                else:
                    shortage += abs(diff)
                adjustments += 1

                item_id = line["itemId"]
                unit_cost = item_cost_map.get(item_id, float(line.get("costPrice", 0.0) or 0.0))
                tx_type = InventoryTransactionService.TYPE_ENTRADA if diff > 0 else InventoryTransactionService.TYPE_SALIDA

                idempotency_key = InventoryTransactionService.build_idempotency_key(
                    company_id=company_id,
                    reference_type="PHYSICAL_COUNT",
                    reference_id=f"{count_id}_{item_id}_v{attempt}",
                    operation=tx_type
                )

                res_tx = InventoryTransactionService.execute_transaction(
                    owner_uid=owner_uid,
                    company_id=company_id,
                    tx_dict={
                        "type": tx_type,
                        "itemId": item_id,
                        "itemName": line["itemName"],
                        "quantity": abs(diff),
                        "unitCost": unit_cost,
                        "destinationWarehouseId": count["warehouseId"] if diff > 0 else "",
                        "originWarehouseId": count["warehouseId"] if diff <= 0 else "",
                        "reason": InventoryTransactionService.REASON_AJUSTE_FISICO,
                        "referenceType": "PHYSICAL_COUNT",
                        "referenceId": count_id,
                        "idempotencyKey": idempotency_key,
                        "metadata": {"finalizeAttempt": attempt},
                        "notes": f"Ajuste automático: conteo #{count_id[:8]}, diferencia {diff:+.4f}",
                        "performedBy": finalized_by,
                    },
                    sandbox=sandbox,
                    allow_negative_stock=True  # Conteo físico refleja la realidad física ajustada
                )

                # ── Post-Commit Contable: Contabilizar Ajuste Físico / Merma ──
                if res_tx:
                    try:
                        from app.services.inventory_accounting_service import InventoryAccountingService
                        InventoryAccountingService.post_inventory_transaction(
                            company_id=company_id,
                            tx=res_tx,
                            sandbox=sandbox,
                            owner_uid=owner_uid
                        )
                    except Exception as acc_err:
                        print(f"⚠️ Error al contabilizar ajuste de conteo físico {count_id}: {acc_err}")

                adjusted_items.append({
                    "itemId": line["itemId"],
                    "name": line["itemName"],
                    "quantity": diff,
                    "qtyDiff": diff,
                    "costPrice": unit_cost,
                })


        count["status"] = "ajustado" if adjustments > 0 else "finalizado"
        count["finalizedDate"] = datetime.now(timezone.utc).isoformat()
        count["finalizedBy"] = finalized_by
        count["finalizeAttempt"] = attempt
        count["linesWithDifference"] = lines_with_diff
        count["totalSurplus"] = round(surplus, 2)
        count["totalShortage"] = round(shortage, 2)

        coll = cls._get_coll(company_id, sandbox)
        if coll:
            coll.document(count_id).set(count)

        return True, {
            "totalLines": len(count["lines"]),
            "linesWithDifference": lines_with_diff,
            "totalSurplus": round(surplus, 2),
            "totalShortage": round(shortage, 2),
            "adjustments": adjustments,
        }

    @classmethod
    def reopen_count(cls, company_id, count_id, reopened_by="", sandbox=True, owner_uid=""):
        """Reabre un conteo finalizado/ajustado revirtiendo sus ajustes de inventario y contabilidad.

        Crea una transacción compensatoria por cada movimiento del último cierre del conteo,
        la contabiliza (asiento inverso) y devuelve el conteo a estado 'en_progreso' para
        permitir corregir las cantidades contadas.
        Retorna (success, summary_dict | error_message).
        """
        from app.services.inventory_transaction_service import InventoryTransactionService
        from app.services.inventory_accounting_service import InventoryAccountingService
        from app.services.db_service import _company_coll

        count = cls.get_count(company_id, count_id, sandbox)
        if not count:
            return False, "Conteo no encontrado."
        if count.get("status") not in ("finalizado", "ajustado"):
            return False, "Solo se pueden reabrir conteos finalizados o ajustados."

        target_attempt = int(count.get("finalizeAttempt", 0) or 0)

        coll_name = "sandbox_inventory_transactions" if sandbox else "inventory_transactions"
        try:
            docs = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=coll_name).get()
        except Exception as e:
            return False, f"No se pudieron leer las transacciones del conteo: {e}"

        reversed_count = 0
        for doc in docs:
            tx = doc.to_dict() or {}
            if tx.get("referenceType") != "PHYSICAL_COUNT":
                continue
            if str(tx.get("referenceId", "")) != str(count_id):
                continue
            meta = tx.get("metadata") or {}
            if int(meta.get("finalizeAttempt", 0) or 0) != target_attempt:
                continue

            tx_type = (tx.get("type") or "").upper()
            if tx_type not in (InventoryTransactionService.TYPE_ENTRADA, InventoryTransactionService.TYPE_SALIDA):
                continue

            item_id = tx.get("itemId")
            qty = float(tx.get("quantity", 0.0) or 0.0)
            wh_id = tx.get("destinationWarehouseId") if tx_type == InventoryTransactionService.TYPE_ENTRADA \
                else tx.get("originWarehouseId")
            if not item_id or qty <= 0 or not wh_id:
                continue

            rev_type = InventoryTransactionService.TYPE_SALIDA if tx_type == InventoryTransactionService.TYPE_ENTRADA \
                else InventoryTransactionService.TYPE_ENTRADA

            rev_dict = {
                "type": rev_type,
                "itemId": item_id,
                "itemName": tx.get("itemName", ""),
                "itemCode": tx.get("itemCode", ""),
                "quantity": qty,
                "unitCost": float(tx.get("unitCost", 0.0) or 0.0),
                "reason": InventoryTransactionService.REASON_AJUSTE_FISICO_REVERSAL,
                "referenceType": "PHYSICAL_COUNT_REOPEN",
                "referenceId": count_id,
                "destinationWarehouseId": wh_id if rev_type == InventoryTransactionService.TYPE_ENTRADA else "",
                "originWarehouseId": wh_id if rev_type == InventoryTransactionService.TYPE_SALIDA else "",
                "idempotencyKey": InventoryTransactionService.build_idempotency_key(
                    company_id=company_id,
                    reference_type="PHYSICAL_COUNT_REOPEN",
                    reference_id=f"{count_id}_{item_id}_v{target_attempt}",
                    operation=rev_type,
                ),
                "metadata": {"finalizeAttempt": target_attempt, "reversedTxId": tx.get("id")},
                "notes": f"Reapertura de conteo #{count_id[:8]}: reverso de ajuste {tx_type}",
                "performedBy": reopened_by or "Sistema",
            }

            try:
                res_tx = InventoryTransactionService.execute_transaction(
                    owner_uid=owner_uid,
                    company_id=company_id,
                    tx_dict=rev_dict,
                    sandbox=sandbox,
                    allow_negative_stock=True,
                )
            except Exception as e:
                return False, f"Error al revertir la transacción {tx.get('id')}: {e}"

            if res_tx:
                try:
                    InventoryAccountingService.post_inventory_transaction(
                        company_id=company_id,
                        tx=res_tx,
                        sandbox=sandbox,
                        owner_uid=owner_uid,
                    )
                except Exception as acc_err:
                    print(f"⚠️ Error al contabilizar reverso de conteo {count_id}: {acc_err}")
                reversed_count += 1

        count["status"] = "en_progreso"
        count["finalizedDate"] = ""
        count["finalizedBy"] = ""
        count["linesWithDifference"] = 0
        count["totalSurplus"] = 0.0
        count["totalShortage"] = 0.0

        coll = cls._get_coll(company_id, sandbox)
        if coll:
            coll.document(count_id).set(count)

        return True, {
            "reversedTransactions": reversed_count,
            "status": "en_progreso",
        }
