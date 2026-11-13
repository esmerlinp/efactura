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


def _contact_to_supplier(contact):
    """Proyecta un contacto con tipo 'proveedor' al shape legacy de supplier."""
    s = {
        "id": contact.get("id", ""),
        "rnc": contact.get("rnc", ""),
        "name": contact.get("razonSocial", ""),
        "tipoPersona": contact.get("tipoPersona", "fisica"),
        "code": contact.get("code", ""),
        "estado": contact.get("estado", "Activo"),
        "phone": contact.get("telefono", ""),
        "email": contact.get("email", ""),
        "address": contact.get("direccion", ""),
        "city": contact.get("municipio", ""),
        "country": contact.get("pais", "República Dominicana"),
        "contactPerson": contact.get("contactPerson", ""),
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
        "attachments": contact.get("attachments", []),
        "firebaseAttachmentURLs": contact.get("firebaseAttachmentURLs", []),
        "createdAt": contact.get("createdAt", ""),
        "updatedAt": contact.get("updatedAt", ""),
        "branchId": contact.get("branchId", "default-sucursal-principal"),
        "projectId": contact.get("projectId"),
    }
    return s


def _require_company_id(company_id):
    from app.services.company_authorization import require_company_id
    return require_company_id(company_id, "SupplierService")


class SupplierService:

    @classmethod
    def _contacts_as_suppliers(cls, owner_uid=None, sandbox=True, company_id=None):
        """Contactos con tipo 'proveedor' proyectados al shape de supplier (dual read)."""
        company_id = _require_company_id(company_id)
        try:
            from app.services.contact_service import ContactService
            contacts = ContactService.get_contacts(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
        except Exception as e:
            print(f"⚠️ Error al leer contactos proveedor: {e}")
            return []
        return [_contact_to_supplier(c) for c in contacts if "proveedor" in c.get("types", [])]

    @classmethod
    def get_suppliers(cls, owner_uid=None, sandbox=True, branch_id=None, project_id=None, company_id=None):
        company_id = _require_company_id(company_id)
        if not firebase_initialized or db_firestore is None:
            return []
        suppliers = []
        seen_ids = set()
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            docs = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                suppliers.append(data)
                seen_ids.add(doc.id)
        except Exception as e:
            print(f"⚠️ Error al obtener proveedores: {e}")
        # Dual read: contactos con tipo proveedor que aún no estén en legacy
        for s in cls._contacts_as_suppliers(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id):
            if s["id"] not in seen_ids:
                suppliers.append(s)
                seen_ids.add(s["id"])
        suppliers.sort(key=lambda x: (x.get("name") or "").lower())
        if branch_id:
            suppliers = [s for s in suppliers if s.get("branchId") == branch_id]
        if project_id == '__no_project__':
            suppliers = [s for s in suppliers if not s.get("projectId")]
        elif project_id:
            suppliers = [s for s in suppliers if s.get("projectId") == project_id]
        return suppliers

    @classmethod
    def get_supplier(cls, owner_uid=None, supplier_id=None, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            doc = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).document(supplier_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener proveedor {supplier_id}: {e}")
        # Fallback dual read: contacto con tipo proveedor
        try:
            from app.services.contact_service import ContactService
            c = ContactService.get_contact(owner_uid=owner_uid, contact_id=supplier_id, sandbox=sandbox, company_id=company_id)
            if c and "proveedor" in c.get("types", []):
                return _contact_to_supplier(c)
        except Exception:
            pass
        return None

    @classmethod
    def _save_legacy_supplier(cls, owner_uid=None, supplier_id=None, supplier_dict=None, sandbox=True, company_id=None):
        """Escribe el espejo legacy `suppliers` (NO es la fuente canónica).

        La creación/edición de proveedores debe hacerse vía
        `ContactService.save_contact` / `ContactService.ensure_supplier`, que
        escribe en `contacts` y luego invoca este método como espejo.
        """
        company_id = _require_company_id(company_id)
        supplier_dict["id"] = supplier_id
        supplier_dict["ownerUID"] = owner_uid
        supplier_dict["branchId"] = supplier_dict.get("branchId", "default-sucursal-principal")
        supplier_dict["projectId"] = supplier_dict.get("projectId", None)
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
                _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).document(supplier_id).set(supplier_dict)
            except Exception as e:
                print(f"⚠️ Error al guardar proveedor en Firestore: {e}")
        return supplier_dict

    @classmethod
    def delete_supplier(cls, owner_uid=None, supplier_id=None, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        if not firebase_initialized or db_firestore is None:
            return
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).document(supplier_id).delete()
        except Exception as e:
            print(f"⚠️ Error al eliminar proveedor {supplier_id}: {e}")

    @classmethod
    def get_supplier_by_rnc(cls, owner_uid=None, rnc=None, sandbox=True, company_id=None):
        rnc_clean = "".join(filter(str.isdigit, str(rnc)))
        if not rnc_clean:
            return None
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            coll_name = "sandbox_suppliers" if sandbox else "suppliers"
            docs = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=coll_name).where("rnc", "==", rnc_clean).limit(1).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al buscar proveedor por RNC {rnc}: {e}")
        # Fallback dual read: contacto con tipo proveedor
        try:
            from app.services.contact_service import ContactService
            c = ContactService.get_contact_by_rnc(owner_uid=owner_uid, rnc=rnc_clean, sandbox=sandbox, company_id=company_id)
            if c and "proveedor" in c.get("types", []):
                return _contact_to_supplier(c)
        except Exception:
            pass
        return None

    @classmethod
    def get_or_create_supplier(cls, owner_uid=None, rnc=None, name=None, address="", sandbox=True, company_id=None):
        """Crea/asegura un proveedor como contacto (fuente de verdad) con espejo legacy.

        Delega en ContactService.ensure_supplier para mantener una sola vía de
        escritura. Devuelve (supplier_id, created).
        """
        try:
            from app.services.contact_service import ContactService
            return ContactService.ensure_supplier(
                owner_uid=owner_uid, supplier_id=None, rnc=rnc, razonSocial=name,
                direccion=address or "", sandbox=sandbox, company_id=company_id,
            )
        except Exception as e:
            # No crear proveedores legacy huérfanos: la escritura canónica falló.
            print(f"⚠️ Error al asegurar proveedor {rnc}: {e}")
            return (None, False)
