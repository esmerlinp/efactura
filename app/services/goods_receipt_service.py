import uuid
import re
from datetime import datetime, timezone

try:
    from app.services.db_service import db_firestore, firebase_initialized, DatabaseService, _company_coll
except ImportError:
    db_firestore = None
    firebase_initialized = False
    DatabaseService = None
    _company_coll = None

try:
    from app.services.purchase_order_service import PurchaseOrderService
except ImportError:
    PurchaseOrderService = None


def serialize_field(val):
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    return str(val)


class GoodsReceiptService:

    @classmethod
    def get_receipts(cls, company_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return []
        receipts = []
        try:
            coll_name = "sandbox_goods_receipts" if sandbox else "goods_receipts"
            docs = _company_coll(company_id=company_id, coll_name=coll_name).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                receipts.append(data)
            receipts.sort(key=lambda x: x.get("receiptNumber", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener recepciones: {e}")
        return receipts

    @classmethod
    def get_receipt(cls, company_id, receipt_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            coll_name = "sandbox_goods_receipts" if sandbox else "goods_receipts"
            doc = _company_coll(company_id=company_id, coll_name=coll_name).document(receipt_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener recepción {receipt_id}: {e}")
        return None

    @classmethod
    def get_receipts_by_po(cls, company_id, po_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return []
        receipts = []
        try:
            coll_name = "sandbox_goods_receipts" if sandbox else "goods_receipts"
            docs = _company_coll(company_id=company_id, coll_name=coll_name)\
                .where("poId", "==", po_id).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                receipts.append(data)
            receipts.sort(key=lambda x: x.get("createdAt", ""))
        except Exception as e:
            print(f"⚠️ Error al obtener recepciones de OC {po_id}: {e}")
        return receipts

    @classmethod
    def get_next_receipt_number(cls, company_id, sandbox=True):
        year = datetime.now(timezone.utc).strftime("%Y")
        max_num = 0
        receipts = cls.get_receipts(company_id, sandbox=sandbox)
        for r in receipts:
            rn = r.get("receiptNumber", "")
            m = re.match(rf"^RC-{year}-(\d{{4}})$", rn)
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
        return f"RC-{year}-{max_num + 1:04d}"

    @classmethod
    def create_receipt(cls, company_id, receipt_data, sandbox=True):
        receipt_id = str(uuid.uuid4())
        receipt_data["id"] = receipt_id
        receipt_data["ownerUID"] = company_id
        if "createdAt" not in receipt_data or not receipt_data["createdAt"]:
            receipt_data["createdAt"] = serialize_field(datetime.now(timezone.utc))
        receipt_data["updatedAt"] = serialize_field(datetime.now(timezone.utc))

        defaults = {
            "status": "completada",
            "notes": "",
        }
        for k, v in defaults.items():
            if k not in receipt_data:
                receipt_data[k] = v

        coll_name = "sandbox_goods_receipts" if sandbox else "goods_receipts"
        if firebase_initialized and db_firestore is not None:
            try:
                _company_coll(company_id=company_id, coll_name=coll_name).document(receipt_id).set(
                    receipt_data
                )
            except Exception as e:
                print(f"⚠️ Error al guardar recepción en Firestore: {e}")

        return receipt_data

    @classmethod
    def validate_receipt(cls, company_id, receipt_data, sandbox=True, owner_uid=""):
        """Valida un recibo ANTES de persistir nada.

        Reúne todos los errores (no aborta en el primero) y lanza un único
        ValueError con el detalle. Incluye:
          - almacén de destino obligatorio,
          - al menos una partida con cantidad > 0,
          - cada partida recibida debe tener ítem de catálogo asociado,
          - la cantidad recibida no puede exceder el saldo de la orden de compra.
        """
        errors = []

        warehouse_id = (receipt_data.get("warehouseId") or "").strip()
        if not warehouse_id:
            errors.append("Debe seleccionar un almacén de destino.")

        items = receipt_data.get("items", [])
        if not items:
            errors.append("Debe indicar al menos una partida con cantidad mayor a 0.")

        for item in items:
            label = item.get("poItemName") or item.get("itemName") or "—"
            item_id = (item.get("itemId") or "").strip()
            if not item_id:
                errors.append(f"La partida '{label}' no tiene ítem de catálogo asociado.")
                continue

            rqty = float(item.get("receivedQuantity", 0) or 0)
            if rqty <= 0:
                continue

            # Verificación de control por lotes
            track_lots = item.get("trackLots")
            if track_lots is None and firebase_initialized and db_firestore is not None:
                try:
                    coll_name = "sandbox_items" if sandbox else "items"
                    item_doc = _company_coll(company_id=company_id, coll_name=coll_name).document(item_id).get()
                    if getattr(item_doc, "exists", False) is True:
                        doc_data = item_doc.to_dict()
                        if isinstance(doc_data, dict):
                            track_lots = bool(doc_data.get("trackLots", False))
                        else:
                            track_lots = False
                    else:
                        track_lots = False
                except Exception:
                    track_lots = False
            track_lots = bool(track_lots)

            if track_lots:
                lot_id = (item.get("lotId") or "").strip()
                lot_number = (item.get("lotNumber") or "").strip()
                if not lot_id and not lot_number:
                    errors.append(
                        f"La partida '{label}' requiere control por lotes. Debe indicar un número de lote o seleccionar uno existente."
                    )
                prod_date = (item.get("productionDate") or "").strip()
                exp_date = (item.get("expirationDate") or "").strip()
                if prod_date and exp_date and exp_date < prod_date:
                    errors.append(
                        f"En la partida '{label}', la fecha de vencimiento ({exp_date}) no puede ser anterior a la de producción ({prod_date})."
                    )

        po_id = receipt_data.get("poId") or receipt_data.get("purchaseOrderId") or ""
        if po_id and PurchaseOrderService is not None:
            po = PurchaseOrderService.get_purchase_order(
                owner_uid=owner_uid, po_id=po_id, sandbox=sandbox, company_id=company_id
            )
            if po:
                po_items = po.get("items", [])
                for item in items:
                    line_id = item.get("poItemId") or item.get("id") or ""
                    po_item = next((i for i in po_items if i.get("id") == line_id), None)
                    if not po_item:
                        errors.append(
                            f"La partida '{item.get('poItemName') or item.get('itemName') or '—'}' "
                            "no pertenece a la orden de compra."
                        )
                        continue
                    ordered_qty = float(po_item.get("quantity", 0))
                    received_qty = float(po_item.get("receivedQuantity", 0))
                    new_qty = float(item.get("receivedQuantity", 0))
                    if received_qty + new_qty > ordered_qty + 1e-9:
                        errors.append(
                            f"Cantidad excede la orden de compra para "
                            f"{po_item.get('name', po_item.get('itemName', ''))}: "
                            f"ordenado {ordered_qty}, recibido {received_qty}, nuevo {new_qty}."
                        )

        if errors:
            raise ValueError(" ".join(errors))
        return True

    @classmethod
    def delete_receipt(cls, company_id, receipt_id, sandbox=True):
        if not firebase_initialized or db_firestore is None or not receipt_id:
            return
        try:
            coll_name = "sandbox_goods_receipts" if sandbox else "goods_receipts"
            _company_coll(company_id=company_id, coll_name=coll_name).document(receipt_id).delete()
        except Exception as e:
            print(f"⚠️ Error al eliminar recepción {receipt_id}: {e}")

    @classmethod
    def reverse_registered_transactions(cls, company_id, registered, sandbox=True, owner_uid=""):
        """Compensa (revierte) las transacciones ENTRADA ya aplicadas de un recibo.

        Se usa cuando el registro de inventario falla a mitad de camino: se
        emite una SALIDA por cada ENTRADA aplicada para no dejar stock fantasma.
        """
        from app.services.inventory_transaction_service import InventoryTransactionService

        reversed_count = 0
        for tx in registered or []:
            try:
                dest_wh = tx.get("destinationWarehouseId", "")
                qty = float(tx.get("quantity", 0))
                if qty <= 0 or not dest_wh or not tx.get("itemId"):
                    continue
                rev = {
                    "type": InventoryTransactionService.TYPE_SALIDA,
                    "itemId": tx.get("itemId"),
                    "itemName": tx.get("itemName", ""),
                    "quantity": qty,
                    "originWarehouseId": dest_wh,
                    "reason": InventoryTransactionService.REASON_DEVOLUCION_PROVEEDOR,
                    "referenceType": "GOODS_RECEIPT_ROLLBACK",
                    "referenceId": str(tx.get("id", "")),
                    "idempotencyKey": InventoryTransactionService.build_idempotency_key(
                        company_id=company_id,
                        reference_type="GOODS_RECEIPT_ROLLBACK",
                        reference_id=str(tx.get("id", "")),
                        operation="ROLLBACK",
                    ),
                    "notes": f"Reversión automática de recepción {tx.get('referenceId', '')}",
                    "performedBy": tx.get("performedBy", "Sistema"),
                    "lotId": (tx.get("lotId") or "").strip(),
                    "lotNumber": (tx.get("lotNumber") or "").strip(),
                    "allowNegativeStock": True,
                }
                InventoryTransactionService.execute_transaction(
                    owner_uid=owner_uid, company_id=company_id, tx_dict=rev, sandbox=sandbox
                )
                reversed_count += 1
            except Exception as rev_err:
                print(f"⚠️ Error al revertir transacción {tx.get('id')}: {rev_err}")
        return reversed_count

    @classmethod
    def register_receipt_inventory(cls, company_id, receipt_data, sandbox=True, owner_uid=""):
        registered = []
        if DatabaseService is None:
            return registered

        po_id = receipt_data.get("poId") or receipt_data.get("purchaseOrderId") or ""
        po = None
        if po_id and PurchaseOrderService is not None:
            po = PurchaseOrderService.get_purchase_order(
                owner_uid=owner_uid, po_id=po_id, sandbox=sandbox, company_id=company_id
            )
        if po:
            po_items = po.get("items", [])
            for item in receipt_data.get("items", []):
                line_id = item.get("poItemId") or item.get("id") or ""
                po_item = next((i for i in po_items if i.get("id") == line_id), None)
                if not po_item:
                    continue
                ordered_qty = float(po_item.get("quantity", 0))
                received_qty = float(po_item.get("receivedQuantity", 0))
                new_qty = float(item.get("receivedQuantity", 0))
                if received_qty + new_qty > ordered_qty + 1e-9:
                    raise ValueError(
                        f"Cantidad excede la orden de compra para {po_item.get('name', po_item.get('itemName',''))}: "
                        f"ordenado {ordered_qty}, recibido {received_qty}, nuevo {new_qty}"
                    )

        items = receipt_data.get("items", [])
        warehouse_id = receipt_data.get("warehouseId", "")
        receipt_number = receipt_data.get("receiptNumber", "")
        receipt_id = receipt_data.get("id", receipt_number)
        performed_by = receipt_data.get("createdBy", "Sistema")

        from app.services.inventory_transaction_service import InventoryTransactionService
        from app.services.inventory_costing_service import InventoryCostingService

        for item in items:
            item_id = item.get("itemId", "")
            if not item_id:
                continue
            qty = float(item.get("receivedQuantity", 0))
            if qty <= 0:
                continue

            unit_cost = float(item.get("unitCost", item.get("costPrice", item.get("unitPrice", 0))) or 0)
            line_ref = item.get("poItemId") or item.get("id") or item_id
            idempotency_key = InventoryTransactionService.build_idempotency_key(
                company_id=company_id,
                reference_type="GOODS_RECEIPT",
                reference_id=f"{receipt_id}_{line_ref}",
                operation="ENTRADA"
            )

            tx = {
                "type": InventoryTransactionService.TYPE_ENTRADA,
                "itemId": item_id,
                "itemName": item.get("itemName", item.get("poItemName", "")),
                "quantity": qty,
                "unitCost": unit_cost,
                "destinationWarehouseId": warehouse_id,
                "destinationWarehouseName": receipt_data.get("warehouseName", ""),
                "reason": InventoryTransactionService.REASON_COMPRA,
                "referenceType": "GOODS_RECEIPT",
                "referenceId": receipt_number or receipt_id,
                "idempotencyKey": idempotency_key,
                "notes": f"Recepción {receipt_number} - OC {receipt_data.get('poNumber', '')}",
                "performedBy": performed_by,
                "lotId": (item.get("lotId") or "").strip(),
                "lotNumber": (item.get("lotNumber") or "").strip(),
                "productionDate": (item.get("productionDate") or "").strip(),
                "expirationDate": (item.get("expirationDate") or "").strip(),
                "lotNotes": (item.get("lotNotes") or "").strip(),
            }
            result = InventoryTransactionService.execute_transaction(
                owner_uid=owner_uid,
                company_id=company_id,
                tx_dict=tx,
                sandbox=sandbox
            )
            if result:
                registered.append(result)

            if unit_cost > 0:
                InventoryCostingService.recalculate_item_avg_cost(
                    company_id, item_id, warehouse_id, sandbox=sandbox, owner_uid=owner_uid
                )

        # ── Post-Commit Contable: Contabilizar Recepción de Mercancías ──
        from app.services.inventory_accounting_service import InventoryAccountingService
        for tx_result in registered:
            try:
                InventoryAccountingService.post_inventory_transaction(
                    company_id=company_id,
                    tx=tx_result,
                    sandbox=sandbox,
                    owner_uid=owner_uid
                )
            except Exception as acc_err:
                print(f"⚠️ Error al contabilizar recepción de mercancía {tx_result.get('id')}: {acc_err}")

        return registered

