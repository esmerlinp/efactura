"""MassActionService — Orquestador de Acciones de Personal Masivas."""

import uuid
import dataclasses
from datetime import datetime, timezone
from typing import Optional

from app.services import hr_data_service as hr
from app.services.state_machine import StateMachineValidator, MASS_ACTION_STATES
from app.services.payroll_audit_service import log_action
from app.events import get_event_bus
from app.events.events import (
    BulkSalaryChanged,
    BulkPositionChanged,
    BulkSupervisorChanged,
    BulkPromotionApplied,
    BulkAbsenceApplied,
)


ACTION_TYPE_MAP = {
    "salary_change": "Cambio Salarial",
    "position_change": "Cambio de Puesto",
    "supervisor_change": "Cambio de Supervisor",
    "promotion": "Promoción",
    "mass_absence": "Ausencia Masiva",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_for_action(action_type: str, mass_action_id: str, payload: dict,
                      affected_ids: list, payroll_period_key: str = ""):
    common = dict(mass_action_id=mass_action_id, action_data=payload,
                  affected_ids=affected_ids)
    if action_type == "salary_change":
        return BulkSalaryChanged(**common, payroll_period_key=payroll_period_key)
    if action_type == "position_change":
        return BulkPositionChanged(**common)
    if action_type == "supervisor_change":
        return BulkSupervisorChanged(**common)
    if action_type == "promotion":
        return BulkPromotionApplied(**common, payroll_period_key=payroll_period_key)
    if action_type == "mass_absence":
        return BulkAbsenceApplied(**common)
    return None


def _detect_period(owner_uid: str, effective_date: str, sandbox: bool) -> Optional[str]:
    """Detecta el periodo de nómina abierto que contiene la fecha efectiva."""
    if not effective_date:
        return None
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    frequency = config.get("payroll", {}).get("frequency", "mensual")
    year = effective_date[:4]
    try:
        periods = _generate_periods_simple(frequency, int(year))
    except Exception:
        return None
    for p in periods:
        if p["start"] <= effective_date <= p["end"]:
            return p["key"]
    return None


def _generate_periods_simple(frequency: str, year: int) -> list:
    """Genera lista de periodos sin depender del blueprint web."""
    import calendar
    MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    periods = []
    if frequency in ("quincenal", "ambos", "quincenal_y_mensual"):
        for m in range(1, 13):
            last_day = calendar.monthrange(year, m)[1]
            mid = 15
            label_m = MONTHS_ES[m - 1]
            periods.append({
                "key": f"{year}-{m:02d}-1",
                "label": f"Q1: 1 {label_m} - 15 {label_m}",
                "start": f"{year}-{m:02d}-01",
                "end": f"{year}-{m:02d}-{mid}",
            })
            periods.append({
                "key": f"{year}-{m:02d}-2",
                "label": f"Q2: 16 {label_m} - {last_day} {label_m}",
                "start": f"{year}-{m:02d}-16",
                "end": f"{year}-{m:02d}-{last_day}",
            })
    else:
        for m in range(1, 13):
            last_day = calendar.monthrange(year, m)[1]
            label_m = MONTHS_ES[m - 1]
            periods.append({
                "key": f"{year}-{m:02d}",
                "label": f"{label_m} {year}",
                "start": f"{year}-{m:02d}-01",
                "end": f"{year}-{m:02d}-{last_day}",
            })
    return periods


def _build_employee_map(owner_uid: str, sandbox: bool) -> dict:
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    return {e["id"]: e for e in employees}


def create_mass_action(owner_uid: str, action_type: str, employee_ids: list,
                       payload: dict, created_by: str, sandbox: bool = True) -> dict:
    action_id = str(uuid.uuid4())
    now = _now()

    payroll_period_key = payload.get("payrollPeriodKey")
    if not payroll_period_key and payload.get("effectiveDate"):
        payroll_period_key = _detect_period(owner_uid, payload.get("effectiveDate", ""), sandbox)
        if payroll_period_key:
            payload["payrollPeriodKey"] = payroll_period_key

    data = {
        "id": action_id,
        "actionType": action_type,
        "status": "draft",
        "createdBy": created_by,
        "createdAt": now,
        "processedAt": "",
        "ownerUid": owner_uid,
        "sandbox": sandbox,
        "selectionCriteria": {"employeeIds": employee_ids},
        "totalEmployees": len(employee_ids),
        "successCount": 0,
        "errorCount": 0,
        "payload": payload,
        "results": [],
        "errorLog": [],
        "statusHistory": [
            {"from": "", "to": "draft", "by": created_by, "at": now}
        ],
    }

    hr.save_mass_action(owner_uid, action_id, data, sandbox=sandbox)
    return data


def validate_action(owner_uid: str, action_type: str, employee_ids: list,
                    payload: dict, sandbox: bool = True) -> list:
    errors = []
    if not employee_ids:
        errors.append({"field": "employeeIds", "message": "Debe seleccionar al menos un empleado."})
        return errors

    emp_map = _build_employee_map(owner_uid, sandbox)

    for eid in employee_ids:
        emp = emp_map.get(eid)
        if not emp:
            errors.append({"employeeId": eid, "employeeName": "Desconocido",
                           "field": "employeeId", "message": "Empleado no encontrado."})
            continue

        if action_type in ("salary_change", "position_change", "supervisor_change", "promotion"):
            if emp.get("status") != "activo":
                errors.append({"employeeId": eid, "employeeName": emp.get("fullName", ""),
                               "field": "status", "message": "El empleado no está activo."})

    if action_type == "salary_change":
        amt = payload.get("amount", 0)
        pct = payload.get("percentage")
        if pct is None and amt <= 0:
            errors.append({"field": "amount", "message": "Debe especificar un monto o porcentaje válido."})
        if pct is not None and (pct < -50 or pct > 200):
            errors.append({"field": "percentage", "message": "El porcentaje debe estar entre -50% y 200%."})
        if not payload.get("effectiveDate"):
            errors.append({"field": "effectiveDate", "message": "La fecha efectiva es obligatoria."})

    elif action_type == "position_change":
        if not payload.get("newPosition"):
            errors.append({"field": "newPosition", "message": "El nuevo puesto es obligatorio."})

    elif action_type == "supervisor_change":
        new_sup_id = payload.get("newSupervisorId")
        if not new_sup_id:
            errors.append({"field": "newSupervisorId", "message": "Debe seleccionar un supervisor."})
        else:
            sup = emp_map.get(new_sup_id)
            if not sup or sup.get("status") != "activo":
                errors.append({"field": "newSupervisorId", "message": "El supervisor no existe o no está activo."})
            for eid in employee_ids:
                if eid == new_sup_id:
                    errors.append({"employeeId": eid, "employeeName": sup.get("fullName", ""),
                                   "field": "newSupervisorId", "message": "Un empleado no puede reportarse a sí mismo."})
                    break

    elif action_type == "promotion":
        if not payload.get("newPosition"):
            errors.append({"field": "newPosition", "message": "El nuevo puesto es obligatorio."})
        amt = payload.get("amount", 0)
        pct = payload.get("percentage")
        if pct is None and amt <= 0:
            errors.append({"field": "amount", "message": "Debe especificar un nuevo salario o porcentaje."})

    elif action_type == "mass_absence":
        if not payload.get("startDate"):
            errors.append({"field": "startDate", "message": "La fecha de inicio es obligatoria."})
        if not payload.get("endDate"):
            errors.append({"field": "endDate", "message": "La fecha de fin es obligatoria."})
        elif payload.get("startDate") and payload.get("endDate"):
            if payload["endDate"] < payload["startDate"]:
                errors.append({"field": "endDate", "message": "La fecha de fin no puede ser anterior a la de inicio."})
        if payload.get("absenceType") == "vacation":
            for eid in employee_ids:
                emp = emp_map.get(eid)
                if emp:
                    remaining = _calc_remaining_vacation_days(emp)
                    days_needed = payload.get("days", 0)
                    if remaining < days_needed:
                        errors.append({
                            "employeeId": eid,
                            "employeeName": emp.get("fullName", ""),
                            "field": "vacationDays",
                            "message": f"Saldo insuficiente: tiene {remaining} días, necesita {days_needed}."
                        })

    return errors


def _calc_remaining_vacation_days(employee: dict) -> int:
    from app.services.payroll_service import PayrollService
    total = PayrollService.calculate_vacation_days(employee.get("hireDate", ""))
    used = 0
    return total - used


def execute_action(owner_uid: str, action_id: str,
                   created_by: str, sandbox: bool = True) -> dict:
    action = hr.get_mass_action(owner_uid, action_id, sandbox=sandbox)
    if not action:
        raise ValueError("Acción masiva no encontrada.")

    sm = StateMachineValidator(MASS_ACTION_STATES)
    sm.validate_transition(action["status"], "processing", "acción masiva")

    now = _now()
    action["status"] = "processing"
    action["statusHistory"].append({"from": "draft", "to": "processing", "by": created_by, "at": now})
    hr.save_mass_action(owner_uid, action_id, action, sandbox=sandbox)

    action_type = action["actionType"]
    payload = action["payload"]
    employee_ids = action["selectionCriteria"]["employeeIds"]
    emp_map = _build_employee_map(owner_uid, sandbox)

    results = []
    error_log = []
    success_count = 0
    error_count = 0

    for eid in employee_ids:
        emp = emp_map.get(eid)
        if not emp:
            error_log.append({"employeeId": eid, "employeeName": "Desconocido",
                              "field": "employeeId", "message": "Empleado no encontrado."})
            error_count += 1
            continue

        try:
            before = _snapshot_employee(emp, action_type)
            _apply_action_to_employee(owner_uid, emp, action_type, payload, created_by, sandbox)
            after = _snapshot_employee(emp_map.get(eid) or emp, action_type)

            results.append({
                "employeeId": eid,
                "employeeName": emp.get("fullName", ""),
                "status": "success",
                "errorMessage": "",
                "changes": {"before": before, "after": after},
                "processedAt": _now(),
            })
            success_count += 1
        except Exception as e:
            error_log.append({
                "employeeId": eid,
                "employeeName": emp.get("fullName", ""),
                "field": "general",
                "message": str(e),
            })
            results.append({
                "employeeId": eid,
                "employeeName": emp.get("fullName", ""),
                "status": "error",
                "errorMessage": str(e),
                "changes": {},
                "processedAt": _now(),
            })
            error_count += 1

    new_status = "completed" if error_count == 0 else "partial"
    now = _now()
    action["status"] = new_status
    action["processedAt"] = now
    action["successCount"] = success_count
    action["errorCount"] = error_count
    action["results"] = results
    action["errorLog"] = error_log
    action["statusHistory"].append({"from": "processing", "to": new_status, "by": created_by, "at": now})
    hr.save_mass_action(owner_uid, action_id, action, sandbox=sandbox)

    try:
        event = _event_for_action(
            action_type, action_id, payload, employee_ids,
            payroll_period_key=payload.get("payrollPeriodKey", ""),
        )
        if event:
            event = dataclasses.replace(event, owner_uid=owner_uid, sandbox=sandbox)
            get_event_bus().publish(event)
    except Exception:
        pass

    log_action(owner_uid, "mass_action", action_type, action_id, created_by,
               changes={"status": new_status, "total": len(employee_ids),
                        "success": success_count, "errors": error_count},
               sandbox=sandbox)

    return action


def _snapshot_employee(emp: dict, action_type: str) -> dict:
    fields = {"salary", "baseSalary", "position", "area", "department",
              "costCenter", "reportsTo", "status"}
    return {k: emp.get(k) for k in fields if k in emp}


def _apply_action_to_employee(owner_uid: str, emp: dict, action_type: str,
                               payload: dict, created_by: str, sandbox: bool):
    eid = emp["id"]
    now = _now()

    if action_type in ("salary_change", "promotion"):
        change_type = payload.get("changeType", "fixed_amount")
        if change_type == "percentage":
            pct = payload.get("percentage", 0)
            current = emp.get("baseSalary", 0) or 0
            new_salary = round(current * (1 + pct / 100), 2)
        else:
            new_salary = payload.get("amount", 0)

        prev_salary = emp.get("baseSalary", 0) or 0
        if new_salary > 0 and new_salary != prev_salary:
            hr.save_employee(owner_uid, eid, {**emp, "baseSalary": new_salary, "salary": new_salary}, sandbox=sandbox)
            history_id = str(uuid.uuid4())
            hr.save_salary_history_entry(owner_uid, {
                "id": history_id,
                "employeeId": eid,
                "amount": new_salary,
                "previousAmount": prev_salary,
                "effectiveDate": payload.get("effectiveDate", now[:10]),
                "endDate": "",
                "reason": payload.get("reason", f"Acción masiva: {ACTION_TYPE_MAP.get(action_type, action_type)}"),
                "approvedBy": created_by,
                "createdAt": now[:10],
            }, sandbox=sandbox)

    if action_type in ("position_change", "promotion"):
        new_position = payload.get("newPosition")
        new_area = payload.get("newArea", emp.get("area", ""))
        new_department = payload.get("newDepartment", emp.get("department", ""))
        new_cost_center = payload.get("newCostCenter", emp.get("costCenter", ""))
        changes = {}
        if new_position:
            changes["position"] = new_position
        if new_area:
            changes["area"] = new_area
        if new_department:
            changes["department"] = new_department
        if new_cost_center:
            changes["costCenter"] = new_cost_center
        if changes:
            hr.save_employee(owner_uid, eid, {**emp, **changes}, sandbox=sandbox)
            hist_id = str(uuid.uuid4())
            hr.save_employment_history(owner_uid, {
                "id": hist_id,
                "employeeId": eid,
                "previousPosition": emp.get("position", ""),
                "newPosition": new_position or emp.get("position", ""),
                "previousDepartment": emp.get("department", ""),
                "newDepartment": new_department or emp.get("department", ""),
                "effectiveDate": payload.get("effectiveDate", now[:10]),
                "reason": payload.get("reason", f"Acción masiva: {ACTION_TYPE_MAP.get(action_type, action_type)}"),
                "changedBy": created_by,
                "changedAt": now[:10],
            }, sandbox=sandbox)

    if action_type == "supervisor_change":
        new_sup_id = payload.get("newSupervisorId")
        if new_sup_id and new_sup_id != emp.get("reportsTo"):
            hr.save_employee(owner_uid, eid, {**emp, "reportsTo": new_sup_id}, sandbox=sandbox)
            hist_id = str(uuid.uuid4())
            hr.save_employment_history(owner_uid, {
                "id": hist_id,
                "employeeId": eid,
                "previousPosition": emp.get("position", ""),
                "newPosition": emp.get("position", ""),
                "previousDepartment": emp.get("department", ""),
                "newDepartment": emp.get("department", ""),
                "effectiveDate": payload.get("effectiveDate", now[:10]),
                "reason": payload.get("reason", "Reasignación de supervisor"),
                "changedBy": created_by,
                "changedAt": now[:10],
            }, sandbox=sandbox)

    if action_type == "mass_absence":
        absence_type = payload.get("absenceType", "vacation")
        if absence_type == "vacation":
            vac_id = str(uuid.uuid4())
            hr.save_vacation_request(owner_uid, vac_id, {
                "id": vac_id,
                "employeeId": eid,
                "employeeName": emp.get("fullName", ""),
                "startDate": payload.get("startDate", ""),
                "endDate": payload.get("endDate", ""),
                "days": payload.get("days", 0),
                "status": "aprobada",
                "approvedBy": created_by,
                "approvedDate": now[:10],
                "notes": payload.get("reason", "Vacaciones masivas"),
                "createdDate": now[:10],
            }, sandbox=sandbox)
        else:
            leave_id = str(uuid.uuid4())
            hr.save_leave_request(owner_uid, leave_id, {
                "id": leave_id,
                "employeeId": eid,
                "employeeName": emp.get("fullName", ""),
                "leaveType": payload.get("leaveType", "otro"),
                "startDate": payload.get("startDate", ""),
                "endDate": payload.get("endDate", ""),
                "days": payload.get("days", 0),
                "status": "aprobada",
                "approvedBy": created_by,
                "notes": payload.get("reason", "Licencia masiva"),
            }, sandbox=sandbox)
