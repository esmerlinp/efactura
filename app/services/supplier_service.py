import uuid
from datetime import datetime, timezone

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


class SupplierService:

    @classmethod
    def get_suppliers(cls, owner_uid, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return []
        suppliers = []
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                suppliers.append(data)
            suppliers.sort(key=lambda x: x.get("name", "").lower())
        except Exception as e:
            print(f"⚠️ Error al obtener proveedores: {e}")
        return suppliers

    @classmethod
    def get_supplier(cls, owner_uid, supplier_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            doc = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(supplier_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener proveedor {supplier_id}: {e}")
        return None

    @classmethod
    def save_supplier(cls, owner_uid, supplier_id, supplier_dict, sandbox=True):
        supplier_dict["id"] = supplier_id
        supplier_dict["ownerUID"] = owner_uid
        if "createdAt" not in supplier_dict or not supplier_dict["createdAt"]:
            supplier_dict["createdAt"] = serialize_field(datetime.now(timezone.utc))
        supplier_dict["updatedAt"] = serialize_field(datetime.now(timezone.utc))
        supplier_dict["name"] = supplier_dict.get("name", "").strip()
        supplier_dict["rnc"] = "".join(filter(str.isdigit, str(supplier_dict.get("rnc", ""))))

        defaults = {
            "tipoPersona": "fisica",
            "code": "",
            "estado": "Activo",
            "phone": "",
            "email": "",
            "address": "",
            "city": "",
            "country": "República Dominicana",
            "contactPerson": "",
            "supplierType": "formal",
            "currency": "DOP",
            "creditDays": 0,
            "creditLimit": 0.0,
            "paymentMethod": "Efectivo",
            "ecfTypeEmits": "E31",
            "itbisWithholding": False,
            "isrWithholding": False,
            "tipoGastoDGII": "02",
            "attachments": [],
            "firebaseAttachmentURLs": [],
            "notes": "",
        }
        for k, v in defaults.items():
            if k not in supplier_dict:
                supplier_dict[k] = v

        if firebase_initialized and db_firestore is not None:
            try:
                coll_name = "sandbox_suppliers" if sandbox else "suppliers"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(supplier_id).set(supplier_dict)
            except Exception as e:
                print(f"⚠️ Error al guardar proveedor en Firestore: {e}")
        return supplier_dict

    @classmethod
    def delete_supplier(cls, owner_uid, supplier_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            db_firestore.collection("users").document(owner_uid).collection(coll_name).document(supplier_id).delete()
        except Exception as e:
            print(f"⚠️ Error al eliminar proveedor {supplier_id}: {e}")

    @classmethod
    def get_supplier_by_rnc(cls, owner_uid, rnc, sandbox=True):
        rnc_clean = "".join(filter(str.isdigit, str(rnc)))
        if not rnc_clean:
            return None
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).where("rnc", "==", rnc_clean).limit(1).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al buscar proveedor por RNC {rnc}: {e}")
        return None

    @classmethod
    def get_or_create_supplier(cls, owner_uid, rnc, name, address="", sandbox=True):
        existing = cls.get_supplier_by_rnc(owner_uid, rnc, sandbox=sandbox)
        if existing:
            return existing["id"]
        supplier_id = str(uuid.uuid4())
        supplier_dict = {
            "rnc": rnc,
            "name": name,
            "address": address,
        }
        cls.save_supplier(owner_uid, supplier_id, supplier_dict, sandbox=sandbox)
        return supplier_id

    @classmethod
    def update_last_import(cls, owner_uid, supplier_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            db_firestore.collection("users").document(owner_uid).collection(coll_name).document(supplier_id).update({
                "lastImportDate": serialize_field(datetime.now(timezone.utc)),
            })
        except Exception as e:
            print(f"⚠️ Error al actualizar lastImportDate: {e}")
