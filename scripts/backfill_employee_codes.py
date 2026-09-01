"""Backfill de códigos de empleado (incremental, por empresa/entorno).

Asigna el campo `code` (1, 2, 3...) a los empleados existentes que solo
tienen GUID. Orden determinístico: fecha de ingreso asc → nombre → id.
Idempotente: los empleados que ya tienen código no se tocan.

Uso:
    python scripts/backfill_employee_codes.py --company <company_id> [--dry-run]
    python scripts/backfill_employee_codes.py --all [--dry-run]
"""

import argparse
import sys

from app.services.db_service import db_firestore, firebase_initialized
from app.services import hr_data_service as hr


def backfill_company(company_id: str, dry_run: bool = False) -> dict:
    summary = {"sandbox": {"assigned": 0, "skipped": 0}, "prod": {"assigned": 0, "skipped": 0}}
    for sandbox, key in ((True, "sandbox"), (False, "prod")):
        try:
            employees = hr.get_employees(company_id, sandbox=sandbox)
        except Exception as e:
            print(f"  ⚠️ {company_id}/{key}: error leyendo empleados: {e}")
            continue
        missing = [e for e in employees if not e.get("code")]
        missing.sort(key=lambda e: (
            e.get("hireDate", "") or "9999-12-31",
            (e.get("fullName", "") or "").lower(),
            e.get("id", ""),
        ))
        existing_codes = [int(e["code"]) for e in employees if e.get("code")]
        next_preview = max(existing_codes, default=0)
        for emp in missing:
            if dry_run:
                # Sin escrituras: solo se simula (next = max existente + 1 incremental local).
                next_preview += 1
                print(f"  [dry-run] {company_id}/{key}: {emp.get('fullName', emp.get('id', '?'))} → {next_preview}")
            else:
                next_code = hr.get_next_employee_code(company_id, sandbox=sandbox)
                if not next_code:
                    print(f"  ❌ {company_id}/{key}: no se pudo obtener código para {emp.get('fullName', emp.get('id', '?'))}")
                    continue
                emp["code"] = next_code
                hr.save_employee(company_id, emp.get("id", ""), emp, sandbox=sandbox)
                print(f"  ✅ {company_id}/{key}: {emp.get('fullName', emp.get('id', '?'))} → código {next_code}")
            summary[key]["assigned"] += 1
        summary[key]["skipped"] = len(employees) - len(missing)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Backfill de códigos de empleado")
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

    total = {"sandbox": {"assigned": 0, "skipped": 0}, "prod": {"assigned": 0, "skipped": 0}}
    for company_id in company_ids:
        print(f"🔍 Empresa {company_id}...")
        s = backfill_company(company_id, dry_run=args.dry_run)
        for key in ("sandbox", "prod"):
            total[key]["assigned"] += s[key]["assigned"]
            total[key]["skipped"] += s[key]["skipped"]

    print("\n📊 Resumen:")
    for key in ("sandbox", "prod"):
        print(f"  {key}: asignados={total[key]['assigned']}, ya con código={total[key]['skipped']}")
    if args.dry_run:
        print("  (dry-run: no se guardó nada)")


if __name__ == "__main__":
    main()
