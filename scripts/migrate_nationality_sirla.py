"""Migración de nacionalidad: código textual legacy → ID oficial SIRLA.

El campo `nationality` ahora representa directamente el ID oficial SIRLA
(1 = Dominicana, 2 = Norteamericana, ...). Los empleados que aún tengan un
`nationalityCode` textual (ej. "VEN", "USA") o un valor antiguo en
`nationality` se migran al ID correspondiente.

Los valores no reconocidos se dejan tal cual y se reportan para revisión.

Uso:
    python scripts/migrate_nationality_sirla.py --company <company_id> [--dry-run]
    python scripts/migrate_nationality_sirla.py --all [--dry-run]
"""

import argparse
import sys

from app.services.db_service import db_firestore, firebase_initialized
from app.services import hr_data_service as hr
from app.data.nationality_catalog import (
    is_valid_nationality_code,
    LEGACY_NATIONALITY_CODE_MAP,
)


def resolve_id(emp: dict) -> tuple:
    """Devuelve (nuevo_id, cambió, nota)."""
    nat = emp.get("nationality")
    code = (emp.get("nationalityCode") or "").strip()

    # Ya es un ID oficial válido
    if is_valid_nationality_code(nat):
        return int(str(nat).strip()), False, ""

    # Resolver desde nationalityCode textual legacy
    if code:
        mapped = LEGACY_NATIONALITY_CODE_MAP.get(code.upper())
        if mapped:
            return int(mapped), True, f"{code} → {mapped}"

    # nationality numérico crudo no mapeable o vacío
    return nat or 1, False, f"no reconocido (nationality={nat!r}, nationalityCode={code!r})"


def migrate_company(company_id: str, dry_run: bool = False) -> dict:
    summary = {"sandbox": {"migrated": 0, "ok": 0, "pending": 0}, "prod": {"migrated": 0, "ok": 0, "pending": 0}}
    for sandbox, key in ((True, "sandbox"), (False, "prod")):
        try:
            employees = hr.get_employees(company_id, sandbox=sandbox)
        except Exception as e:
            print(f"  ⚠️ {company_id}/{key}: error leyendo empleados: {e}")
            continue
        for emp in employees:
            new_id, changed, note = resolve_id(emp)
            if changed:
                emp["nationality"] = new_id
                emp.pop("nationalityCode", None)
                if not dry_run:
                    hr.save_employee(company_id, emp.get("id", ""), emp, sandbox=sandbox)
                print(f"  ✅ {company_id}/{key}: {emp.get('fullName', emp.get('id', '?'))} → ID {new_id} ({note})")
                summary[key]["migrated"] += 1
            elif note.startswith("no reconocido"):
                print(f"  ⚠️ {company_id}/{key}: {emp.get('fullName', emp.get('id', '?'))} — {note}")
                summary[key]["pending"] += 1
            else:
                summary[key]["ok"] += 1
    return summary


def main():
    parser = argparse.ArgumentParser(description="Migración de nacionalidad a ID oficial SIRLA")
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

    total = {"sandbox": {"migrated": 0, "ok": 0, "pending": 0}, "prod": {"migrated": 0, "ok": 0, "pending": 0}}
    for company_id in company_ids:
        print(f"🔍 Empresa {company_id}...")
        s = migrate_company(company_id, dry_run=args.dry_run)
        for k in ("sandbox", "prod"):
            for kk in ("migrated", "ok", "pending"):
                total[k][kk] += s[k][kk]

    print("\n📊 Resumen:")
    for k in ("sandbox", "prod"):
        print(f"  {k}: migrados={total[k]['migrated']}, ok={total[k]['ok']}, pendientes={total[k]['pending']}")
    if args.dry_run:
        print("  (dry-run: no se guardó nada)")


if __name__ == "__main__":
    main()
