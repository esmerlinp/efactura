"""Crea membresias de propietario para companias que aun no las tienen.

Uso:
    python scripts/migrate_company_memberships.py --dry-run
    python scripts/migrate_company_memberships.py --company COMPANY_ID

La operacion es idempotente y no modifica membresias existentes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.db_service import DatabaseService, db_firestore, firebase_initialized  # noqa: E402


def migrate(company_id=None, dry_run=True):
    if not firebase_initialized:
        raise RuntimeError("Firebase no esta inicializado.")

    companies_ref = db_firestore.collection("companies")
    companies = []
    if company_id:
        doc = companies_ref.document(company_id).get()
        if doc.exists:
            companies.append(doc)
    else:
        companies = companies_ref.get()

    result = {"scanned": 0, "created": 0, "skipped": 0, "invalid": 0}
    for company_doc in companies:
        result["scanned"] += 1
        company = company_doc.to_dict() or {}
        owner_uid = company.get("owner_uid") or company.get("ownerUID")
        current_company_id = company.get("id") or company_doc.id
        if not owner_uid or not current_company_id:
            result["invalid"] += 1
            continue

        membership = DatabaseService.get_membership(owner_uid, current_company_id)
        if membership and membership.get("status") == "active":
            result["skipped"] += 1
            continue

        if not dry_run:
            created = DatabaseService.create_membership(
                owner_uid,
                current_company_id,
                role="owner",
                permissions={},
                invited_by="migration",
            )
            if not created:
                raise RuntimeError(
                    f"No se pudo crear membresia para {owner_uid}/{current_company_id}."
                )
        result["created"] += 1

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", dest="company_id")
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()
    result = migrate(company_id=args.company_id, dry_run=args.dry_run)
    mode = "dry-run" if args.dry_run else "aplicado"
    print(f"Migracion {mode}: {result}")


if __name__ == "__main__":
    main()
