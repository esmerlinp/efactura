import uuid
from datetime import datetime, timezone

try:
    from app.services.db_service import db_firestore, firebase_initialized, DatabaseService
    from app.services.supplier_invoice_service import serialize_field
except ImportError:
    db_firestore = None
    firebase_initialized = False
    DatabaseService = None


class PurchaseCreditNoteService:

    @classmethod
    def _coll(cls, sandbox):
        return "sandbox_purchase_credit_notes" if sandbox else "purchase_credit_notes"

    @classmethod
    def _counter_ref(cls, owner_uid):
        return db_firestore.collection("users").document(owner_uid)\
            .collection("config").document("purchase_credit_note_counter")

    @classmethod
    def _get_next_number(cls, owner_uid):
        from google.cloud.firestore import Transaction
        transaction = db_firestore.transaction()
        @firestore.transactional
        def increment(transaction):
            ref = cls._counter_ref(owner_uid)
            snapshot = transaction.get(ref)
            if snapshot.exists:
                num = snapshot.to_dict().get("counter", 0) + 1
            else:
                num = 1
            transaction.set(ref, {"counter": num})
            return num
        try:
            return increment(transaction)
        except Exception:
            ref = cls._counter_ref(owner_uid)
            snapshot = ref.get()
            if snapshot.exists:
                num = snapshot.to_dict().get("counter", 0) + 1
            else:
                num = 1
            ref.set({"counter": num})
            return num

    @classmethod
    def get_all(cls, owner_uid, sandbox=True):
        notes = []
        if not firebase_initialized or db_firestore is None:
            return notes
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                data["amount"] = float(data.get("amount", 0))
                data["date"] = serialize_field(data.get("date"))
                data["createdAt"] = serialize_field(data.get("createdAt"))
                notes.append(data)
            notes.sort(key=lambda x: x.get("creditNoteNumber", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener NC compras: {e}")
        return notes

    @classmethod
    def get(cls, owner_uid, note_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            doc = db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(note_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                data["amount"] = float(data.get("amount", 0))
                data["date"] = serialize_field(data.get("date"))
                data["createdAt"] = serialize_field(data.get("createdAt"))
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener NC compra {note_id}: {e}")
        return None

    @classmethod
    def create(cls, owner_uid, note_data, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        note_id = str(uuid.uuid4())
        note_number = f"NC-{cls._get_next_number(owner_uid):04d}"
        try:
            note_data["id"] = note_id
            note_data["creditNoteNumber"] = note_number
            note_data["createdAt"] = datetime.now(timezone.utc).isoformat()
            note_data["status"] = note_data.get("status", "activa")
            note_data["creditedInvoiceId"] = note_data.get("creditedInvoiceId", "")
            note_data["creditedInvoiceNumber"] = note_data.get("creditedInvoiceNumber", "")
            note_data["creditedSupplierName"] = note_data.get("creditedSupplierName", "")
            note_data["amount"] = float(note_data.get("amount", 0))
            note_data["date"] = note_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            note_data["concept"] = note_data.get("concept", "")
            note_data["notes"] = note_data.get("notes", "")
            note_data["createdBy"] = note_data.get("createdBy", "")

            db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(note_id).set(note_data)

            # Reducir CxP de la factura de proveedor vinculada
            credited_invoice_id = note_data["creditedInvoiceId"]
            if credited_invoice_id:
                try:
                    from app.services.supplier_invoice_service import SupplierInvoiceService
                    inv = SupplierInvoiceService.get(owner_uid, credited_invoice_id, sandbox=sandbox)
                    if inv:
                        current_rem = float(inv.get("cxpRemainingBalance", inv.get("total", 0)))
                        new_rem = max(0, round(current_rem - note_data["amount"], 2))
                        new_status = "Pagado" if new_rem <= 0.01 else inv.get("cxpStatus", "Pendiente")
                        if new_status == "Pendiente":
                            new_status = "Abonado"
                        SupplierInvoiceService.update(owner_uid, credited_invoice_id, {
                            "cxpRemainingBalance": new_rem,
                            "cxpStatus": new_status,
                        }, sandbox=sandbox)
                except Exception as inv_err:
                    print(f"⚠️ Error al actualizar CxP de factura vinculada a NC compras: {inv_err}")

            msg = f"Nota de Crédito {note_number} creada exitosamente."
            return True, msg
        except Exception as e:
            print(f"⚠️ Error al crear NC compra: {e}")
            return False, str(e)

    @classmethod
    def void(cls, owner_uid, note_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            note = cls.get(owner_uid, note_id, sandbox=sandbox)
            if not note:
                return False, "Nota de crédito no encontrada."
            if note.get("status") != "activa":
                return False, "Solo se pueden anular NC activas."

            db_firestore.collection("users").document(owner_uid).collection(cls._coll(sandbox)).document(note_id).update({
                "status": "anulada",
                "voidedAt": datetime.now(timezone.utc).isoformat(),
            })

            # Restaurar CxP de la factura vinculada
            credited_invoice_id = note.get("creditedInvoiceId", "")
            if credited_invoice_id:
                try:
                    from app.services.supplier_invoice_service import SupplierInvoiceService
                    inv = SupplierInvoiceService.get(owner_uid, credited_invoice_id, sandbox=sandbox)
                    if inv:
                        current_rem = float(inv.get("cxpRemainingBalance", inv.get("total", 0)))
                        new_rem = round(current_rem + note["amount"], 2)
                        total = float(inv.get("total", 0))
                        new_status = "Pagado" if new_rem <= 0.01 else "Pendiente" if new_rem >= total else "Abonado"
                        if new_rem <= 0.01:
                            new_status = "Pagado"
                        SupplierInvoiceService.update(owner_uid, credited_invoice_id, {
                            "cxpRemainingBalance": new_rem,
                            "cxpStatus": new_status,
                        }, sandbox=sandbox)
                except Exception as inv_err:
                    print(f"⚠️ Error al restaurar CxP al anular NC compras: {inv_err}")

            return True, f"Nota de Crédito {note.get('creditNoteNumber', '')} anulada."
        except Exception as e:
            print(f"⚠️ Error al anular NC compra: {e}")
            return False, str(e)
