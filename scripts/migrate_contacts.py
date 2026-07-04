"""
Migración one-time: Copia datos de clients → contacts y suppliers → contacts.
- Clientes existentes → contacts con types=["cliente"]
- Proveedores existentes → si ya existe contacto con mismo RNC, fusiona types; si no, crea nuevo
- No elimina colecciones legacy (clients, suppliers permanecen como respaldo)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from app.services.db_service import db_firestore, firebase_initialized
from app.services.contact_service import ContactService, serialize_field, CONTACT_DEFAULTS


def _coll_name(sandbox):
    return "sandbox_contacts" if sandbox else "contacts"


def _serialize(val):
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    return str(val)


def migrate_user(owner_uid, sandbox=True, dry_run=False):
    """Migra clients y suppliers de un owner_uid a contacts."""
    if not firebase_initialized or db_firestore is None:
        print("❌ Firebase no está inicializado.")
        return

    user_ref = db_firestore.collection("users").document(owner_uid)
    coll_name = "sandbox_" if sandbox else ""
    clients_ref = user_ref.collection(f"{'sandbox_' if sandbox else ''}clients")
    suppliers_ref = user_ref.collection(f"{'sandbox_' if sandbox else ''}suppliers")
    contacts_ref = user_ref.collection(_coll_name(sandbox))

    created = 0
    merged = 0
    skipped = 0

    # --- Migrar Clientes ---
    print(f"\n📋 Migrando clientes de {owner_uid} ({'sandbox' if sandbox else 'produccion'})...")
    client_docs = list(clients_ref.get())
    print(f"   → {len(client_docs)} clientes encontrados")

    for doc in client_docs:
        data = doc.to_dict()
        if not data:
            skipped += 1
            continue

        client_id = doc.id
        rnc = "".join(filter(str.isdigit, str(data.get("rnc", ""))))

        # Verificar si ya existe contacto con este RNC
        existing = None
        if rnc:
            existing_docs = list(contacts_ref.where("rnc", "==", rnc).limit(1).get())
            if existing_docs:
                existing = existing_docs[0]

        if existing:
            # Fusionar: agregar "cliente" a types
            existing_data = existing.to_dict()
            existing_types = existing_data.get("types", [])
            if "cliente" not in existing_types:
                existing_types.append("cliente")
                if not dry_run:
                    contacts_ref.document(existing.id).update({"types": existing_types})
                print(f"   🔗 Fusionado cliente {data.get('razonSocial', '')} (RNC: {rnc}) → contacto existente")
                merged += 1
            else:
                skipped += 1
            continue

        # Crear nuevo contacto desde cliente
        contact_dict = dict(CONTACT_DEFAULTS)
        contact_dict.update({
            "types": ["cliente"],
            "rnc": rnc,
            "razonSocial": data.get("razonSocial", ""),
            "email": data.get("email", ""),
            "telefono": data.get("telefono", ""),
            "direccion": data.get("direccion", ""),
            "notes": data.get("crmNotes", ""),
            "nextContactDate": _serialize(data.get("nextContactDate")),
            "pipelineStage": data.get("pipelineStage", "Prospecto"),
            "responsibleId": data.get("responsibleId", ""),
            "imageUrl": data.get("imageUrl", ""),
            "accessPin": data.get("accessPin", ""),
            "disableAutoReminders": data.get("disableAutoReminders", False),
            "priceListId": data.get("priceListId", ""),
            "createdAt": _serialize(data.get("createdAt", datetime.now(timezone.utc))),
        })

        if not dry_run:
            contacts_ref.document(client_id).set(contact_dict)
        print(f"   ✅ Cliente creado: {contact_dict['razonSocial']} (RNC: {rnc}) ID: {client_id}")
        created += 1

    # --- Migrar Proveedores ---
    print(f"\n📋 Migrando proveedores de {owner_uid} ({'sandbox' if sandbox else 'produccion'})...")
    supplier_docs = list(suppliers_ref.get())
    print(f"   → {len(supplier_docs)} proveedores encontrados")

    for doc in supplier_docs:
        data = doc.to_dict()
        if not data:
            skipped += 1
            continue

        supplier_id = doc.id
        rnc = "".join(filter(str.isdigit, str(data.get("rnc", ""))))

        # Verificar si ya existe contacto con este RNC
        existing = None
        if rnc:
            existing_docs = list(contacts_ref.where("rnc", "==", rnc).limit(1).get())
            if existing_docs:
                existing = existing_docs[0]

        if existing:
            # Fusionar: agregar "proveedor" a types
            existing_data = existing.to_dict()
            existing_types = existing_data.get("types", [])
            if "proveedor" not in existing_types:
                existing_types.append("proveedor")
                if not dry_run:
                    # Actualizar también campos de proveedor
                    updates = {
                        "types": existing_types,
                        "tipoPersona": data.get("tipoPersona", "fisica"),
                        "supplierType": data.get("supplierType", "formal"),
                        "creditDays": data.get("creditDays", 0),
                        "creditLimit": data.get("creditLimit", 0.0),
                        "paymentMethod": data.get("paymentMethod", "Efectivo"),
                        "currency": data.get("currency", "DOP"),
                        "itbisWithholding": data.get("itbisWithholding", False),
                        "isrWithholding": data.get("isrWithholding", False),
                        "tipoGastoDGII": data.get("tipoGastoDGII", "02"),
                        "ecfTypeEmits": data.get("ecfTypeEmits", "E31"),
                        "estado": data.get("estado", "Activo"),
                        "municipio": data.get("city", ""),
                        "telefono": data.get("phone", ""),
                    }
                    if not existing_data.get("notes") and data.get("notes"):
                        updates["notes"] = data["notes"]
                    contacts_ref.document(existing.id).update(updates)
                print(f"   🔗 Fusionado proveedor {data.get('name', '')} (RNC: {rnc}) → contacto existente (ahora ambos)")
                merged += 1
            else:
                skipped += 1
            continue

        # Crear nuevo contacto desde proveedor
        contact_dict = dict(CONTACT_DEFAULTS)
        contact_dict.update({
            "types": ["proveedor"],
            "rnc": rnc,
            "razonSocial": data.get("name", ""),
            "email": data.get("email", ""),
            "telefono": data.get("phone", ""),
            "direccion": data.get("address", ""),
            "municipio": data.get("city", ""),
            "pais": data.get("country", "República Dominicana"),
            "notes": data.get("notes", ""),
            "tipoPersona": data.get("tipoPersona", "fisica"),
            "supplierType": data.get("supplierType", "formal"),
            "creditDays": data.get("creditDays", 0),
            "creditLimit": data.get("creditLimit", 0.0),
            "paymentMethod": data.get("paymentMethod", "Efectivo"),
            "currency": data.get("currency", "DOP"),
            "itbisWithholding": data.get("itbisWithholding", False),
            "isrWithholding": data.get("isrWithholding", False),
            "tipoGastoDGII": data.get("tipoGastoDGII", "02"),
            "ecfTypeEmits": data.get("ecfTypeEmits", "E31"),
            "estado": data.get("estado", "Activo"),
            "createdAt": _serialize(data.get("createdAt", datetime.now(timezone.utc))),
        })

        if not dry_run:
            contacts_ref.document(supplier_id).set(contact_dict)
        print(f"   ✅ Proveedor creado: {contact_dict['razonSocial']} (RNC: {rnc}) ID: {supplier_id}")
        created += 1

    print(f"\n{'='*50}")
    print(f"📊 Resumen para {owner_uid}:")
    print(f"   Creados:  {created}")
    print(f"   Fusionados: {merged}")
    print(f"   Omitidos: {skipped}")
    print(f"{'='*50}")
    return {"created": created, "merged": merged, "skipped": skipped}


def get_all_user_uids():
    """Obtiene todos los UIDs de usuarios registrados en Firestore."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        docs = db_firestore.collection("users").get()
        return [doc.id for doc in docs]
    except Exception as e:
        print(f"⚠️ Error al obtener usuarios: {e}")
        return []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrar clientes y proveedores a contactos unificados")
    parser.add_argument("--owner-uid", help="UID específico del owner (opcional, sino migra todos)")
    parser.add_argument("--sandbox", action="store_true", default=True, help="Usar colecciones sandbox (por defecto True)")
    parser.add_argument("--production", action="store_true", help="Usar colecciones de producción")
    parser.add_argument("--dry-run", action="store_true", help="Solo simular, no escribir en Firestore")
    args = parser.parse_args()

    sandbox = not args.production

    print("🚀 Iniciando migración de clientes y proveedores → contactos...")
    print(f"   Entorno: {'sandbox' if sandbox else 'produccion'}")
    print(f"   Dry run: {args.dry_run}")

    if not firebase_initialized:
        print("❌ Firebase no está inicializado. Asegúrate de que las credenciales estén configuradas.")
        sys.exit(1)

    if args.owner_uid:
        results = [migrate_user(args.owner_uid, sandbox=sandbox, dry_run=args.dry_run)]
    else:
        uids = get_all_user_uids()
        print(f"\n👥 Usuarios encontrados: {len(uids)}")
        results = []
        for uid in uids:
            r = migrate_user(uid, sandbox=sandbox, dry_run=args.dry_run)
            results.append(r)

    total_created = sum(r["created"] for r in results)
    total_merged = sum(r["merged"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)

    print(f"\n{'='*50}")
    print(f"🏁 MIGRACIÓN COMPLETADA")
    print(f"   Total creados:  {total_created}")
    print(f"   Total fusionados (mismo RNC): {total_merged}")
    print(f"   Total omitidos: {total_skipped}")
    print(f"{'='*50}")
