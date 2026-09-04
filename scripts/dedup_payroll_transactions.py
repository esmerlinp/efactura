"""Limpieza one-time de transacciones/aplicaciones de nómina duplicadas.

Cuando una nómina se recalcula, el flujo anterior guardaba transacciones
nuevas sin borrar las previas (cada una con id=uuid4()), dejando duplicados
del mismo período/concepto/origen. Esos duplicados inflan el salario promedio.

Este script agrupa por clave lógica y conserva únicamente el documento más
reciente, eliminando el resto. Idempotente.

Clave de transacción: (periodId, employeeId, conceptCode, source, sourceId)
Clave de aplicación: (recurringMovementId, employeeId, periodId, periodKey)

Uso:
    python scripts/dedup_payroll_transactions.py --company <company_id> [--dry-run]
    python scripts/dedup_payroll_transactions.py --all [--dry-run]
    python scripts/dedup_payroll_transactions.py --company <id> --applications
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_service import db_firestore, firebase_initialized


def _collection_path(company_id: str, sandbox: bool, name: str) -> str:
    prefix = "sandbox_hr_" if sandbox else "hr_"
    return f"companies/{company_id}/{prefix}{name}"


def _tx_key(tx: dict) -> tuple:
    return (
        tx.get("periodId", ""),
        tx.get("employeeId", ""),
        tx.get("conceptCode", ""),
        tx.get("source", ""),
        tx.get("sourceId", ""),
    )


def _app_key(app: dict) -> tuple:
    return (
        app.get("recurringMovementId", ""),
        app.get("employeeId", ""),
        app.get("periodId", ""),
        app.get("periodKey", ""),
    )


def _timestamp(doc: dict) -> str:
    return doc.get("updatedAt") or doc.get("createdAt") or ""


def _dedup_docs(docs: list, key_fn) -> tuple[list, list]:
    """Retorna (keep, delete) donde keep son docs a conservar y delete docs a eliminar."""
    best = {}
    for doc in docs:
        key = key_fn(doc)
        cur = best.get(key)
        if cur is None or _timestamp(doc) >= _timestamp(cur):
            best[key] = doc
    keep_ids = {d["id"] for d in best.values()}
    to_delete = [d for d in docs if d["id"] not in keep_ids]
    return list(best.values()), to_delete


def _load_all(coll_path: str) -> list:
    try:
        docs = db_firestore.collection(coll_path).get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"  ⚠️ Error leyendo {coll_path}: {e}")
        return []


def _delete_docs(coll_path: str, docs: list, dry_run: bool) -> int:
    if not docs:
        return 0
    if dry_run:
        for d in docs:
            print(f"  [dry-run] eliminaría {coll_path}/{d['id']}")
        return len(docs)
    deleted = 0
    for i in range(0, len(docs), 400):
        batch = db_firestore.batch()
        for d in docs[i:i + 400]:
            batch.delete(db_firestore.collection(coll_path).document(d["id"]))
        batch.commit()
        deleted += len(docs[i:i + 400])
    return deleted


def dedup_company(company_id: str, dry_run: bool, clean_applications: bool) -> dict:
    summary = {}
    for sandbox, key in ((True, "sandbox"), (False, "prod")):
        tx_path = _collection_path(company_id, sandbox, "payroll_transactions")
        txs = _load_all(tx_path)
        _, dup_txs = _dedup_docs(txs, _tx_key)
        tx_deleted = _delete_docs(tx_path, dup_txs, dry_run)

        app_deleted = 0
        if clean_applications:
            app_path = _collection_path(company_id, sandbox, "recurring_applications")
            apps = _load_all(app_path)
            _, dup_apps = _dedup_docs(apps, _app_key)
            app_deleted = _delete_docs(app_path, dup_apps, dry_run)

        summary[key] = {"transactions": len(txs), "tx_deleted": tx_deleted,
                        "app_deleted": app_deleted}
        print(f"  {company_id}/{key}: {len(txs)} transacciones, {tx_deleted} duplicadas"
              f"{f', {app_deleted} aplicaciones duplicadas' if clean_applications else ''}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Limpia transacciones de nómina duplicadas")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--company", help="ID de la empresa (companies/{id})")
    group.add_argument("--all", action="store_true", help="Todas las empresas")
    parser.add_argument("--dry-run", action="store_true", help="Solo previsualizar sin borrar")
    parser.add_argument("--applications", action="store_true",
                        help="También limpiar aplicaciones recurrentes duplicadas")
    args = parser.parse_args()

    if not firebase_initialized or db_firestore is None:
        print("❌ Firebase no inicializado")
        sys.exit(1)

    company_ids = []
    if args.all:
        try:
            company_ids = [d.id for d in db_firestore.collection("companies").get()]
        except Exception as e:
            print(f"❌ Error listando empresas: {e}")
            sys.exit(1)
    else:
        company_ids = [args.company]

    for company_id in company_ids:
        print(f"🔍 Empresa {company_id}...")
        dedup_company(company_id, dry_run=args.dry_run,
                      clean_applications=args.applications)

    if args.dry_run:
        print("\n(dry-run: no se eliminó nada)")


if __name__ == "__main__":
    main()
