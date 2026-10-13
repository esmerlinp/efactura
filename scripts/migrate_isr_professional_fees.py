"""Migración puntual: retención ISR de Honorarios Profesionales 0.10 -> 0.15.

Actualiza la config `companies/{id}/config/tax_rules` de las empresas que
guardaron `withholding_isr.professional_fees == 0.10`. Las empresas sin
documento guardado (usan el default) no se tocan: idempotente.

Debe ejecutarse DESPUÉS de desplegar el nuevo default 0.15 (así `get_tax_rules`
ya devuelve 0.15 para quien no tenga valor guardado).

Uso:
    python scripts/migrate_isr_professional_fees.py --company <company_id> [--dry-run]
    python scripts/migrate_isr_professional_fees.py --all [--dry-run]
"""

import argparse
import sys

from app.services.db_service import DatabaseService, db_firestore, firebase_initialized

FROM_RATE = 0.10
TO_RATE = 0.15
EPS = 1e-9


def migrate_company(company_id: str, dry_run: bool = False) -> str:
    """Devuelve 'ok' | 'would' | 'skip' | 'error'."""
    doc_ref = (
        db_firestore.collection("companies")
        .document(company_id)
        .collection("config")
        .document("tax_rules")
    )
    try:
        doc = doc_ref.get()
    except Exception as e:
        print(f"  ⚠️ {company_id}: error leyendo tax_rules: {e}")
        return "error"

    if not doc.exists:
        return "skip"

    stored = doc.to_dict() or {}
    current = ((stored.get("withholding_isr") or {}).get("professional_fees"))
    if current is None or abs(float(current) - FROM_RATE) > EPS:
        return "skip"

    if dry_run:
        print(f"  [dry-run] {company_id}: professional_fees {FROM_RATE:.2f} → {TO_RATE:.2f}")
        return "would"

    comp = db_firestore.collection("companies").document(company_id).get()
    owner_uid = (comp.to_dict() or {}).get("owner_uid", "") if comp.exists else ""

    rules = DatabaseService.get_tax_rules(owner_uid, company_id=company_id)
    rules.setdefault("withholding_isr", {})["professional_fees"] = TO_RATE
    ok, err = DatabaseService.save_tax_rules(owner_uid, rules, company_id=company_id)
    if not ok:
        print(f"  ❌ {company_id}: no se pudo guardar: {err}")
        return "error"
    print(f"  ✅ {company_id}: professional_fees {FROM_RATE:.2f} → {TO_RATE:.2f}")
    return "ok"


def main():
    parser = argparse.ArgumentParser(description="Migra la retención ISR de Honorarios Profesionales a 15%")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--company", help="ID de la empresa (companies/{id})")
    group.add_argument("--all", action="store_true", help="Todas las empresas")
    parser.add_argument("--dry-run", action="store_true", help="Solo previsualizar sin guardar")
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

    summary = {"ok": 0, "would": 0, "skip": 0, "error": 0}
    for company_id in company_ids:
        print(f"🔍 Empresa {company_id}...")
        summary[migrate_company(company_id, dry_run=args.dry_run)] += 1

    print("\n📊 Resumen:")
    print(f"  migradas={summary['ok']}, previsualizadas={summary['would']}, omitidas={summary['skip']}, errores={summary['error']}")
    if args.dry_run:
        print("  (dry-run: no se guardó nada)")


if __name__ == "__main__":
    main()
