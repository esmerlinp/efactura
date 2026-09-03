"""Diagnóstico: verificar licencias y horario de un empleado para el descuento."""
import sys
import types
from unittest.mock import MagicMock

# Parche para entornos macOS donde charset_normalizer falla por firma de código
cn = types.ModuleType("charset_normalizer")
cn.__version__ = "3.4.0"
cn.api = types.ModuleType("charset_normalizer.api")
cn.cd = types.ModuleType("charset_normalizer.cd")
cn.from_bytes = lambda *a, **k: b""
cn.from_path = lambda *a, **k: b""
cn.from_fp = lambda *a, **k: b""
sys.modules.setdefault("charset_normalizer", cn)
sys.modules.setdefault("charset_normalizer.cd", cn.cd)
sys.modules.setdefault("charset_normalizer.api", cn.api)
for _m in ("cryptography", "cryptography.fernet", "cryptography.exceptions",
           "cryptography.hazmat", "cryptography.hazmat.backends",
           "cryptography.hazmat.bindings", "cryptography.hazmat.bindings._rust",
           "cryptography.hazmat.primitives", "cryptography.hazmat.primitives.asymmetric",
           "cryptography.hazmat.primitives.asymmetric.utils"):
    sys.modules.setdefault(_m, MagicMock())

from app.services.db_service import db_firestore, firebase_initialized
from app.services import hr_data_service as hr

def main():
    if not firebase_initialized or db_firestore is None:
        print("Firebase no inicializado")
        sys.exit(1)

    print("Empresas:")
    companies = [d.id for d in db_firestore.collection("companies").get()]
    for c in companies:
        print(" -", c)

    target_name = sys.argv[1] if len(sys.argv) > 1 else "ANA"

    for company_id in companies:
        for sandbox, key in ((True, "sandbox"), (False, "prod")):
            try:
                employees = hr.get_employees(company_id, sandbox=sandbox)
            except Exception as e:
                continue
            for emp in employees:
                fn = (emp.get("fullName") or "").upper()
                if target_name.upper() not in fn:
                    continue
                print(f"\n=== {key} / {company_id} ===")
                print("Empleado:", emp.get("fullName"), "| id:", emp.get("id"))
                print("  salaryType:", emp.get("salaryType"), "| baseSalary:", emp.get("baseSalary"))
                print("  position:", emp.get("position"), "| positionId:", emp.get("positionId"))
                print("  workScheduleCustom:", emp.get("workScheduleCustom"), "| workSchedule:", emp.get("workSchedule"))
                # Posición
                pos = None
                for p in hr.get_catalog(company_id, "positions", sandbox=sandbox):
                    if p.get("id") == emp.get("positionId") or (p.get("name") or "").strip().lower() == (emp.get("position", "") or "").strip().lower():
                        pos = p
                        break
                print("  Posición schedule:", (pos or {}).get("workSchedule") if pos else "N/A")
                # Licencias
                leaves = [r for r in hr.get_leave_requests(company_id, sandbox=sandbox)
                          if r.get("employeeId") == emp.get("id")]
                for l in leaves:
                    print("  Licencia:", l.get("startDate"), "→", l.get("endDate"),
                          "| status:", l.get("status"), "| paidByPayroll:", l.get("paidByPayroll"),
                          "| leaveType:", l.get("leaveType"), "| days:", l.get("days"))
                # Resolver work days
                from app.services.payroll_service import PayrollService
                wd = PayrollService.resolve_employee_work_days(company_id, emp, sandbox=sandbox)
                print("  work_days resuelto:", sorted(wd))
                # Calcular deducción para agosto (mensual y quincenal)
                for label, ps, pe in (("ago1-31", "2026-08-01", "2026-08-31"),
                                      ("ago16-31", "2026-08-16", "2026-08-31")):
                    r = PayrollService.unpaid_leave_deduction(
                        float(emp.get("baseSalary", 0)), leaves, ps, pe,
                        company_id=company_id, sandbox=sandbox,
                        working_days=23.83, work_days=wd)
                    print(f"  deducción {label}: days={r['days']} amount={r['amount']}")


if __name__ == "__main__":
    main()
