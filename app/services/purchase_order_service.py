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

# Transiciones de estado permitidas (estado actual → estados destino válidos).
ALLOWED_TRANSITIONS = {
    "borrador": {"pendiente_aprobacion", "aprobada", "rechazada", "cancelada"},
    "pendiente_aprobacion": {"aprobada", "rechazada", "cancelada"},
    "aprobada": {"recibida_parcial", "recibida_completa", "cancelada"},
    "rechazada": {"borrador", "cancelada"},
    "recibida_parcial": {"recibida_completa", "cancelada"},
    "recibida_completa": set(),
    "cancelada": set(),
}

PAYMENT_TERMS = [
    ("contado", "Contado"),
    ("credito_15d", "Crédito 15 Días"),
    ("credito_30d", "Crédito 30 Días"),
    ("credito_45d", "Crédito 45 Días"),
    ("credito_60d", "Crédito 60 Días"),
    ("credito_90d", "Crédito 90 Días"),
]

CURRENCIES = ["DOP", "USD", "EUR"]


def _require_company_id(company_id):
    from app.services.company_authorization import require_company_id
    return require_company_id(company_id, "PurchaseOrderService")


class PurchaseOrderService:

    @classmethod
    def get_purchase_orders(cls, owner_uid=None, sandbox=True, branch_id=None, project_id=None, company_id=None):
        company_id = _require_company_id(company_id)
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
        company_id = _require_company_id(company_id)
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
        company_id = _require_company_id(company_id)
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
        company_id = _require_company_id(company_id)
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
    def can_transition(cls, current_status, new_status):
        """Indica si una transición de estado de OC está permitida."""
        if new_status not in PO_STATUSES:
            return False
        current = current_status or "borrador"
        if current not in PO_STATUSES:
            return False
        return new_status in ALLOWED_TRANSITIONS.get(current, set())

    @classmethod
    def update_status(cls, owner_uid=None, po_id=None, new_status=None, sandbox=True, user="", company_id=None, enforce=True, approver_uid="", approver_email=""):
        po = cls.get_purchase_order(owner_uid=owner_uid, po_id=po_id, sandbox=sandbox, company_id=company_id)
        if not po:
            return None
        if new_status not in PO_STATUSES:
            return po
        current = po.get("status") or "borrador"
        if enforce and not cls.can_transition(current, new_status):
            raise ValueError(f"Transición no permitida: '{current}' → '{new_status}'.")
        po["status"] = new_status
        now = serialize_field(datetime.now(timezone.utc))
        if new_status == "aprobada":
            po["approvedBy"] = user
            if approver_uid:
                po["approvedByUid"] = approver_uid
            if approver_email:
                po["approvedByEmail"] = approver_email
            po["approvedAt"] = now
        elif new_status in ("recibida_parcial", "recibida_completa"):
            po["receivedBy"] = user
            if approver_uid:
                po["receivedByUid"] = approver_uid
            if approver_email:
                po["receivedByEmail"] = approver_email
            po["receivedAt"] = now
        cls.save_purchase_order(owner_uid=owner_uid, po_id=po_id, po_dict=po, sandbox=sandbox, company_id=company_id)
        return po

    @classmethod
    def _confirm_service_tx(cls, transaction, owner_uid, po_id, po_item_id, status,
                            user, user_uid, notes, sandbox, company_id):
        po_ref = _company_coll(
            company_id=company_id, owner_uid=owner_uid,
            coll_name="sandbox_purchase_orders" if sandbox else "purchase_orders",
        ).document(po_id)
        po_doc = po_ref.get(transaction=transaction)
        if not po_doc.exists:
            raise ValueError("Orden de compra no encontrada.")
        po = po_doc.to_dict() or {}
        item = next((i for i in po.get("items", []) if i.get("id") == po_item_id), None)
        if not item:
            raise ValueError("Partida no encontrada en la orden de compra.")
        if item.get("isInventoriable", True):
            raise ValueError("Solo se pueden confirmar servicios (partidas no inventariables).")
        if status not in ("confirmado", "rechazado"):
            raise ValueError("Estado de confirmación inválido.")

        item["serviceStatus"] = status
        item["serviceConfirmedBy"] = user or ""
        item["serviceConfirmedByUid"] = user_uid or ""
        item["serviceConfirmedAt"] = serialize_field(datetime.now(timezone.utc))
        item["serviceConfirmationNotes"] = notes or ""

        transaction.set(po_ref, po)
        return True

    @classmethod
    def confirm_service(cls, owner_uid=None, po_id=None, po_item_id=None, status="confirmado",
                        user="", user_uid="", notes="", sandbox=True, company_id=None):
        """Confirma o rechaza la realización de un servicio (partida no inventariable).

        Devuelve ``(ok, mensaje)``. La lectura y escritura de la OC se hacen en
        una transacción Firestore, de modo que confirmaciones concurrentes de
        partidas distintas no se sobrescriben entre sí.
        """
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        status = str(status or "").strip().lower()
        try:
            from app.services.db_service import run_firestore_transaction
            run_firestore_transaction(
                cls._confirm_service_tx, owner_uid, po_id, po_item_id, status,
                user, user_uid, notes, sandbox, company_id,
            )
            return True, f"Servicio {status}."
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            print(f"⚠️ Error al confirmar servicio {po_item_id}: {e}")
            return False, "No se pudo confirmar el servicio."

    @classmethod
    def get_traceability(cls, owner_uid=None, po_id=None, sandbox=True, company_id=None):
        """Construye la trazabilidad completa OC → recepción → factura → pago.

        Consulta los registros originales (no duplica información financiera) y
        devuelve importes solicitados, recibidos, facturados, pagados y
        pendientes, junto con el detalle de recepciones, facturas y pagos.

        Definición de importes (todos BRUTOS, incluyen ITBIS cuando aplica):
          - ``requested``: total de la OC (subtotal − descuento + ITBIS).
          - ``receivedAmount``: Σ recibido × precio × (1 − descuento%) × (1 + ITBIS).
          - ``invoiced``: Σ total de facturas no anuladas.
          - ``paid``: Σ pagos aprobados (aplicados).
          - ``pending``: facturado − pagado.
        """
        po = cls.get_purchase_order(owner_uid=owner_uid, po_id=po_id, sandbox=sandbox, company_id=company_id)
        if not po:
            return None

        requested = round(float(po.get("total", 0) or 0), 2)
        received_amount = 0.0
        for item in po.get("items", []):
            qty = float(item.get("receivedQuantity", 0) or 0)
            price = float(item.get("unitPrice", 0) or 0)
            discount = float(item.get("discount", 0) or 0)
            itbis_rate = float(item.get("itbisRate", 0) or 0)
            net = qty * price * (1.0 - discount / 100.0)
            received_amount += net * (1.0 + itbis_rate)
        received_amount = round(received_amount, 2)

        receipts = []
        try:
            from app.services.goods_receipt_service import GoodsReceiptService
            receipts = GoodsReceiptService.get_receipts_by_po(company_id=company_id, po_id=po_id, sandbox=sandbox)
        except Exception as e:
            print(f"⚠️ Error al obtener recepciones para trazabilidad {po_id}: {e}")

        invoices = []
        try:
            from app.services.supplier_invoice_service import SupplierInvoiceService
            all_invoices = SupplierInvoiceService.get_by_po(owner_uid=owner_uid, po_id=po_id, sandbox=sandbox, company_id=company_id)
            invoices = [inv for inv in all_invoices if not SupplierInvoiceService.is_voided(inv)]
        except Exception as e:
            print(f"⚠️ Error al obtener facturas para trazabilidad {po_id}: {e}")

        total_invoiced = 0.0
        total_paid = 0.0
        invoice_details = []
        for inv in invoices:
            inv_total = round(float(inv.get("total", 0) or 0), 2)
            total_invoiced += inv_total
            payments = []
            paid_amount = 0.0
            try:
                from app.services.supplier_invoice_service import SupplierInvoiceService
                all_payments = SupplierInvoiceService.get_payments(
                    owner_uid=owner_uid, invoice_id=inv.get("id", ""), sandbox=sandbox, company_id=company_id
                )
                for p in all_payments:
                    if str(p.get("approvalStatus") or "").lower() != "approved":
                        continue
                    amt = round(float(p.get("amount", 0) or 0), 2)
                    paid_amount += amt
                    payments.append(p)
            except Exception as e:
                print(f"⚠️ Error al obtener pagos para trazabilidad {inv.get('id')}: {e}")
            total_paid += paid_amount
            invoice_details.append({
                "id": inv.get("id", ""),
                "invoiceNumber": inv.get("invoiceNumber", ""),
                "supplierInvoiceNumber": inv.get("supplierInvoiceNumber", ""),
                "ncf": inv.get("ncf", ""),
                "total": inv_total,
                "cxpStatus": inv.get("cxpStatus", ""),
                "paidAmount": round(paid_amount, 2),
                "payments": payments,
            })

        total_invoiced = round(total_invoiced, 2)
        total_paid = round(total_paid, 2)

        return {
            "poId": po_id,
            "poNumber": po.get("poNumber", ""),
            "supplierName": po.get("supplierName", ""),
            "status": po.get("status", ""),
            "requested": requested,
            "receivedAmount": received_amount,
            "invoiced": total_invoiced,
            "paid": total_paid,
            "pending": round(total_invoiced - total_paid, 2),
            "receipts": receipts,
            "invoices": invoice_details,
        }
