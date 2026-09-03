"""Reset de acumulados Year-to-Date (YTD) de nómina.

Limpia la colección `hr_ytd_accumulations` de una empresa (sandbox y/o prod).
Es seguro: los acumulados YTD son datos derivados que se reconstruyen en el
siguiente cálculo de nómina. Útil para corregir datos corruptos por el bug
histórico de acumulación no idempotente (recalcular duplicaba ISR y terminaba
en ISR = 0 para todos).

Uso:
    python scripts/reset_payroll_ytd.py --company <company_id> [--year 2026] [--dry-run]
    python scripts/reset_payroll_ytd.py --all [--year 2026] [--dry-run]
"""

import argparse
import sys
import os

# Add the project root to sys.path so 'app' can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.db_service import db_firestore, firebase_initialized


def _ytd_collection(company_id: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"companies/{company_id}/{prefix}hr_ytd_accumulations"


def reset_company(company_id: str, year: str = "", dry_run: bool = False) -> dict:
    summary = {"sandbox": 0, "prod": 0}
    for sandbox, key in ((True, "sandbox"), (False, "prod")):
        try:
            coll = db_firestore.collection(_ytd_collection(company_id, sandbox=sandbox))
            docs = coll.get()
            count = 0
            for d in docs:
                data = d.to_dict()
                if year and str(data.get("year", "")) != str(year):
                    continue
                count += 1
                if not dry_run:
                    d.reference.delete()
            summary[key] = count
        except Exception as e:
            print(f"  ⚠️ {company_id}/{key}: error: {e}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Reset de acumulados YTD de nómina")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--company", help="ID de la empresa (companies/{id})")
    group.add_argument("--all", action="store_true", help="Todas las empresas")
    parser.add_argument("--year", default="", help="Año a resetear (opcional, ej. 2026)")
    parser.add_argument("--dry-run", action="store_true", help="Solo previsualizar sin borrar")
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

    total = 0
    for company_id in company_ids:
        print(f"🔍 Empresa {company_id}...")
        s = reset_company(company_id, year=args.year, dry_run=args.dry_run)
        for key in ("sandbox", "prod"):
            total += s[key]
            print(f"  {key}: {s[key]} acumulado(s) {'que se borrarían' if args.dry_run else 'borrados'}")

    print(f"\n📊 Total acumulados afectados: {total}")
    if args.dry_run:
        print("  (dry-run: no se borró nada)")


if __name__ == "__main__":
    main()
