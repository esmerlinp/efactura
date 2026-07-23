import uuid
import re
from datetime import datetime, timezone

try:
    from app.services.db_service import db_firestore, firebase_initialized, _company_coll
except ImportError:
    db_firestore = None
    firebase_initialized = False
    _company_coll = None


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
    def get_purchase_orders(cls, owner_uid=None, sandbox=True, branch_id=None, project_id=None, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return []
        orders = []
        try:
            coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
            docs = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                orders.append(data)
            orders.sort(key=lambda x: x.get("poNumber", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener órdenes de compra: {e}")
        if branch_id:
            orders = [o for o in orders if o.get("branchId") == branch_id]
        if project_id == '__no_project__':
            orders = [o for o in orders if not o.get("projectId")]
        elif project_id:
            orders = [o for o in orders if o.get("projectId") == project_id]
        return orders

    @classmethod
    def get_purchase_order(cls, owner_uid=None, po_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
            doc = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).document(po_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener orden de compra {po_id}: {e}")
        return None

    @classmethod
    def save_purchase_order(cls, owner_uid=None, po_id=None, po_dict=None, sandbox=True, company_id=None):
        po_dict["id"] = po_id
        po_dict["ownerUID"] = owner_uid
        po_dict["branchId"] = po_dict.get("branchId", "default-sucursal-principal")
        po_dict["projectId"] = po_dict.get("projectId", None)
        if "createdAt" not in po_dict or not po_dict["createdAt"]:
            po_dict["createdAt"] = serialize_field(datetime.now(timezone.utc))
        po_dict["updatedAt"] = serialize_field(datetime.now(timezone.utc))

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

        try:
            if not po_dict.get("approvalRequestId") and po_dict.get("status") in ("borrador", "", None):
                from app.services.approval_service import ApprovalService
                po_dict = ApprovalService.prepare_document_approval(
                    owner_uid=owner_uid,
                    company_id=company_id,
                    doc_type="purchase_order",
                    doc_id=po_id,
                    document=po_dict,
                    amount_field="total",
                    number_field="poNumber",
                    sandbox=sandbox,
                )
        except Exception as approval_err:
            print(f"⚠️ Error al evaluar aprobación de orden de compra {po_id}: {approval_err}")

        if firebase_initialized and db_firestore is not None:
            try:
                coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
                _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).document(po_id).set(po_dict)
            except Exception as e:
                print(f"⚠️ Error al guardar orden de compra en Firestore: {e}")
        return po_dict

    @classmethod
    def delete_purchase_order(cls, owner_uid=None, po_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return
        try:
            coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
            _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).document(po_id).delete()
        except Exception as e:
            print(f"⚠️ Error al eliminar orden de compra {po_id}: {e}")

    @classmethod
    def get_next_po_number(cls, owner_uid=None, sandbox=True, company_id=None):
        year = datetime.now(timezone.utc).strftime("%Y")
        max_num = 0
        orders = cls.get_purchase_orders(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
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
    def update_status(cls, owner_uid=None, po_id=None, new_status=None, sandbox=True, user="", company_id=None):
        po = cls.get_purchase_order(owner_uid=owner_uid, po_id=po_id, sandbox=sandbox, company_id=company_id)
        if not po:
            return None
        if new_status not in PO_STATUSES:
            return po
        po["status"] = new_status
        now = serialize_field(datetime.now(timezone.utc))
        if new_status == "aprobada":
            po["approvedBy"] = user
            po["approvedAt"] = now
        elif new_status in ("recibida_parcial", "recibida_completa"):
            po["receivedBy"] = user
            po["receivedAt"] = now
        cls.save_purchase_order(owner_uid=owner_uid, po_id=po_id, po_dict=po, sandbox=sandbox, company_id=company_id)
        return po
