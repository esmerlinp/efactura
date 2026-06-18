import uuid
import re
from datetime import datetime

try:
    from app.services.db_service import db_firestore, firebase_initialized
except ImportError:
    db_firestore = None
    firebase_initialized = False


def serialize_field(val):
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    return str(val)


PO_STATUSES = [
    "borrador",
    "pendiente_aprobacion",
    "aprobada",
    "rechazada",
    "recibida_parcial",
    "recibida_completa",
    "cancelada",
]

PAYMENT_TERMS = [
    ("contado", "Contado"),
    ("credito_15d", "Crédito 15 Días"),
    ("credito_30d", "Crédito 30 Días"),
    ("credito_45d", "Crédito 45 Días"),
    ("credito_60d", "Crédito 60 Días"),
    ("credito_90d", "Crédito 90 Días"),
]

CURRENCIES = ["DOP", "USD", "EUR"]


class PurchaseOrderService:

    @classmethod
    def get_purchase_orders(cls, owner_uid, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return []
        orders = []
        try:
            coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
            docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                orders.append(data)
            orders.sort(key=lambda x: x.get("poNumber", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener órdenes de compra: {e}")
        return orders

    @classmethod
    def get_purchase_order(cls, owner_uid, po_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
            doc = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(po_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener orden de compra {po_id}: {e}")
        return None

    @classmethod
    def save_purchase_order(cls, owner_uid, po_id, po_dict, sandbox=True):
        po_dict["id"] = po_id
        po_dict["ownerUID"] = owner_uid
        if "createdAt" not in po_dict or not po_dict["createdAt"]:
            po_dict["createdAt"] = serialize_field(datetime.utcnow())
        po_dict["updatedAt"] = serialize_field(datetime.utcnow())

        defaults = {
            "status": "borrador",
            "currency": "DOP",
            "exchangeRate": 1.0,
            "paymentTerms": "contado",
            "subtotal": 0.0,
            "itbis": 0.0,
            "discount": 0.0,
            "total": 0.0,
            "notes": "",
            "internalNotes": "",
            "deliveryAddress": "",
            "attachments": [],
            "items": [],
        }
        for k, v in defaults.items():
            if k not in po_dict:
                po_dict[k] = v

        if firebase_initialized and db_firestore is not None:
            try:
                coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(po_id).set(po_dict)
            except Exception as e:
                print(f"⚠️ Error al guardar orden de compra en Firestore: {e}")
        return po_dict

    @classmethod
    def delete_purchase_order(cls, owner_uid, po_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return
        try:
            coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
            db_firestore.collection("users").document(owner_uid).collection(coll_name).document(po_id).delete()
        except Exception as e:
            print(f"⚠️ Error al eliminar orden de compra {po_id}: {e}")

    @classmethod
    def get_next_po_number(cls, owner_uid, sandbox=True):
        year = datetime.utcnow().strftime("%Y")
        max_num = 0
        orders = cls.get_purchase_orders(owner_uid, sandbox=sandbox)
        for o in orders:
            pn = o.get("poNumber", "")
            m = re.match(rf"^OC-{year}-(\d{{4}})$", pn)
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
        next_num = max_num + 1
        return f"OC-{year}-{next_num:04d}"

    @classmethod
    def update_status(cls, owner_uid, po_id, new_status, sandbox=True, user=""):
        po = cls.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
        if not po:
            return None
        if new_status not in PO_STATUSES:
            return po
        po["status"] = new_status
        now = serialize_field(datetime.utcnow())
        if new_status == "aprobada":
            po["approvedBy"] = user
            po["approvedAt"] = now
        elif new_status in ("recibida_parcial", "recibida_completa"):
            po["receivedBy"] = user
            po["receivedAt"] = now
        cls.save_purchase_order(owner_uid, po_id, po, sandbox=sandbox)
        return po
