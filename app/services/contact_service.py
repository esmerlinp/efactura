import uuid
from datetime import datetime, timezone

try:
    from app.services.db_service import db_firestore, firebase_initialized, DatabaseService, _company_coll
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

def _coll_ref(owner_uid=None, sandbox=True, company_id=None):
    if company_id:
        return _company_coll(company_id=company_id, coll_name=_coll_name(sandbox))
    return _company_coll(owner_uid=owner_uid, coll_name=_coll_name(sandbox))


def _sync_to_legacy_clients(owner_uid=None, contact=None, sandbox=True, company_id=None):
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
        "customer_category": contact.get("customer_category", "NORMAL"),
    }
    DatabaseService.save_client(owner_uid, contact["id"], client_dict, sandbox=sandbox, company_id=company_id)


def _sync_to_legacy_suppliers(owner_uid=None, contact=None, sandbox=True, company_id=None):
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
    SupplierService.save_supplier(owner_uid, contact["id"], supplier_dict, sandbox=sandbox, company_id=company_id)


def _delete_from_legacy_clients(owner_uid=None, contact_id=None, sandbox=True, company_id=None):
    """Delete from legacy clients collection."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_name = "sandbox_clients" if sandbox else "clients"
        ref = _company_coll(company_id=company_id or owner_uid, coll_name=coll_name) if company_id else _company_coll(owner_uid=owner_uid, coll_name=coll_name)
        ref.document(contact_id).delete()
    except Exception as e:
        print(f"⚠️ Error al eliminar cliente legacy {contact_id}: {e}")


def _delete_from_legacy_suppliers(owner_uid=None, contact_id=None, sandbox=True, company_id=None):
    """Delete from legacy suppliers collection."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_name = "sandbox_suppliers" if sandbox else "suppliers"
        ref = _company_coll(company_id=company_id or owner_uid, coll_name=coll_name) if company_id else _company_coll(owner_uid=owner_uid, coll_name=coll_name)
        ref.document(contact_id).delete()
    except Exception as e:
        print(f"⚠️ Error al eliminar proveedor legacy {contact_id}: {e}")


# =========================================================================
# CRUD Operations
# =========================================================================

class ContactService:

    @classmethod
    def get_contacts(cls, owner_uid=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return []
        contacts = []
        try:
            docs = _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).get()
            for doc in docs:
                c = _build_contact_from_doc(doc, owner_uid)
                contacts.append(c)
        except Exception as e:
            print(f"⚠️ Error al obtener contactos: {e}")

        contacts.sort(key=lambda x: x["razonSocial"].lower())
        return contacts

    @classmethod
    def get_contact(cls, owner_uid=None, contact_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            doc = _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(contact_id).get()
            if doc.exists:
                return _build_contact_from_doc(doc, owner_uid)
        except Exception as e:
            print(f"⚠️ Error al obtener contacto {contact_id}: {e}")

        return None

    @classmethod
    def save_contact(cls, owner_uid=None, contact_id=None, contact_dict=None, sandbox=True, company_id=None):
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
                _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(contact_id).set(contact_dict)
            except Exception as e:
                print(f"⚠️ Error al guardar contacto en Firestore: {e}")

        _sync_to_legacy_clients(owner_uid=owner_uid, contact=contact_dict, sandbox=sandbox, company_id=company_id)
        _sync_to_legacy_suppliers(owner_uid=owner_uid, contact=contact_dict, sandbox=sandbox, company_id=company_id)

        return contact_dict

    @classmethod
    def delete_contact(cls, owner_uid=None, contact_id=None, sandbox=True, company_id=None):
        contact = cls.get_contact(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
        if contact:
            _delete_from_legacy_clients(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
            _delete_from_legacy_suppliers(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)

        if firebase_initialized and db_firestore is not None:
            try:
                _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(contact_id).delete()
            except Exception as e:
                print(f"⚠️ Error al eliminar contacto {contact_id}: {e}")

    @classmethod
    def get_contact_by_rnc(cls, owner_uid=None, rnc=None, sandbox=True, company_id=None):
        rnc_clean = "".join(filter(str.isdigit, str(rnc)))
        if not rnc_clean:
            return None
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            docs = _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).where("rnc", "==", rnc_clean).limit(1).get()
            for doc in docs:
                return _build_contact_from_doc(doc, owner_uid)
        except Exception as e:
            print(f"⚠️ Error al buscar contacto por RNC {rnc}: {e}")

        return None

    @classmethod
    def get_or_create_contact(cls, owner_uid=None, rnc=None, razonSocial=None, direccion="", sandbox=True, company_id=None):
        existing = cls.get_contact_by_rnc(owner_uid=owner_uid, rnc=rnc, sandbox=sandbox, company_id=company_id)
        if existing:
            return (existing["id"], False)
        contact_id = str(uuid.uuid4())
        contact_dict = {
            "rnc": rnc,
            "razonSocial": razonSocial,
            "direccion": direccion,
        }
        cls.save_contact(owner_uid=owner_uid, contact_id=contact_id, contact_dict=contact_dict, sandbox=sandbox, company_id=company_id)
        return (contact_id, True)

    @classmethod
    def search_contacts(cls, owner_uid=None, query=None, sandbox=True, company_id=None):
        contacts = cls.get_contacts(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
        q = query.lower().strip()
        if not q:
            return contacts
        results = []
        for c in contacts:
            if q in c["razonSocial"].lower() or q in c["rnc"] or q in c["email"].lower() or q in c["telefono"]:
                results.append(c)
        return results

    @classmethod
    def update_pipeline(cls, owner_uid=None, contact_id=None, pipeline_stage=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return
        try:
            _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(contact_id).update({
                "pipelineStage": pipeline_stage,
            })
            c = cls.get_contact(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
            if c and "cliente" in c.get("types", []):
                DatabaseService.update_client_pipeline(owner_uid, contact_id, pipeline_stage, sandbox=sandbox, company_id=company_id)
        except Exception as e:
            print(f"⚠️ Error al actualizar pipeline del contacto {contact_id}: {e}")
