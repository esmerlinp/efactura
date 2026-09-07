"""rehire_migration_dry_run — Solo lectura. Reporta el estado legacy para reincorporación.

No modifica Firestore. Genera conteos:
- empleados, contratos, contratos activos múltiples
- empleados con terminationDate, empleados sin contrato
- contratos sin empleado
- vacaciones/licencias sin contractId (ambiguos)
- liquidaciones sin contractId
- movimientos recurrentes sin contractId
- líneas de nómina sin contractId

Uso:
    python scripts/rehire_migration_dry_run.py --company <company_id> [--sandbox|--prod]
    python scripts/rehire_migration_dry_run.py --company <id> --json
"""
import argparse
import json
import sys
from collections import Counter


def _load_hr(company_id, sandbox):
    from app.services import hr_data_service as hr
    employees = hr.get_employees(company_id, sandbox=sandbox)
    contracts = hr.get_contracts(company_id, sandbox=sandbox)
    return hr, employees, contracts


def dry_run(company_id: str, sandbox: bool = True) -> dict:
    hr, employees, contracts = _load_hr(company_id, sandbox)
    emp_ids = {e.get("id") for e in employees if e.get("id")}

    by_emp = Counter(c.get("employeeId", "") for c in contracts)
    active_by_emp = Counter(
        c.get("employeeId", "") for c in contracts if (c.get("status") or "") == "activo"
    )
    multi_active = {eid: n for eid, n in active_by_emp.items() if n > 1}
    with_termination = [e for e in employees if e.get("terminationDate")]
    without_contract = [e for e in employees if e.get("id") and by_emp.get(e.get("id"), 0) == 0]
    orphan_contracts = [c for c in contracts if (c.get("employeeId") or "") not in emp_ids]

    # Vacaciones / licencias
    try:
        vacs = hr.get_vacation_requests(company_id, sandbox=sandbox)
    except Exception:
        vacs = []
    try:
        leaves = hr.get_leave_requests(company_id, sandbox=sandbox)
    except Exception:
        leaves = []
    vac_ambiguous = [v for v in vacs if not (v.get("contractId") or "").strip()]
    leave_ambiguous = [l for l in leaves if not (l.get("contractId") or "").strip()]

    # Liquidaciones
    try:
        liquidaciones = hr._get_all(company_id, "liquidaciones", sandbox)
    except Exception:
        liquidaciones = []
    liq_without = [l for l in liquidaciones if not (l.get("contractId") or "").strip()]

    # Recurrentes
    try:
        from app.services.recurring_service import get_recurring_movements
        movs = get_recurring_movements(company_id, sandbox=sandbox)
    except Exception:
        movs = []
    movs_without = [m for m in movs if not (m.get("contractId") or "").strip()]

    # Nómina: muestreo de líneas sin contractId (últimos 20 períodos para no escanear todo)
    payroll_without = 0
    payroll_checked = 0
    try:
        periods = sorted(hr.get_payroll_periods(company_id, sandbox=sandbox),
                         key=lambda p: p.get("periodKey", ""), reverse=True)[:20]
        for p in periods:
            lines = hr.get_payroll_lines(company_id, p.get("id", ""), sandbox=sandbox)
            for ln in lines:
                payroll_checked += 1
                if not (ln.get("contractId") or "").strip():
                    payroll_without += 1
    except Exception as e:
        print(f"⚠️ nómina: {e}", file=sys.stderr)

    # Salary history
    try:
        salaries = hr.get_all_salary_history(company_id, sandbox=sandbox)
    except Exception:
        salaries = []
    sal_without = [s for s in salaries if not (s.get("contractId") or "").strip()]

    return {
        "company_id": company_id,
        "sandbox": sandbox,
        "empleados": len(employees),
        "contratos": len(contracts),
        "contratos_activos_multiples": multi_active,
        "empleados_con_terminationDate": len(with_termination),
        "empleados_sin_contrato": len(without_contract),
        "empleados_sin_contrato_ids": [e.get("id") for e in without_contract[:50]],
        "contratos_huerfanos": len(orphan_contracts),
        "vacaciones_totales": len(vacs),
        "vacaciones_sin_contractId": len(vac_ambiguous),
        "licencias_totales": len(leaves),
        "licencias_sin_contractId": len(leave_ambiguous),
        "liquidaciones_totales": len(liquidaciones),
        "liquidaciones_sin_contractId": len(liq_without),
        "recurrentes_totales": len(movs),
        "recurrentes_sin_contractId": len(movs_without),
        "nomina_lineas_revisadas": payroll_checked,
        "nomina_lineas_sin_contractId": payroll_without,
        "salarios_totales": len(salaries),
        "salarios_sin_contractId": len(sal_without),
        "nota": "DRY-RUN: no se modificó ningún dato. contractId='' = legacy con fallback a employeeId.",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True)
    ap.add_argument("--sandbox", action="store_true", default=True)
    ap.add_argument("--prod", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sandbox = not args.prod
    report = dry_run(args.company, sandbox)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("═" * 60)
        print(f"REHIRE DRY-RUN — {report['company_id']} ({'sandbox' if sandbox else 'prod'})")
        print("═" * 60)
        for k, v in report.items():
            if k in ("company_id", "sandbox", "nota"):
                continue
            print(f"{k}: {v}")
        print("─" * 60)
        print(report["nota"])


if __name__ == "__main__":
    main()
