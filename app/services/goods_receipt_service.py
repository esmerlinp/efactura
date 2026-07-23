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
    def register_receipt_inventory(cls, company_id, receipt_data, sandbox=True):
        registered = []
        if DatabaseService is None:
            return registered

        po_id = receipt_data.get("purchaseOrderId", "")
        if po_id:
            try:
                po = DatabaseService.get_purchase_order(company_id, po_id, sandbox=sandbox)
                if po:
                    for item in receipt_data.get("items", []):
                        po_items = po.get("items", [])
                        po_item = next((i for i in po_items if i.get("itemId") == item.get("itemId")), None)
                        if po_item:
                            ordered_qty = float(po_item.get("quantity", 0))
                            received_qty = float(po_item.get("receivedQuantity", 0))
                            new_qty = float(item.get("receivedQuantity", 0))
                            if received_qty + new_qty > ordered_qty:
                                raise ValueError(
                                    f"Cantidad excede la orden de compra para {po_item.get('itemName','')}: "
                                    f"ordenado {ordered_qty}, recibido {received_qty}, nuevo {new_qty}"
                                )
            except Exception as e:
                if "Cantidad excede" in str(e):
                    raise
                pass

        items = receipt_data.get("items", [])
        warehouse_id = receipt_data.get("warehouseId", "")
        receipt_number = receipt_data.get("receiptNumber", "")
        performed_by = receipt_data.get("createdBy", "Sistema")

        for item in items:
            item_id = item.get("itemId", "")
            if not item_id:
                continue
            qty = float(item.get("receivedQuantity", 0))
            if qty <= 0:
                continue

            tx = {
                "type": "ENTRADA",
                "itemId": item_id,
                "itemName": item.get("itemName", item.get("poItemName", "")),
                "quantity": qty,
                "destinationWarehouseId": warehouse_id,
                "destinationWarehouseName": receipt_data.get("warehouseName", ""),
                "reason": "COMPRA",
                "referenceId": receipt_number,
                "notes": f"Recepción {receipt_number} - OC {receipt_data.get('poNumber', '')}",
                "performedBy": performed_by,
            }
            result = DatabaseService.register_inventory_transaction(company_id, tx, sandbox=sandbox)
            if result:
                registered.append(result)

            unit_cost = float(item.get("unitCost", item.get("costPrice", item.get("unitPrice", 0))) or 0)
            if unit_cost > 0:
                from app.services.inventory_costing_service import InventoryCostingService
                InventoryCostingService.record_fifo_entry(
                    company_id, item_id, warehouse_id, qty, unit_cost,
                    reference_id=receipt_number, reference_type="COMPRA",
                    sandbox=sandbox
                )
                InventoryCostingService.recalculate_item_avg_cost(
                    company_id, item_id, warehouse_id, sandbox=sandbox
                )

        return registered
