"""Tests de unificación Proveedores ↔ Contactos (contactos como fuente de verdad).

Cubre:
1. `_sync_to_legacy_suppliers`: save_contact con type 'proveedor' espeja a suppliers.
2. `ContactService.ensure_supplier`: por id, por RNC y creación nueva.
3. Dual read en `SupplierService`: contactos proveedor + legacy, dedup por id, shape.
4. Proyección `_contact_to_supplier` preserva las claves del shape JS.
5. Regresión del NameError `company_id` en rutas de proveedores.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.contact_service import (
    ContactService,
    _sync_to_legacy_clients,
    _sync_to_legacy_suppliers,
)
from app.services.supplier_service import SupplierService, _contact_to_supplier

EXPECTED_KEYS = {
    "id", "rnc", "name", "tipoPersona", "code", "estado", "phone", "email",
    "address", "city", "country", "contactPerson", "supplierType", "currency",
    "creditDays", "creditLimit", "paymentMethod", "ecfTypeEmits",
    "itbisWithholding", "isrWithholding", "tipoGastoDGII", "notes",
    "attachments", "firebaseAttachmentURLs", "branchId", "projectId",
}


class InMemoryFirestore:
    def __init__(self):
        self.store = {}

    def get_collection(self, company_id, coll_name):
        store = self.store

        class MockDocRef:
            def __init__(self, doc_id):
                self.doc_id = doc_id

            def get(self):
                key = (company_id, coll_name, self.doc_id)
                exists = key in store
                doc_mock = MagicMock()
                doc_mock.exists = exists
                doc_mock.id = self.doc_id
                doc_mock.to_dict.return_value = store.get(key)
                return doc_mock

            def set(self, data):
                store[(company_id, coll_name, self.doc_id)] = dict(data)

            def update(self, data):
                key = (company_id, coll_name, self.doc_id)
                merged = dict(store.get(key) or {})
                merged.update(data)
                store[key] = merged

            def delete(self):
                store.pop((company_id, coll_name, self.doc_id), None)

        class MockQuery:
            def __init__(self, filters, limit=None):
                self.filters = filters
                self._limit = limit

            def limit(self, n):
                return MockQuery(self.filters, n)

            def get(self):
                docs = []
                for (cid, cname, did), data in list(store.items()):
                    if cid != company_id or cname != coll_name:
                        continue
                    if all(data.get(f) == v for f, v in self.filters):
                        dm = MagicMock()
                        dm.id = did
                        dm.to_dict.return_value = dict(data)
                        docs.append(dm)
                return docs[:self._limit] if self._limit else docs

            def where(self, field, op, value):
                return MockQuery(self.filters + [(field, value)], self._limit)

        class MockCollRef:
            def document(self, doc_id):
                return MockDocRef(doc_id)

            def where(self, field, op, value):
                return MockQuery([(field, value)])

            def get(self):
                docs = []
                for (cid, cname, did), data in list(store.items()):
                    if cid == company_id and cname == coll_name:
                        dm = MagicMock()
                        dm.id = did
                        dm.to_dict.return_value = dict(data)
                        docs.append(dm)
                return docs

        return MockCollRef()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Sync a la colección legacy suppliers
# ─────────────────────────────────────────────────────────────────────────────

def test_sync_to_legacy_suppliers_on_proveedor_contact():
    with patch("app.services.contact_service.datetime") as mock_dt:
        mock_dt.now.return_value.isoformat.return_value = "2026-10-19T12:00:00"
        with patch("app.services.supplier_service.SupplierService._save_legacy_supplier") as mock_save:
            _sync_to_legacy_suppliers(
                owner_uid="u1",
                contact={
                    "id": "c-100", "types": ["proveedor"], "razonSocial": "Proveedor SA",
                    "rnc": "101010107", "telefono": "8095550000", "email": "p@acme.com",
                    "direccion": "Av. 27", "contactPerson": "Juan",
                },
                sandbox=True, company_id="comp-1",
            )
            mock_save.assert_called_once()
            args = mock_save.call_args
            assert args[0][0] == "u1"
            assert args[0][1] == "c-100"
            sd = args[0][2]
            assert sd["name"] == "Proveedor SA"
            assert sd["rnc"] == "101010107"
            assert sd["contactPerson"] == "Juan"
            assert args[1]["company_id"] == "comp-1"


def test_sync_skipped_when_not_proveedor():
    with patch("app.services.supplier_service.SupplierService._save_legacy_supplier") as mock_save:
        _sync_to_legacy_suppliers(owner_uid="u1", contact={"id": "c-1", "types": ["cliente"]})
        mock_save.assert_not_called()


def test_sync_to_legacy_clients_preserves_dual_types_and_project():
    with patch("app.services.contact_service.DatabaseService.save_client") as mock_save:
        _sync_to_legacy_clients(
            owner_uid="u1",
            contact={
                "id": "c-both", "types": ["cliente", "proveedor"],
                "projectId": "proj-1", "rnc": "101010107",
                "razonSocial": "Ambos SA", "email": "ambos@acme.com",
            },
            sandbox=True, company_id="comp-1",
        )
        client_dict = mock_save.call_args[0][2]
        assert client_dict["types"] == ["cliente", "proveedor"]
        assert client_dict["projectId"] == "proj-1"


# ─────────────────────────────────────────────────────────────────────────────
# 2. ensure_supplier
# ─────────────────────────────────────────────────────────────────────────────

def test_ensure_supplier_by_id_adds_type():
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    fake_fs.store[("comp-1", "sandbox_contacts", "sup-1")] = {
        "id": "sup-1", "razonSocial": "Ya Existe SRL", "rnc": "101010108", "types": [],
    }
    with patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll):
        cid, created = ContactService.ensure_supplier(
            owner_uid="u1", supplier_id="sup-1", sandbox=True, company_id="comp-1")
        assert cid == "sup-1"
        assert created is False
        assert "proveedor" in fake_fs.store[("comp-1", "sandbox_contacts", "sup-1")]["types"]


def test_ensure_supplier_by_rnc_links_existing():
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    fake_fs.store[("comp-1", "sandbox_contacts", "c-exist")] = {
        "id": "c-exist", "razonSocial": "Cliente Proveedor", "rnc": "131880681", "types": ["cliente"],
    }
    with patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.contact_service._sync_to_legacy_suppliers"):
        cid, created = ContactService.ensure_supplier(
            owner_uid="u1", rnc="131880681", razonSocial="Cliente Proveedor",
            sandbox=True, company_id="comp-1")
        assert cid == "c-exist"
        assert created is False
        types = fake_fs.store[("comp-1", "sandbox_contacts", "c-exist")]["types"]
        assert "cliente" in types and "proveedor" in types


def test_ensure_supplier_creates_new_contact():
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.contact_service.uuid") as mock_uuid:
        mock_uuid.uuid4.return_value = "new-sup-id"
        cid, created = ContactService.ensure_supplier(
            owner_uid="u1", rnc="402123456", razonSocial="Nuevo Proveedor",
            sandbox=True, company_id="comp-1")
        assert created is True
        assert cid == "new-sup-id"
        saved = fake_fs.store[("comp-1", "sandbox_contacts", "new-sup-id")]
        assert saved["razonSocial"] == "Nuevo Proveedor"
        assert "proveedor" in saved["types"]
        assert saved["rnc"] == "402123456"


def test_get_or_create_supplier_does_not_write_legacy_on_failure():
    """Si la escritura canónica falla, no debe crear un proveedor legacy huérfano."""
    with patch(
        "app.services.contact_service.ContactService.ensure_supplier",
        side_effect=RuntimeError("contact store unavailable"),
    ), patch(
        "app.services.supplier_service.SupplierService._save_legacy_supplier"
    ) as mock_legacy:
        result = SupplierService.get_or_create_supplier(
            owner_uid="u1", rnc="402123456", name="Proveedor Fallido",
            sandbox=True, company_id="comp-1",
        )
    assert result == (None, False)
    mock_legacy.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Dual read en SupplierService
# ─────────────────────────────────────────────────────────────────────────────

def test_get_suppliers_merges_contacts_and_legacy_without_dupes():
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    # Contacto proveedor NO presente en legacy -> solo vía contactos
    fake_fs.store[("comp-1", "sandbox_contacts", "c-only")] = {
        "id": "c-only", "types": ["proveedor"], "razonSocial": "Solo Contacto",
        "rnc": "101010109", "telefono": "8091111111",
    }
    # Contacto cliente -> no debe aparecer
    fake_fs.store[("comp-1", "sandbox_contacts", "c-cliente")] = {
        "id": "c-cliente", "types": ["cliente"], "razonSocial": "Solo Cliente", "rnc": "999",
    }
    # Legacy ya espejado (mismo id que contacto) -> sin duplicado
    fake_fs.store[("comp-1", "sandbox_suppliers", "c-dup")] = {
        "id": "c-dup", "name": "Espejo Legacy", "rnc": "101010110",
    }
    fake_fs.store[("comp-1", "sandbox_contacts", "c-dup")] = {
        "id": "c-dup", "types": ["proveedor"], "razonSocial": "Espejo Legacy", "rnc": "101010110",
    }

    with patch("app.services.supplier_service.firebase_initialized", True), \
         patch("app.services.supplier_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll):

        suppliers = SupplierService.get_suppliers(owner_uid="u1", sandbox=True, company_id="comp-1")
        ids = sorted(s["id"] for s in suppliers)
        assert ids == ["c-dup", "c-only"]
        assert all(s["id"] != "c-cliente" for s in suppliers)


def test_get_contacts_with_legacy_includes_legacy_suppliers():
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    fake_fs.store[("comp-1", "sandbox_contacts", "c-only")] = {
        "id": "c-only", "types": ["proveedor"], "razonSocial": "Solo Contacto",
        "rnc": "101010109",
    }
    fake_fs.store[("comp-1", "sandbox_contacts", "c-cliente")] = {
        "id": "c-cliente", "types": ["cliente"], "razonSocial": "Solo Cliente",
        "rnc": "999",
    }
    fake_fs.store[("comp-1", "sandbox_contacts", "c-dup")] = {
        "id": "c-dup", "types": ["proveedor"], "razonSocial": "Espejo Legacy",
        "rnc": "101010110",
    }
    fake_fs.store[("comp-1", "sandbox_suppliers", "c-dup")] = {
        "id": "c-dup", "name": "Espejo Legacy", "rnc": "101010110",
    }
    # Proveedor legacy con el mismo id que un contacto sin rol proveedor
    fake_fs.store[("comp-1", "sandbox_contacts", "c-roleless")] = {
        "id": "c-roleless", "types": ["cliente"], "razonSocial": "Cliente Sin Rol",
        "rnc": "101010140",
    }
    fake_fs.store[("comp-1", "sandbox_suppliers", "c-roleless")] = {
        "id": "c-roleless", "name": "Cliente Sin Rol", "rnc": "101010140",
    }
    fake_fs.store[("comp-1", "sandbox_suppliers", "c-legacy")] = {
        "id": "c-legacy", "name": "Proveedor Legacy", "rnc": "101010130",
        "phone": "8092222222", "email": "legacy@acme.com",
    }

    with patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service.db_firestore", object()), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.supplier_service.firebase_initialized", True), \
         patch("app.services.supplier_service._company_coll", side_effect=fake_company_coll):
        contacts = ContactService.get_contacts_with_legacy(
            owner_uid="u1", sandbox=True, company_id="comp-1")
        by_id = {c["id"]: c for c in contacts}
        assert sorted(by_id) == ["c-cliente", "c-dup", "c-legacy", "c-only", "c-roleless"]

        legacy = by_id["c-legacy"]
        assert legacy["types"] == ["proveedor"]
        assert legacy["razonSocial"] == "Proveedor Legacy"
        assert legacy["telefono"] == "8092222222"
        assert legacy["email"] == "legacy@acme.com"
        # El contacto existente con el mismo id hereda el rol proveedor
        assert "proveedor" in by_id["c-roleless"]["types"]


def test_get_supplier_fallback_to_contact():
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    fake_fs.store[("comp-1", "sandbox_contacts", "c-only")] = {
        "id": "c-only", "types": ["proveedor"], "razonSocial": "Solo Contacto",
        "rnc": "101010109",
    }
    with patch("app.services.supplier_service.firebase_initialized", True), \
         patch("app.services.supplier_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll):
        s = SupplierService.get_supplier(owner_uid="u1", supplier_id="c-only",
                                        sandbox=True, company_id="comp-1")
        assert s is not None
        assert s["name"] == "Solo Contacto"


def test_get_supplier_by_rnc_fallback_to_contact():
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    fake_fs.store[("comp-1", "sandbox_contacts", "c-only")] = {
        "id": "c-only", "types": ["proveedor"], "razonSocial": "Solo Contacto",
        "rnc": "101010109",
    }
    with patch("app.services.supplier_service.firebase_initialized", True), \
         patch("app.services.supplier_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll):
        s = SupplierService.get_supplier_by_rnc(rnc="101010109", owner_uid="u1",
                                                sandbox=True, company_id="comp-1")
        assert s is not None
        assert s["id"] == "c-only"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Proyección de shape
# ─────────────────────────────────────────────────────────────────────────────

def test_contact_to_supplier_shape_has_all_keys():
    projected = _contact_to_supplier({
        "id": "c-1", "razonSocial": "Shape SA", "rnc": "101010111",
        "telefono": "8090000000", "email": "s@acme.com",
    })
    missing = EXPECTED_KEYS - set(projected.keys())
    assert not missing, f"Faltan claves del shape: {missing}"
    assert projected["id"] == "c-1"
    assert projected["name"] == "Shape SA"
    assert projected["branchId"] == "default-sucursal-principal"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Regresión NameError company_id en rutas
# ─────────────────────────────────────────────────────────────────────────────

def test_supplier_routes_reference_company_id():
    """Las rutas que llaman a servicios deben proveer company_id (bug original)."""
    import inspect
    from app.web import suppliers as suppliers_module

    for fn in (suppliers_module.ajax_create_supplier, suppliers_module.delete_supplier,
               suppliers_module.list_suppliers, suppliers_module.new_supplier):
        src = inspect.getsource(fn)
        assert "company_id" in src, f"{fn.__name__} no propaga company_id"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Roles múltiples: quitar un rol sin borrar el contacto
# ─────────────────────────────────────────────────────────────────────────────

def _fs_patches(fake_fs):
    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)
    return (
        patch("app.services.contact_service.firebase_initialized", True),
        patch("app.services.contact_service.db_firestore", object()),
        patch("app.services.contact_service._company_coll", side_effect=fake_company_coll),
        patch("app.services.contact_service.DatabaseService.save_client"),
        patch("app.services.supplier_service.firebase_initialized", False),
        patch("app.services.customer_account_service.CustomerAccountService.ensure_for_contact", return_value=None),
    )


def test_remove_role_keeps_contact_when_other_role_remains():
    fake_fs = InMemoryFirestore()
    fake_fs.store[("comp-1", "sandbox_contacts", "c-both")] = {
        "id": "c-both", "razonSocial": "Contacto Ambos", "rnc": "101010120",
        "email": "ambos@acme.com", "types": ["cliente", "proveedor"],
    }
    fake_fs.store[("comp-1", "sandbox_clients", "c-both")] = {"id": "c-both", "razonSocial": "Contacto Ambos"}
    fake_fs.store[("comp-1", "sandbox_suppliers", "c-both")] = {"id": "c-both", "name": "Contacto Ambos"}

    p1, p2, p3, p4, p5, p6 = _fs_patches(fake_fs)
    with p1, p2, p3, p4, p5, p6:
        removed = ContactService.remove_role(
            owner_uid="u1", contact_id="c-both", role="proveedor",
            sandbox=True, company_id="comp-1",
        )
        assert removed is True
        kept = ContactService.get_contact("u1", "c-both", sandbox=True, company_id="comp-1")
        assert kept is not None
        assert kept["types"] == ["cliente"]

    assert ("comp-1", "sandbox_suppliers", "c-both") not in fake_fs.store
    assert ("comp-1", "sandbox_clients", "c-both") in fake_fs.store


def test_remove_role_deletes_contact_when_last_role_removed():
    fake_fs = InMemoryFirestore()
    fake_fs.store[("comp-1", "sandbox_contacts", "c-only-client")] = {
        "id": "c-only-client", "razonSocial": "Solo Cliente", "rnc": "101010121",
        "email": "solo@acme.com", "types": ["cliente"],
    }
    fake_fs.store[("comp-1", "sandbox_clients", "c-only-client")] = {"id": "c-only-client"}

    p1, p2, p3, p4, p5, p6 = _fs_patches(fake_fs)
    with p1, p2, p3, p4, p5, p6:
        removed = ContactService.remove_role(
            owner_uid="u1", contact_id="c-only-client", role="cliente",
            sandbox=True, company_id="comp-1",
        )
        assert removed is True
        assert ContactService.get_contact("u1", "c-only-client", sandbox=True, company_id="comp-1") is None

    assert ("comp-1", "sandbox_clients", "c-only-client") not in fake_fs.store


def test_remove_role_returns_false_when_role_absent():
    fake_fs = InMemoryFirestore()
    fake_fs.store[("comp-1", "sandbox_contacts", "c-cli")] = {
        "id": "c-cli", "razonSocial": "Cliente", "rnc": "101010122",
        "email": "cli@acme.com", "types": ["cliente"],
    }
    p1, p2, p3, p4, p5, p6 = _fs_patches(fake_fs)
    with p1, p2, p3, p4, p5, p6:
        assert ContactService.remove_role(
            owner_uid="u1", contact_id="c-cli", role="proveedor",
            sandbox=True, company_id="comp-1",
        ) is False
    assert fake_fs.store[("comp-1", "sandbox_contacts", "c-cli")]["types"] == ["cliente"]
