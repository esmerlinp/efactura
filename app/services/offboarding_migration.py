"""OffboardingMigration — Script para migrar empleados inactivos existentes.

Crea registros de offboarding_requests retroactivos para todos los
empleados con status=inactivo que no tengan una solicitud asociada.

Uso:
    from app.services.offboarding_migration import migrate_inactive_employees
    migrate_inactive_employees(owner_uid, sandbox=True, user_email="admin@example.com")
"""

from datetime import datetime, timezone
from uuid import uuid4


def migrate_inactive_employees(owner_uid: str, sandbox: bool = True,
                               user_email: str = "system@migration",
                               dry_run: bool = False) -> dict:
    from app.services import hr_data_service as hr
    from app.services.offboarding_service import OffboardingService
    from app.services.offboarding_data_service import get_all as _get_all_offboard

    stats = {"total_inactive": 0, "already_migrated": 0, "migrated": 0, "errors": 0, "skipped_no_date": 0}

    all_employees = hr.get_employees(owner_uid, sandbox=sandbox)
    inactive = [e for e in all_employees if e.get("status") == "inactivo"]
    stats["total_inactive"] = len(inactive)

    existing = _get_all_offboard("offboarding_requests", owner_uid, sandbox, limit=1000)
    existing_employee_ids = set(r.get("employeeId", "") for r in existing)

    svc = OffboardingService(owner_uid, sandbox)

    for emp in inactive:
        try:
            emp_id = emp.get("id", "")
            if not emp_id:
                continue
            if emp_id in existing_employee_ids:
                stats["already_migrated"] += 1
                continue

            term_date = emp.get("terminationDate", "") or emp.get("effectiveDate", "")
            if not term_date:
                stats["skipped_no_date"] += 1
                continue

            term_type = emp.get("terminationType", "otro") or "otro"
            term_reason = emp.get("terminationReason", "") or "Migración automática"

            if dry_run:
                stats["migrated"] += 1
                continue

            data = {
                "employeeId": emp_id,
                "employeeName": emp.get("fullName", ""),
                "cedula": emp.get("cedula", ""),
                "departmentId": emp.get("departmentId", ""),
                "positionId": emp.get("positionId", ""),
                "supervisorId": emp.get("supervisorId", ""),
                "effectiveDate": term_date,
                "lastWorkDate": term_date,
                "terminationType": term_type,
                "terminationReason": term_reason,
                "detailedReason": "Migración automática de empleado inactivo preexistente",
                "initiatedBy": user_email,
                "initiatedByRole": "system",
                "status": "completed",
                "closedAt": datetime.now(timezone.utc).isoformat(),
                "createdBy": user_email,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedBy": user_email,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "ownerUid": owner_uid,
                "sandbox": sandbox,
                "statusHistory": [{
                    "fromStatus": "",
                    "toStatus": "completed",
                    "changedBy": user_email,
                    "changedAt": datetime.now(timezone.utc).isoformat(),
                    "comment": "Migración automática de empleado inactivo",
                }],
            }
            req = svc.create_request(data, user_email)
            existing_employee_ids.add(emp_id)
            stats["migrated"] += 1

        except Exception as e:
            print(f"⚠️ Error migrando empleado {emp.get('id', '')}: {e}")
            stats["errors"] += 1

    return stats
