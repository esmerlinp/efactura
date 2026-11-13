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
    "regimenDgii": "",
    "regimenDgiiNormalized": "",
    "estadoDgii": "",
    "categoriaDgii": "",
    "actividadDgii": "",
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


def _legacy_supplier_to_contact(supplier):
    """Proyecta un proveedor legacy (`suppliers`) al shape canónico de contacto."""
    contact = dict(CONTACT_DEFAULTS)
    contact.update({
        "id": supplier.get("id", ""),
        "types": ["proveedor"],
        "rnc": supplier.get("rnc", ""),
        "razonSocial": supplier.get("name") or supplier.get("razonSocial", ""),
        "email": supplier.get("email", ""),
        "telefono": supplier.get("phone") or supplier.get("telefono", ""),
        "direccion": supplier.get("address") or supplier.get("direccion", ""),
        "municipio": supplier.get("city") or supplier.get("municipio", ""),
        "pais": supplier.get("country") or supplier.get("pais", "República Dominicana"),
        "tipoPersona": supplier.get("tipoPersona", "fisica"),
        "supplierType": supplier.get("supplierType", "formal"),
        "currency": supplier.get("currency", "DOP"),
        "creditDays": supplier.get("creditDays", 0),
        "creditLimit": supplier.get("creditLimit", 0.0),
        "paymentMethod": supplier.get("paymentMethod", "Efectivo"),
        "ecfTypeEmits": supplier.get("ecfTypeEmits", "E31"),
        "itbisWithholding": supplier.get("itbisWithholding", False),
        "isrWithholding": supplier.get("isrWithholding", False),
        "tipoGastoDGII": supplier.get("tipoGastoDGII", "02"),
        "estado": supplier.get("estado", "Activo"),
        "notes": supplier.get("notes", ""),
        "code": supplier.get("code", ""),
        "contactPerson": supplier.get("contactPerson", ""),
        "attachments": supplier.get("attachments", []),
        "firebaseAttachmentURLs": supplier.get("firebaseAttachmentURLs", []),
        "branchId": supplier.get("branchId", "default-sucursal-principal"),
        "projectId": supplier.get("projectId"),
        "createdAt": supplier.get("createdAt", ""),
        "updatedAt": supplier.get("updatedAt", ""),
    })
    return contact


# =========================================================================
# Sync helpers — write to legacy collections for backward compatibility
# =========================================================================

def _coll_ref(owner_uid=None, sandbox=True, company_id=None):
    from app.services.company_authorization import require_company_id
    return _company_coll(
        company_id=require_company_id(company_id, "ContactService"),
        coll_name=_coll_name(sandbox),
    )


def _sync_to_legacy_clients(owner_uid=None, contact=None, sandbox=True, company_id=None):
    """Sync contact data to legacy clients collection if type includes 'cliente'."""
    if "cliente" not in contact.get("types", []):
        return
    client_dict = {
        "types": contact.get("types", ["cliente"]),
        "branchId": contact.get("branchId", "default-sucursal-principal"),
        "projectId": contact.get("projectId"),
        "rnc": contact.get("rnc", ""),
        "razonSocial": contact.get("razonSocial", ""),
        "email": contact.get("email", ""),
        "companyEmail": contact.get("companyEmail", ""),
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
        "foreignTaxId": contact.get("foreignTaxId", ""),
        "regimenDgii": contact.get("regimenDgii", ""),
        "regimenDgiiNormalized": contact.get("regimenDgiiNormalized", ""),
        "estadoDgii": contact.get("estadoDgii", ""),
        "categoriaDgii": contact.get("categoriaDgii", ""),
        "actividadDgii": contact.get("actividadDgii", ""),
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
        "contactPerson": contact.get("contactPerson", ""),
        "code": contact.get("code", ""),
        "attachments": contact.get("attachments", []),
        "firebaseAttachmentURLs": contact.get("firebaseAttachmentURLs", []),
        "branchId": contact.get("branchId", "default-sucursal-principal"),
        "projectId": contact.get("projectId"),
        "updatedAt": contact.get("updatedAt", datetime.now(timezone.utc).isoformat()),
    }
    SupplierService._save_legacy_supplier(owner_uid, contact["id"], supplier_dict, sandbox=sandbox, company_id=company_id)


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
                if not c.get("isDeleted", False):
                    contacts.append(c)
        except Exception as e:
            print(f"⚠️ Error al obtener contactos: {e}")

        contacts.sort(key=lambda x: x["razonSocial"].lower())
        return contacts

    @classmethod
    def get_contacts_with_legacy(cls, owner_uid=None, sandbox=True, company_id=None):
        """Contactos canónicos + proveedores de `SupplierService` (misma fuente que /suppliers).

        Garantiza paridad con el listado de proveedores: incluye tanto contactos
        canónicos con rol `proveedor` como proveedores legacy aún no migrados.
        Deduplica por `id`; si un proveedor comparte id con un contacto existente
        sin rol `proveedor`, se añade el rol en memoria para que aparezca en la
        pestaña de proveedores.
        """
        contacts = cls.get_contacts(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
        by_id = {c.get("id"): c for c in contacts if c.get("id")}

        try:
            from app.services.supplier_service import SupplierService
            suppliers = SupplierService.get_suppliers(
                owner_uid=owner_uid, sandbox=sandbox, company_id=company_id
            )
        except Exception as e:
            print(f"⚠️ Error al obtener proveedores para contactos: {e}")
            return contacts

        added = False
        for s in suppliers:
            sid = s.get("id")
            existing = by_id.get(sid)
            if existing:
                types = list(existing.get("types") or [])
                if "proveedor" not in types:
                    types.append("proveedor")
                    existing["types"] = types
                continue
            c = _legacy_supplier_to_contact(s)
            contacts.append(c)
            by_id[sid] = c
            added = True

        if added:
            contacts.sort(key=lambda x: (x.get("razonSocial") or "").lower())
        return contacts

    @classmethod
    def get_contact(cls, owner_uid=None, contact_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            doc = _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(contact_id).get()
            if doc.exists:
                c = _build_contact_from_doc(doc, owner_uid)
                if c.get("isDeleted", False):
                    return None
                return c
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
        if contact_dict.get("customer_category") == "FOREIGN":
            contact_dict["rnc"] = str(contact_dict.get("rnc", "")).strip()
        else:
            contact_dict["rnc"] = "".join(filter(str.isdigit, str(contact_dict.get("rnc", ""))))

        existing_contact = None
        if contact_id:
            try:
                existing_contact = cls.get_contact(
                    owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id
                )
            except Exception:
                existing_contact = None

        if "cliente" in contact_dict.get("types", []):
            from app.services.customer_account_service import CustomerAccountService
            was_client = bool(existing_contact and "cliente" in (existing_contact.get("types") or []))
            if not was_client and not CustomerAccountService.valid_email(contact_dict.get("email")):
                raise ValueError("El correo electrónico del cliente es obligatorio y debe ser válido.")

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

        existing_types = (existing_contact or {}).get("types") or []
        new_types = contact_dict.get("types") or []
        if "cliente" in existing_types and "cliente" not in new_types:
            _delete_from_legacy_clients(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
        if "proveedor" in existing_types and "proveedor" not in new_types:
            _delete_from_legacy_suppliers(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)

        if "cliente" in contact_dict.get("types", []):
            from app.services.customer_account_service import CustomerAccountService
            try:
                account_id = CustomerAccountService.ensure_for_contact(contact_dict, owner_uid, company_id, sandbox)
            except ValueError:
                # Contactos legacy pueden conservar su rol de cliente sin email válido.
                account_id = None
            if account_id:
                contact_dict["customerId"] = account_id
                _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(contact_id).set(
                    {"customerId": account_id}, merge=True
                )

        return contact_dict

    @classmethod
    def delete_contact(cls, owner_uid=None, contact_id=None, sandbox=True, company_id=None, deleted_by=""):
        """Eliminación segura (Soft Delete CRM-08) preservando documentos fiscales."""
        contact = cls.get_contact(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
        if not contact:
            return False

        contact["isDeleted"] = True
        contact["deletedAt"] = datetime.now(timezone.utc).isoformat()
        contact["deletedBy"] = deleted_by or "Sistema"
        contact["estado"] = "Inactivo"

        if firebase_initialized and db_firestore is not None:
            try:
                _coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(contact_id).set(contact)
            except Exception as e:
                print(f"⚠️ Error al realizar soft delete de contacto {contact_id}: {e}")
                return False

        _delete_from_legacy_clients(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
        _delete_from_legacy_suppliers(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
        return True

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
    def get_or_create_contact(cls, owner_uid=None, rnc=None, razonSocial=None, direccion="", sandbox=True, company_id=None, types=None, extra=None):
        existing = cls.get_contact_by_rnc(owner_uid=owner_uid, rnc=rnc, sandbox=sandbox, company_id=company_id)
        if existing:
            return (existing["id"], False)
        contact_id = str(uuid.uuid4())
        contact_dict = {
            "rnc": rnc,
            "razonSocial": razonSocial,
            "direccion": direccion,
        }
        if types:
            contact_dict["types"] = list(types)
        if extra:
            contact_dict.update(extra)
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
    def ensure_supplier(cls, owner_uid=None, supplier_id=None, rnc=None, razonSocial=None, direccion="", sandbox=True, company_id=None):
        """Asegura que existe un contacto con tipo 'proveedor'. Devuelve (contact_id, created)."""
        # Si viene supplier_id y existe
        if supplier_id:
            c = cls.get_contact(owner_uid=owner_uid, contact_id=supplier_id, sandbox=sandbox, company_id=company_id)
            if c:
                types = list(c.get("types", []))
                if "proveedor" not in types:
                    types.append("proveedor")
                    c2 = dict(c)
                    c2["types"] = types
                    cls.save_contact(owner_uid=owner_uid, contact_id=supplier_id, contact_dict=c2, sandbox=sandbox, company_id=company_id)
                return (supplier_id, False)

        rnc_clean = "".join(filter(str.isdigit, str(rnc)))
        if rnc_clean:
            c = cls.get_contact_by_rnc(owner_uid=owner_uid, rnc=rnc_clean, sandbox=sandbox, company_id=company_id)
            if c:
                types = list(c.get("types", []))
                if "proveedor" not in types:
                    types.append("proveedor")
                    c2 = dict(c)
                    c2["types"] = types
                    cls.save_contact(owner_uid=owner_uid, contact_id=c["id"], contact_dict=c2, sandbox=sandbox, company_id=company_id)
                return (c["id"], False)

        rs = (razonSocial or "").strip()
        if not rs and not rnc_clean:
            return (None, False)

        contact_id = str(uuid.uuid4())
        contact_dict = {
            "rnc": rnc_clean,
            "razonSocial": rs or rnc_clean,
            "direccion": direccion,
            "types": ["proveedor"],
        }
        cls.save_contact(owner_uid=owner_uid, contact_id=contact_id, contact_dict=contact_dict, sandbox=sandbox, company_id=company_id)
        return (contact_id, True)
    @classmethod
    def remove_role(cls, owner_uid=None, contact_id=None, role=None, sandbox=True, company_id=None):
        """Quita un rol del contacto sin borrar la entidad si conserva otros roles.

        Si el contacto se queda sin roles, se elimina por completo. Si conserva
        otros roles, solo se elimina el espejo legacy del rol retirado.
        Devuelve True si el rol fue retirado (o el contacto eliminado por quedar
        sin roles), False si el contacto no existe o no tenía ese rol.
        """
        contact = cls.get_contact(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
        if not contact:
            return False

        types = [t for t in (contact.get("types") or []) if t != role]
        if len(types) == len(contact.get("types") or []):
            return False

        if not types:
            return cls.delete_contact(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)

        updated = dict(contact)
        updated["types"] = types
        cls.save_contact(owner_uid=owner_uid, contact_id=contact_id, contact_dict=updated, sandbox=sandbox, company_id=company_id)

        if role == "cliente":
            _delete_from_legacy_clients(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
        elif role == "proveedor":
            _delete_from_legacy_suppliers(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
        return True

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
