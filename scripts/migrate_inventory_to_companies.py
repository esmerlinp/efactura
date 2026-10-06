#!/usr/bin/env python3
"""
Script de diagnóstico y migración de inventario a rutas canónicas multiempresa.

Reubica documentos de:
  users/{owner_uid}/inventory_stock
  users/{owner_uid}/inventory_transactions
  users/{owner_uid}/inventory_lots
  users/{owner_uid}/inventory_cost_ledger

Hacia:
  companies/{company_id}/inventory_stock (o sandbox_inventory_stock)
  companies/{company_id}/inventory_transactions
  companies/{company_id}/inventory_lots
  companies/{company_id}/inventory_cost_ledger

Uso:
  python scripts/migrate_inventory_to_companies.py --dry-run
  python scripts/migrate_inventory_to_companies.py --apply
"""

import argparse
import sys
import os

# Asegurar path de importación
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.db_service import db_firestore, firebase_initialized


COLLECTIONS_TO_CHECK = [
    ("inventory_stock", "sandbox_inventory_stock"),
    ("inventory_transactions", "sandbox_inventory_transactions"),
    ("inventory_lots", "sandbox_inventory_lots"),
    ("inventory_cost_ledger", "sandbox_inventory_cost_ledger"),
]


def resolve_company_for_user(owner_uid):
    """Obtiene la compañía asociada a un owner_uid."""
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        # Buscar en companies donde ownerUID == owner_uid
        docs = db_firestore.collection("companies").where("ownerUID", "==", owner_uid).get()
        if docs:
            return docs[0].id
        
        # Buscar si el usuario tiene documento directo en companies con su mismo ID
        doc_direct = db_firestore.collection("companies").document(owner_uid).get()
        if doc_direct.exists:
            return owner_uid
    except Exception as e:
        print(f"  [!] Error buscando compañía para owner_uid {owner_uid}: {e}")
    return None


def run_diagnostics_and_migration(apply_changes=False):
    print("=" * 70)
    print(f"DIAGNÓSTICO Y MIGRACIÓN DE INVENTARIO MULTIEMPRESA ({'MODO APLICACIÓN' if apply_changes else 'MODO DRY-RUN'})")
    print("=" * 70)

    if not firebase_initialized or db_firestore is None:
        print("[!] Firebase no está inicializado. Abortando.")
        return False

    users_ref = db_firestore.collection("users")
    users = users_ref.get()

    total_legacy_docs = 0
    total_migrated_docs = 0
    total_orphan_docs = 0
    plan = []

    for user_doc in users:
        owner_uid = user_doc.id
        company_id = resolve_company_for_user(owner_uid)

        for prod_coll, sand_coll in COLLECTIONS_TO_CHECK:
            for is_sandbox, coll_name in [(False, prod_coll), (True, sand_coll)]:
                subcoll_ref = user_doc.reference.collection(coll_name)
                docs = subcoll_ref.get()

                if not docs:
                    continue

                count = len(docs)
                total_legacy_docs += count

                if not company_id:
                    print(f"[!] ADVERTENCIA: {count} documentos en users/{owner_uid}/{coll_name} pero NO se encontró company_id.")
                    total_orphan_docs += count
                    continue

                dest_coll_name = coll_name
                dest_ref = db_firestore.collection("companies").document(company_id).collection(dest_coll_name)

                print(f"[*] Encontrados {count} documentos en users/{owner_uid}/{coll_name} -> Destino: companies/{company_id}/{dest_coll_name}")

                for doc in docs:
                    doc_data = doc.to_dict()
                    plan.append({
                        "source_path": f"users/{owner_uid}/{coll_name}/{doc.id}",
                        "dest_path": f"companies/{company_id}/{dest_coll_name}/{doc.id}",
                        "doc_id": doc.id,
                        "data": doc_data,
                        "dest_ref": dest_ref.document(doc.id)
                    })

    print("-" * 70)
    print(f"Resumen del diagnóstico:")
    print(f"  • Total documentos legacy encontrados: {total_legacy_docs}")
    print(f"  • Total documentos listos para migrar: {len(plan)}")
    print(f"  • Total documentos huérfanos (sin compañía): {total_orphan_docs}")
    print("-" * 70)

    if apply_changes:
        if not plan:
            print("[✓] No hay documentos pendientes por migrar.")
            return True

        print("[*] Aplicando migración a Firestore...")
        for item in plan:
            # Idempotente: solo crea o actualiza en destino
            item["dest_ref"].set(item["data"], merge=True)
            total_migrated_docs += 1

        print(f"[✓] Migración completada exitosamente. Total documentos copiados a companies/: {total_migrated_docs}")
        print("[i] Los documentos originales en users/ se mantienen como respaldo de seguridad.")
    else:
        print("[i] Modo DRY-RUN finalizado. Ningún dato fue modificado.")
        print("    Para aplicar los cambios, ejecute: python scripts/migrate_inventory_to_companies.py --apply")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migración de inventario a colecciones canónicas de compañías.")
    parser.add_argument("--apply", action="store_true", help="Aplica la migración en Firestore.")
    parser.add_argument("--dry-run", action="store_true", help="Solo diagnostica sin modificar.")
    args = parser.parse_args()

    run_diagnostics_and_migration(apply_changes=args.apply)
