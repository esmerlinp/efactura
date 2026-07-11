import uuid
import re
from datetime import datetime, timezone

try:
    from app.services.db_service import db_firestore, firebase_initialized, firebase_storage_bucket, DatabaseService
except ImportError:
    db_firestore = None
    firebase_initialized = False
    firebase_storage_bucket = None
    DatabaseService = None


def serialize_field(val):
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    return str(val)


CXP_STATUSES = ["Pendiente", "Abonado", "Pagado", "Vencido"]

ALLOWED_MIME_TYPES = ["application/pdf", "image/jpeg", "image/png"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class SupplierInvoiceService:

    @classmethod
    def _coll(cls, sandbox):
        return "sandbox_supplier_invoices" if sandbox else "supplier_invoices"

    @classmethod
    def _counter_ref(cls, owner_uid):
        return db_firestore.collection("users").document(owner_uid)\
            .collection("config").document("supplier_invoice_counter")

    @classmethod
    def _get_next_counter(cls, owner_uid):
        """Atomically increment the supplier invoice counter using Firestore transaction."""
        from google.cloud.firestore import Transaction

        transaction = db_firestore.transaction()

        @firestore.transactional
        def increment(transaction):
            ref = cls._counter_ref(owner_uid)
            doc = ref.get(transaction=transaction)
            year = datetime.now(timezone.utc).strftime("%Y")

            if doc.exists:
                data = doc.to_dict()
                last_year = data.get("year", "")
                last_num = data.get("lastNumber", 0)
                if last_year == year:
                    next_num = last_num + 1
                else:
                    next_num = 1
            else:
                next_num = 1

            transaction.set(ref, {
                "year": year,
                "lastNumber": next_num,
            })
            return next_num

        try:
            return increment(transaction)
        except Exception as e:
            print(f"⚠️ Error en contador atómico de facturas proveedor: {e}")
            raise

    @classmethod
    def get_all(cls, owner_uid, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return []
        invoices = []
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                invoices.append(data)
            invoices.sort(key=lambda x: x.get("invoiceNumber", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener facturas proveedor: {e}")
        return invoices

    @classmethod
    def get(cls, owner_uid, invoice_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            doc = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(invoice_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener factura proveedor {invoice_id}: {e}")
        return None

    @classmethod
    def get_by_po(cls, owner_uid, po_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return []
        invoices = []
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox))\
                .where("poId", "==", po_id).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                invoices.append(data)
            invoices.sort(key=lambda x: x.get("invoiceNumber", ""))
        except Exception as e:
            print(f"⚠️ Error al obtener facturas de OC {po_id}: {e}")
        return invoices

    @classmethod
    def get_by_receipt(cls, owner_uid, receipt_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return []
        invoices = []
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox))\
                .where("receiptId", "==", receipt_id).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                invoices.append(data)
        except Exception as e:
            print(f"⚠️ Error al obtener facturas de recepción {receipt_id}: {e}")
        return invoices

    @classmethod
    def get_next_invoice_number(cls, owner_uid, sandbox=True):
        try:
            next_num = cls._get_next_counter(owner_uid)
        except Exception:
            year = datetime.now(timezone.utc).strftime("%Y")
            max_num = 0
            invoices = cls.get_all(owner_uid, sandbox=sandbox)
            for inv in invoices:
                inv_num = inv.get("invoiceNumber", "")
                m = re.match(rf"^FI-{year}-(\d{{4}})$", inv_num)
                if m:
                    num = int(m.group(1))
                    if num > max_num:
                        max_num = num
            next_num = max_num + 1
        year = datetime.now(timezone.utc).strftime("%Y")
        return f"FI-{year}-{next_num:04d}"

    @classmethod
    def _check_ncf_unique(cls, owner_uid, ncf, sandbox=True, exclude_id=None):
        """Check if supplierInvoiceNumber or NCF already exists."""
        if not ncf or not firebase_initialized:
            return True
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox))\
                .where("supplierInvoiceNumber", "==", ncf).get()
            for doc in docs:
                if exclude_id and doc.id == exclude_id:
                    continue
                return False
            if len(ncf) >= 8:
                docs = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox))\
                    .where("ncf", "==", ncf).get()
                for doc in docs:
                    if exclude_id and doc.id == exclude_id:
                        continue
                    return False
        except Exception as e:
            print(f"⚠️ Error al verificar NCF duplicado: {e}")
        return True

    @classmethod
    def create(cls, owner_uid, data, sandbox=True):
        invoice_id = str(uuid.uuid4())
        data["id"] = invoice_id
        data["ownerUID"] = owner_uid
        if "createdAt" not in data or not data["createdAt"]:
            data["createdAt"] = serialize_field(datetime.now(timezone.utc))
        data["updatedAt"] = serialize_field(datetime.now(timezone.utc))

        total = float(data.get("total", 0))
        data.setdefault("cxpStatus", "Pendiente")
        data.setdefault("cxpRemainingBalance", total)
        data.setdefault("status", "registrada")
        data.setdefault("currency", "DOP")
        data.setdefault("exchangeRate", 1.0)
        data.setdefault("notes", "")
        data.setdefault("attachmentUrls", [])
        data.setdefault("items", [])
        data.setdefault("paymentMethod", "")
        data.setdefault("paymentReference", "")
        data.setdefault("supplierType", "formal")
        data.setdefault("ecfType", "E31")
        data.setdefault("cne", "")
        data.setdefault("paymentTerms", "contado")
        data.setdefault("bankAccountId", "")
        data.setdefault("retainedISR", 0.0)
        data.setdefault("retainedITBIS", 0.0)
        data.setdefault("category", "Otros Gastos")
        data.setdefault("tipoGastoDGII", "02")
        data.setdefault("poId", "")
        data.setdefault("poNumber", "")
        data.setdefault("branchId", "")
        data.setdefault("projectId", None)
        data.setdefault("comentario", "")

        if firebase_initialized and db_firestore is not None:
            try:
                db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(invoice_id).set(data)
            except Exception as e:
                print(f"⚠️ Error al guardar factura proveedor en Firestore: {e}")
        return data

    @classmethod
    def update(cls, owner_uid, invoice_id, data, sandbox=True):
        """Update non-fiscal fields of a supplier invoice."""
        if not firebase_initialized or db_firestore is None:
            return False
        try:
            data["updatedAt"] = serialize_field(datetime.now(timezone.utc))
            db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(invoice_id).update(data)
            return True
        except Exception as e:
            print(f"⚠️ Error al actualizar factura proveedor {invoice_id}: {e}")
            return False

    @classmethod
    def add_attachment(cls, owner_uid, invoice_id, file_data, file_name, mime_type, sandbox=True):
        """Add an attachment to an existing supplier invoice."""
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            safe_name = file_name.replace(" ", "_")
            dest_path = f"users/{owner_uid}/supplier_invoices/{uuid.uuid4().hex}/{safe_name}"
            public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
            if public_url:
                doc_ref = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(invoice_id)
                doc_ref.update({
                    "attachmentUrls": firestore.ArrayUnion([public_url]),
                    "updatedAt": serialize_field(datetime.now(timezone.utc)),
                })
            return public_url
        except Exception as e:
            print(f"⚠️ Error al agregar attachment a factura proveedor {invoice_id}: {e}")
            return None

    @classmethod
    def save_payment(cls, owner_uid, invoice_id, payment_amount, registered_by="Usuario",
                     sandbox=True, payment_method="", payment_reference="", bank_account_id=""):
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            doc_ref = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(invoice_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False, "Factura proveedor no encontrada."
            data = doc.to_dict()
            current_status = data.get("cxpStatus", "Pendiente")
            if current_status == "Pagado":
                return False, "La factura ya está pagada. No se pueden registrar más pagos."
            total = float(data.get("total", 0))
            current_rem = float(data.get("cxpRemainingBalance", total))
            if payment_amount > current_rem:
                return False, f"El monto (RD$ {payment_amount:,.2f}) excede el saldo pendiente (RD$ {current_rem:,.2f})."
            new_rem = round(current_rem - payment_amount, 2)
            new_status = "Pagado" if new_rem <= 0.01 else "Abonado"
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            due_date = data.get("dueDate", "")
            if new_status in ("Abonado", "Pendiente") and due_date and due_date < today_str:
                new_status = "Vencido"
            payment_id = str(uuid.uuid4())
            payment_doc = {
                "id": payment_id,
                "amount": payment_amount,
                "paymentDate": datetime.now(timezone.utc).isoformat(),
                "registeredBy": registered_by,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "method": payment_method or "",
                "reference": payment_reference or "",
                "bankAccountId": bank_account_id,
            }
            doc_ref.collection("cxp_payments").document(payment_id).set(payment_doc)
            doc_ref.update({
                "cxpRemainingBalance": new_rem,
                "cxpStatus": new_status,
                "updatedAt": serialize_field(datetime.now(timezone.utc)),
            })

            # Actualizar saldo de la cuenta bancaria si se especificó
            if bank_account_id:
                try:
                    from app.services.db_service import DatabaseService
                    bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox)
                    if bank_acc:
                        new_balance = bank_acc["currentBalance"] - payment_amount
                        DatabaseService.save_bank_account(owner_uid, bank_account_id, {
                            **bank_acc,
                            "currentBalance": new_balance
                        }, sandbox=sandbox)
                except Exception as bank_err:
                    print(f"⚠️ Error al actualizar saldo de cuenta bancaria en pago a proveedor: {bank_err}")

            msg = f"Pago de RD$ {payment_amount:,.2f} registrado con éxito. Nuevo balance: RD$ {new_rem:,.2f}."
            return True, msg
        except Exception as e:
            print(f"⚠️ Error en save_payment supplier_invoice: {e}")
            return False, str(e)

    @classmethod
    def get_payments(cls, owner_uid, invoice_id, sandbox=True):
        payments = []
        if not firebase_initialized or db_firestore is None:
            return payments
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(invoice_id).collection("cxp_payments").get()
            for doc in docs:
                data = doc.to_dict()
                payments.append({
                    "id": doc.id,
                    "amount": float(data.get("amount", 0)),
                    "paymentDate": data.get("paymentDate", ""),
                    "registeredBy": data.get("registeredBy", ""),
                    "method": data.get("method", ""),
                    "reference": data.get("reference", ""),
                    "createdAt": data.get("createdAt", ""),
                })
            payments.sort(key=lambda p: p.get("createdAt", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener pagos de factura proveedor: {e}")
        return payments

    @classmethod
    def void_payment(cls, owner_uid, invoice_id, payment_id, sandbox=True):
        """Reverse a payment and recalculate invoice status."""
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            doc_ref = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(invoice_id)
            inv_doc = doc_ref.get()
            if not inv_doc.exists:
                return False, "Factura proveedor no encontrada."
            inv_data = inv_doc.to_dict()
            pay_ref = doc_ref.collection("cxp_payments").document(payment_id)
            pay_doc = pay_ref.get()
            if not pay_doc.exists:
                return False, "Pago no encontrado."
            pay_data = pay_doc.to_dict()
            amount = float(pay_data.get("amount", 0))
            current_rem = float(inv_data.get("cxpRemainingBalance", inv_data.get("total", 0)))
            total = float(inv_data.get("total", 0))
            new_rem = round(current_rem + amount, 2)
            pay_ref.delete()
            if new_rem >= total - 0.01:
                new_status = "Pendiente"
            else:
                new_status = "Abonado"
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            due_date = inv_data.get("dueDate", "")
            if new_status in ("Pendiente", "Abonado") and due_date and due_date < today_str:
                new_status = "Vencido"
            doc_ref.update({
                "cxpRemainingBalance": new_rem,
                "cxpStatus": new_status,
                "updatedAt": serialize_field(datetime.now(timezone.utc)),
            })
            return True, f"Pago de RD$ {amount:,.2f} revertido. Nuevo saldo: RD$ {new_rem:,.2f}."
        except Exception as e:
            print(f"⚠️ Error al revertir pago {payment_id}: {e}")
            return False, str(e)

    @classmethod
    def delete(cls, owner_uid, invoice_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return
        try:
            doc_ref = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(invoice_id)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                attachment_urls = data.get("attachmentUrls", [])
                for url in attachment_urls:
                    if url and not url.startswith("/static/"):
                        try:
                            from urllib.parse import urlparse
                            path = urlparse(url).path
                            if path.startswith("/"):
                                path = path[1:]
                            blob = firebase_storage_bucket.blob(path)
                            blob.delete()
                        except Exception as e:
                            print(f"⚠️ Error al eliminar archivo de storage: {e}")
                payments = doc_ref.collection("cxp_payments").get()
                for pay in payments:
                    pay.reference.delete()
            doc_ref.delete()
        except Exception as e:
            print(f"⚠️ Error al eliminar factura proveedor {invoice_id}: {e}")
