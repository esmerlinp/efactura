import uuid
from datetime import datetime, timezone

try:
    from app.services.db_service import db_firestore, firebase_initialized, DatabaseService
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


# =========================================================================
# Data model default values
# =========================================================================

CONTACT_DEFAULTS = {
    "types": [],
    "rnc": "",
    "razonSocial": "",
    "email": "",
    "telefono": "",
    "telefono2": "",
    "celular": "",
    "direccion": "",
    "municipio": "",
    "provincia": "",
    "pais": "República Dominicana",
    "imageUrl": "",
    "pipelineStage": "Prospecto",
    "priceListId": "",
    "nextContactDate": "",
    "responsibleId": "",
    "accessPin": "",
    "disableAutoReminders": False,
    "tipoPersona": "fisica",
    "supplierType": "formal",
    "creditDays": 0,
    "creditLimit": 0.0,
    "paymentMethod": "Efectivo",
    "currency": "DOP",
    "itbisWithholding": False,
    "isrWithholding": False,
    "tipoGastoDGII": "02",
    "ecfTypeEmits": "E31",
    "estado": "Activo",
    "associatedPeople": [],
    "notes": "",
    "interactions": [],
    "documents": [],
}


def _coll_name(sandbox):
    return "sandbox_contacts" if sandbox else "contacts"


def _build_contact_from_doc(doc, owner_uid):
    data = doc.to_dict()
    contact = dict(CONTACT_DEFAULTS)
    contact["id"] = doc.id
    contact["ownerUID"] = owner_uid
    contact["branchId"] = data.get("branchId", "default-sucursal-principal")
    contact["projectId"] = data.get("projectId")
    for k, v in data.items():
        if k == "types":
            if isinstance(v, list):
                contact["types"] = v
            continue
        contact[k] = v
    contact["nextContactDate"] = serialize_field(contact.get("nextContactDate"))
    contact["createdAt"] = serialize_field(data.get("createdAt")) if data.get("createdAt") else datetime.now(timezone.utc).isoformat()
    return contact


# =========================================================================
# Sync helpers — write to legacy collections for backward compatibility
# =========================================================================

def _sync_to_legacy_clients(owner_uid, contact, sandbox):
    """Sync contact data to legacy clients collection if type includes 'cliente'."""
    if "cliente" not in contact.get("types", []):
        return
    client_dict = {
        "rnc": contact.get("rnc", ""),
        "razonSocial": contact.get("razonSocial", ""),
        "email": contact.get("email", ""),
        "telefono": contact.get("telefono", ""),
        "direccion": contact.get("direccion", ""),
        "crmNotes": contact.get("notes", ""),
        "nextContactDate": contact.get("nextContactDate", ""),
        "pipelineStage": contact.get("pipelineStage", "Prospecto"),
        "responsibleId": contact.get("responsibleId", ""),
        "imageUrl": contact.get("imageUrl", ""),
        "accessPin": contact.get("accessPin", ""),
        "disableAutoReminders": contact.get("disableAutoReminders", False),
        "createdAt": contact.get("createdAt", datetime.now(timezone.utc).isoformat()),
    }
    DatabaseService.save_client(owner_uid, contact["id"], client_dict, sandbox=sandbox)


def _sync_to_legacy_suppliers(owner_uid, contact, sandbox):
    """Sync contact data to legacy suppliers collection if type includes 'proveedor'."""
    if "proveedor" not in contact.get("types", []):
        return

    from app.services.supplier_service import SupplierService

    supplier_dict = {
        "rnc": contact.get("rnc", ""),
        "name": contact.get("razonSocial", ""),
        "tipoPersona": contact.get("tipoPersona", "fisica"),
        "estado": contact.get("estado", "Activo"),
        "phone": contact.get("telefono", ""),
        "email": contact.get("email", ""),
        "address": contact.get("direccion", ""),
        "city": contact.get("municipio", ""),
        "country": contact.get("pais", "República Dominicana"),
        "supplierType": contact.get("supplierType", "formal"),
        "currency": contact.get("currency", "DOP"),
        "creditDays": contact.get("creditDays", 0),
        "creditLimit": contact.get("creditLimit", 0.0),
        "paymentMethod": contact.get("paymentMethod", "Efectivo"),
        "ecfTypeEmits": contact.get("ecfTypeEmits", "E31"),
        "itbisWithholding": contact.get("itbisWithholding", False),
        "isrWithholding": contact.get("isrWithholding", False),
        "tipoGastoDGII": contact.get("tipoGastoDGII", "02"),
        "notes": contact.get("notes", ""),
        "createdAt": contact.get("createdAt", datetime.now(timezone.utc).isoformat()),
    }
    SupplierService.save_supplier(owner_uid, contact["id"], supplier_dict, sandbox=sandbox)


def _delete_from_legacy_clients(owner_uid, contact_id, sandbox):
    """Delete from legacy clients collection."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_name = "sandbox_clients" if sandbox else "clients"
        db_firestore.collection("users").document(owner_uid).collection(coll_name).document(contact_id).delete()
    except Exception as e:
        print(f"⚠️ Error al eliminar cliente legacy {contact_id}: {e}")


def _delete_from_legacy_suppliers(owner_uid, contact_id, sandbox):
    """Delete from legacy suppliers collection."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_name = "sandbox_suppliers" if sandbox else "suppliers"
        db_firestore.collection("users").document(owner_uid).collection(coll_name).document(contact_id).delete()
    except Exception as e:
        print(f"⚠️ Error al eliminar proveedor legacy {contact_id}: {e}")


# =========================================================================
# CRUD Operations
# =========================================================================

class ContactService:

    @classmethod
    def get_contacts(cls, owner_uid, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return []
        contacts = []
        contact_ids = set()
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(_coll_name(sandbox)).get()
            for doc in docs:
                c = _build_contact_from_doc(doc, owner_uid)
                contact_ids.add(c["id"])
                contacts.append(c)
        except Exception as e:
            print(f"⚠️ Error al obtener contactos: {e}")

        # Fallback: importar clientes legacy que no existan como contacto
        try:
            coll_name = "sandbox_clients" if sandbox else "clients"
            legacy_docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
            for doc in legacy_docs:
                if doc.id in contact_ids:
                    continue
                data = doc.to_dict()
                if not data:
                    continue
                c = dict(CONTACT_DEFAULTS)
                c["id"] = doc.id
                c["ownerUID"] = owner_uid
                c["types"] = ["cliente"]
                c["rnc"] = data.get("rnc", "")
                c["razonSocial"] = data.get("razonSocial", "")
                c["email"] = data.get("email", "")
                c["telefono"] = data.get("telefono", "")
                c["direccion"] = data.get("direccion", "")
                c["notes"] = data.get("crmNotes", "")
                c["nextContactDate"] = serialize_field(data.get("nextContactDate"))
                c["pipelineStage"] = data.get("pipelineStage", "Prospecto")
                c["responsibleId"] = data.get("responsibleId", "")
                c["imageUrl"] = data.get("imageUrl", "")
                c["accessPin"] = data.get("accessPin", "")
                c["disableAutoReminders"] = data.get("disableAutoReminders", False)
                c["priceListId"] = data.get("priceListId", "")
                c["createdAt"] = serialize_field(data.get("createdAt", datetime.now(timezone.utc)))
                contact_ids.add(c["id"])
                contacts.append(c)
        except Exception as e:
            print(f"⚠️ Error al importar clientes legacy: {e}")

        # Fallback: importar proveedores legacy que no existan como contacto
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            legacy_docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
            for doc in legacy_docs:
                if doc.id in contact_ids:
                    continue
                data = doc.to_dict()
                if not data:
                    continue
                c = dict(CONTACT_DEFAULTS)
                c["id"] = doc.id
                c["ownerUID"] = owner_uid
                c["types"] = ["proveedor"]
                c["rnc"] = data.get("rnc", "")
                c["razonSocial"] = data.get("name", "")
                c["email"] = data.get("email", "")
                c["telefono"] = data.get("phone", "")
                c["direccion"] = data.get("address", "")
                c["municipio"] = data.get("city", "")
                c["pais"] = data.get("country", "República Dominicana")
                c["notes"] = data.get("notes", "")
                c["tipoPersona"] = data.get("tipoPersona", "fisica")
                c["supplierType"] = data.get("supplierType", "formal")
                c["creditDays"] = data.get("creditDays", 0)
                c["creditLimit"] = data.get("creditLimit", 0.0)
                c["paymentMethod"] = data.get("paymentMethod", "Efectivo")
                c["currency"] = data.get("currency", "DOP")
                c["itbisWithholding"] = data.get("itbisWithholding", False)
                c["isrWithholding"] = data.get("isrWithholding", False)
                c["tipoGastoDGII"] = data.get("tipoGastoDGII", "02")
                c["ecfTypeEmits"] = data.get("ecfTypeEmits", "E31")
                c["estado"] = data.get("estado", "Activo")
                c["createdAt"] = serialize_field(data.get("createdAt", datetime.now(timezone.utc)))
                contact_ids.add(c["id"])
                contacts.append(c)
        except Exception as e:
            print(f"⚠️ Error al importar proveedores legacy: {e}")

        contacts.sort(key=lambda x: x["razonSocial"].lower())
        return contacts

    @classmethod
    def _legacy_client_to_contact(cls, owner_uid, client_id, sandbox):
        """Convierte un cliente legacy en dict de contacto."""
        coll_name = "sandbox_clients" if sandbox else "clients"
        doc = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        c = dict(CONTACT_DEFAULTS)
        c["id"] = doc.id
        c["ownerUID"] = owner_uid
        c["types"] = ["cliente"]
        c["rnc"] = data.get("rnc", "")
        c["razonSocial"] = data.get("razonSocial", "")
        c["email"] = data.get("email", "")
        c["telefono"] = data.get("telefono", "")
        c["direccion"] = data.get("direccion", "")
        c["notes"] = data.get("crmNotes", "")
        c["nextContactDate"] = serialize_field(data.get("nextContactDate"))
        c["pipelineStage"] = data.get("pipelineStage", "Prospecto")
        c["responsibleId"] = data.get("responsibleId", "")
        c["imageUrl"] = data.get("imageUrl", "")
        c["accessPin"] = data.get("accessPin", "")
        c["disableAutoReminders"] = data.get("disableAutoReminders", False)
        c["priceListId"] = data.get("priceListId", "")
        c["createdAt"] = serialize_field(data.get("createdAt", datetime.now(timezone.utc)))
        return c

    @classmethod
    def _legacy_supplier_to_contact(cls, owner_uid, supplier_id, sandbox):
        """Convierte un proveedor legacy en dict de contacto."""
        coll_name = "sandbox_suppliers" if sandbox else "suppliers"
        doc = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(supplier_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        c = dict(CONTACT_DEFAULTS)
        c["id"] = doc.id
        c["ownerUID"] = owner_uid
        c["types"] = ["proveedor"]
        c["rnc"] = data.get("rnc", "")
        c["razonSocial"] = data.get("name", "")
        c["email"] = data.get("email", "")
        c["telefono"] = data.get("phone", "")
        c["direccion"] = data.get("address", "")
        c["municipio"] = data.get("city", "")
        c["pais"] = data.get("country", "República Dominicana")
        c["notes"] = data.get("notes", "")
        c["tipoPersona"] = data.get("tipoPersona", "fisica")
        c["supplierType"] = data.get("supplierType", "formal")
        c["creditDays"] = data.get("creditDays", 0)
        c["creditLimit"] = data.get("creditLimit", 0.0)
        c["paymentMethod"] = data.get("paymentMethod", "Efectivo")
        c["currency"] = data.get("currency", "DOP")
        c["itbisWithholding"] = data.get("itbisWithholding", False)
        c["isrWithholding"] = data.get("isrWithholding", False)
        c["tipoGastoDGII"] = data.get("tipoGastoDGII", "02")
        c["ecfTypeEmits"] = data.get("ecfTypeEmits", "E31")
        c["estado"] = data.get("estado", "Activo")
        c["createdAt"] = serialize_field(data.get("createdAt", datetime.now(timezone.utc)))
        return c

    @classmethod
    def get_contact(cls, owner_uid, contact_id, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            doc = db_firestore.collection("users").document(owner_uid).collection(_coll_name(sandbox)).document(contact_id).get()
            if doc.exists:
                return _build_contact_from_doc(doc, owner_uid)
        except Exception as e:
            print(f"⚠️ Error al obtener contacto {contact_id}: {e}")

        # Fallback: buscar en legacy
        c = cls._legacy_client_to_contact(owner_uid, contact_id, sandbox)
        if c:
            return c
        c = cls._legacy_supplier_to_contact(owner_uid, contact_id, sandbox)
        if c:
            return c
        return None

        # Fallback: buscar en legacy
        c = cls._legacy_client_to_contact(owner_uid, contact_id, sandbox)
        if c:
            return c
        c = cls._legacy_supplier_to_contact(owner_uid, contact_id, sandbox)
        if c:
            return c
        return None

    @classmethod
    def save_contact(cls, owner_uid, contact_id, contact_dict, sandbox=True):
        contact_dict["id"] = contact_id
        contact_dict["ownerUID"] = owner_uid
        contact_dict["branchId"] = contact_dict.get("branchId", "default-sucursal-principal")
        contact_dict["projectId"] = contact_dict.get("projectId", None)
        if "createdAt" not in contact_dict or not contact_dict["createdAt"]:
            contact_dict["createdAt"] = serialize_field(datetime.now(timezone.utc))
        contact_dict["updatedAt"] = serialize_field(datetime.now(timezone.utc))
        contact_dict["razonSocial"] = contact_dict.get("razonSocial", "").strip()
        contact_dict["rnc"] = "".join(filter(str.isdigit, str(contact_dict.get("rnc", ""))))

        defaults = dict(CONTACT_DEFAULTS)
        for k, v in defaults.items():
            if k not in contact_dict:
                contact_dict[k] = v

        if firebase_initialized and db_firestore is not None:
            try:
                db_firestore.collection("users").document(owner_uid).collection(_coll_name(sandbox)).document(contact_id).set(contact_dict)
            except Exception as e:
                print(f"⚠️ Error al guardar contacto en Firestore: {e}")

        _sync_to_legacy_clients(owner_uid, contact_dict, sandbox)
        _sync_to_legacy_suppliers(owner_uid, contact_dict, sandbox)

        return contact_dict

    @classmethod
    def delete_contact(cls, owner_uid, contact_id, sandbox=True):
        contact = cls.get_contact(owner_uid, contact_id, sandbox)
        if contact:
            _delete_from_legacy_clients(owner_uid, contact_id, sandbox)
            _delete_from_legacy_suppliers(owner_uid, contact_id, sandbox)

        if firebase_initialized and db_firestore is not None:
            try:
                db_firestore.collection("users").document(owner_uid).collection(_coll_name(sandbox)).document(contact_id).delete()
            except Exception as e:
                print(f"⚠️ Error al eliminar contacto {contact_id}: {e}")

    @classmethod
    def get_contact_by_rnc(cls, owner_uid, rnc, sandbox=True):
        rnc_clean = "".join(filter(str.isdigit, str(rnc)))
        if not rnc_clean:
            return None
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(_coll_name(sandbox)).where("rnc", "==", rnc_clean).limit(1).get()
            for doc in docs:
                return _build_contact_from_doc(doc, owner_uid)
        except Exception as e:
            print(f"⚠️ Error al buscar contacto por RNC {rnc}: {e}")

        # Fallback: buscar en legacy clients
        try:
            coll_name = "sandbox_clients" if sandbox else "clients"
            docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).where("rnc", "==", rnc_clean).limit(1).get()
            for doc in docs:
                return cls._legacy_client_to_contact(owner_uid, doc.id, sandbox)
        except Exception as e:
            print(f"⚠️ Error al buscar en clientes legacy por RNC {rnc}: {e}")

        # Fallback: buscar en legacy suppliers
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).where("rnc", "==", rnc_clean).limit(1).get()
            for doc in docs:
                return cls._legacy_supplier_to_contact(owner_uid, doc.id, sandbox)
        except Exception as e:
            print(f"⚠️ Error al buscar en proveedores legacy por RNC {rnc}: {e}")

        return None

    @classmethod
    def get_or_create_contact(cls, owner_uid, rnc, razonSocial, direccion="", sandbox=True):
        existing = cls.get_contact_by_rnc(owner_uid, rnc, sandbox=sandbox)
        if existing:
            return (existing["id"], False)
        contact_id = str(uuid.uuid4())
        contact_dict = {
            "rnc": rnc,
            "razonSocial": razonSocial,
            "direccion": direccion,
        }
        cls.save_contact(owner_uid, contact_id, contact_dict, sandbox=sandbox)
        return (contact_id, True)

    @classmethod
    def search_contacts(cls, owner_uid, query, sandbox=True):
        contacts = cls.get_contacts(owner_uid, sandbox=sandbox)
        q = query.lower().strip()
        if not q:
            return contacts
        results = []
        for c in contacts:
            if q in c["razonSocial"].lower() or q in c["rnc"] or q in c["email"].lower() or q in c["telefono"]:
                results.append(c)
        return results

    @classmethod
    def update_pipeline(cls, owner_uid, contact_id, pipeline_stage, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return
        try:
            db_firestore.collection("users").document(owner_uid).collection(_coll_name(sandbox)).document(contact_id).update({
                "pipelineStage": pipeline_stage,
            })
            c = cls.get_contact(owner_uid, contact_id, sandbox)
            if c and "cliente" in c.get("types", []):
                DatabaseService.update_client_pipeline(owner_uid, contact_id, pipeline_stage, sandbox=sandbox)
        except Exception as e:
            print(f"⚠️ Error al actualizar pipeline del contacto {contact_id}: {e}")
