"""RRHH module — auto-extracted."""

import csv
import io
import re
import uuid
from datetime import date, datetime, timezone
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_static_data import DEFAULT_PAYROLL_CONFIG
from app.services.payroll_service import PayrollService
from app.utils.hr_utils import is_active_equivalent
from app.services.payroll_audit_service import log_action, get_audit_log
from app.data.occupations_catalog import OCCUPATIONS
from app.data.nationality_catalog import SIRLA_NATIONALITIES
from app.data.disability_catalog import SIRLA_DISABILITIES, normalize_disability


# ═══════════════════════════════════════════════════════════════════════════
# HISTORIAL DE ACCIONES DEL EMPLEADO (timeline unificado)
# ═══════════════════════════════════════════════════════════════════════════

ACTION_LABELS = {
    "create": "Empleado creado",
    "update": "Empleado actualizado",
    "rehire": "Recontratación",
    "work_certificate_generated": "Carta de trabajo",
    "overtime_created": "Hora extra",
    "overtime_approved": "Hora extra aprobada",
    "recurring_movement_created": "Movimiento recurrente",
    "payroll_paid": "Pago de nómina",
    "evaluation_created": "Evaluación",
    "training_created": "Capacitación",
    "vacation_request_created": "Solicitud de vacaciones",
    "vacation_approved": "Vacaciones aprobadas",
    "vacation_rejected": "Vacaciones rechazadas",
    "leave_request_created": "Solicitud de licencia",
    "leave_approved": "Licencia aprobada",
    "leave_rejected": "Licencia rechazada",
    "tool_assigned": "Herramienta asignada",
    "tool_returned": "Herramienta devuelta",
    "tool_maintenance": "Mantenimiento de herramienta",
    "employee_marked_inactive": "Baja de empleado",
    "employee_reactivated": "Reactivación",
    "liquidacion_calculada": "Liquidación calculada",
}


def _action_category(action: str, changes: dict) -> str:
    """Mapea una acción del audit log a una categoría visual (badge)."""
    if action in ("work_certificate_generated",):
        return "carta"
    if action in ("overtime_created", "overtime_approved"):
        return "hora_extra"
    if action == "recurring_movement_created":
        return "recurrente_ingreso" if (changes or {}).get("movementType") == "earning" else "recurrente_deduccion"
    if action in ("payroll_paid",):
        return "pago"
    if action in ("evaluation_created",):
        return "evaluacion"
    if action in ("training_created",):
        return "capacitacion"
    if action.startswith("vacation"):
        return "vacaciones"
    if action.startswith("leave"):
        return "licencia"
    if action in ("tool_assigned", "tool_returned", "tool_maintenance"):
        return "herramienta"
    if action in ("employee_marked_inactive",):
        return "baja"
    if action in ("rehire", "employee_reactivated"):
        return "alta"
    return "empleado"


def _fmt_currency(value) -> str:
    try:
        return "RD$ {:,.2f}".format(float(value or 0))
    except (TypeError, ValueError):
        return "—"


def _fmt_currency_0(value) -> str:
    try:
        return "RD$ {:,.0f}".format(float(value or 0))
    except (TypeError, ValueError):
        return "—"


def _format_ts(ts: str) -> tuple:
    """Convierte un timestamp ISO en (fecha, hora) en zona horaria local."""
    if not ts:
        return "", ""
    s = str(ts)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")
    except Exception:
        return s[:10], s[11:16] if len(s) > 16 else ""


def _detail_text(item: dict) -> str:
    """Construye una única línea de detalle legible para una acción del timeline."""
    kind = item.get("kind", "")
    action = item.get("action", "")
    changes = item.get("changes", {}) or {}

    if kind == "status":
        txt = item.get("comment", "") or "—"
        reason = item.get("reason", "")
        return f"{txt} · {reason}" if reason else txt

    if kind == "mass":
        c = changes
        if action == "desvinculacion" and c and c.get("after"):
            after = c["after"]
            parts = [f"Estado: {after.get('status') or '—'}"]
            tt = (after.get("terminationType") or "").replace("_", " ").title()
            if tt:
                parts.append(tt)
            if after.get("terminationDate"):
                parts.append(after["terminationDate"])
            return " · ".join(parts)
        if c and c.get("before") and c.get("after"):
            before, after = c["before"], c["after"]
            parts = []
            if (before.get("baseSalary") != after.get("baseSalary")
                    or before.get("salary") != after.get("salary")):
                parts.append(f"Salario {_fmt_currency_0(before.get('baseSalary') or before.get('salary') or 0)}"
                             f" → {_fmt_currency_0(after.get('baseSalary') or after.get('salary') or 0)}")
            if before.get("position") != after.get("position"):
                parts.append(f"Puesto {before.get('position') or '—'} → {after.get('position') or '—'}")
            if before.get("department") != after.get("department"):
                parts.append(f"Depto {before.get('department') or '—'} → {after.get('department') or '—'}")
            if before.get("area") != after.get("area"):
                parts.append(f"Área {before.get('area') or '—'} → {after.get('area') or '—'}")
            if before.get("reportsTo") != after.get("reportsTo"):
                parts.append("Supervisor cambiado")
            return " · ".join(parts) if parts else "Sin cambios detectados"
        return "Detalle no disponible"

    # audit
    txt = item.get("comment", "") or ""
    extras = []
    if action == "payroll_paid" and changes.get("netSalary"):
        extras.append(f"Neto {_fmt_currency(changes.get('netSalary'))}")
    elif action in ("overtime_created", "overtime_approved") and changes.get("hours"):
        extras.append(f"{changes.get('hours')} h")
    elif action == "recurring_movement_created" and changes.get("amount"):
        extras.append(_fmt_currency(changes.get("amount")))
    if extras:
        return f"{txt} · {' · '.join(extras)}" if txt else " · ".join(extras)
    return txt or "—"


def build_employee_timeline(audit_log: list, status_events: list,
                            employee_actions: list) -> list:
    """Fusiona audit log + transiciones de estado + acciones masivas en una
    única línea de tiempo cronológica (más reciente primero)."""
    items = []

    for e in audit_log or []:
        action = e.get("action", "")
        if action.startswith("employee_status_"):
            # Las transiciones de estado se muestran desde status_events (más ricas).
            continue
        changes = e.get("changes", {}) or {}
        items.append({
            "ts": e.get("timestamp", ""),
            "kind": "audit",
            "action": action,
            "category": _action_category(action, changes),
            "label": ACTION_LABELS.get(action, action.replace("_", " ").title()),
            "comment": e.get("comment", ""),
            "changes": changes,
            "actor": e.get("userId", ""),
        })

    for ev in status_events or []:
        trigger = ev.get("trigger", "")
        if trigger.startswith("vacation"):
            category = "vacaciones"
            label = "Vacaciones" if "cancel" not in trigger and "revok" not in trigger else (
                "Anulación" if "cancel" in trigger else "Revocación")
        elif trigger.startswith("leave"):
            category = "licencia"
            label = "Licencia"
        else:
            category = "estado"
            label = "Estado"
        items.append({
            "ts": ev.get("timestamp", ""),
            "kind": "status",
            "action": trigger,
            "category": category,
            "label": label,
            "comment": f"{ev.get('fromStatus', '') or '—'} → {ev.get('toStatus', '') or '—'}",
            "reason": ev.get("reason", ""),
            "changes": {},
            "actor": ev.get("actor", ""),
        })

    for a in employee_actions or []:
        items.append({
            "ts": a.get("createdAt", ""),
            "kind": "mass",
            "action": a.get("actionType", ""),
            "category": "accion_masiva",
            "label": a.get("actionTypeLabel", a.get("actionType", "")),
            "comment": "",
            "changes": (a.get("result") or {}).get("changes", {}),
            "actor": a.get("createdBy", ""),
            "mass_action_id": a.get("id", ""),
        })

    items.sort(key=lambda i: i.get("ts", ""), reverse=True)
    for it in items:
        it["_date"], it["_time"] = _format_ts(it.get("ts", ""))
        it["detail"] = _detail_text(it)
    return items


def _timeline_detail_url(item: dict, employee_id: str):
    """Retorna la URL de detalle de una acción del timeline, o None si no aplica.

    Requiere contexto de request (url_for). Se invoca dentro del view.
    """
    kind = item.get("kind", "")
    action = item.get("action", "")
    changes = item.get("changes", {}) or {}

    if kind == "mass":
        aid = item.get("mass_action_id", "")
        return url_for("web_rrhh.mass_action_detail", action_id=aid) if aid else None

    if kind == "status":
        if action.startswith("vacation"):
            return url_for("web_rrhh.vacation_list")
        if action.startswith("leave"):
            return url_for("web_rrhh.leave_list")
        return None

    # kind == "audit"
    if action in ("create", "update", "rehire", "employee_marked_inactive",
                  "employee_reactivated"):
        return url_for("web_rrhh.employee_view", employee_id=employee_id)
    if action == "work_certificate_generated":
        return url_for("web_rrhh.employee_certificate", employee_id=employee_id)
    if action in ("overtime_created", "overtime_approved"):
        oid = changes.get("overtimeId", "")
        return url_for("web_rrhh.overtime_view", record_id=oid) if oid else None
    if action == "recurring_movement_created":
        mid = changes.get("movementId", "")
        return url_for("web_rrhh.recurring_edit", movement_id=mid) if mid else None
    if action == "payroll_paid":
        pid = changes.get("periodId", "")
        return url_for("web_rrhh.payroll_view", period_id=pid) if pid else None
    if action == "evaluation_created":
        return url_for("web_rrhh.evaluation_list")
    if action == "training_created":
        return url_for("web_rrhh.training_list")
    if action.startswith("vacation"):
        return url_for("web_rrhh.vacation_list")
    if action.startswith("leave"):
        return url_for("web_rrhh.leave_list")
    if action in ("tool_assigned", "tool_returned", "tool_maintenance"):
        hid = changes.get("herramientaId", "")
        return url_for("web_herramientas.detail_herramienta", herramienta_id=hid) if hid else None
    if action == "liquidacion_calculada":
        return url_for("web_rrhh.employee_liquidaciones_list", employee_id=employee_id)
    return None


MASS_ACTION_LABELS = {
    "salary_change": "Cambio Salarial", "position_change": "Cambio de Puesto",
    "supervisor_change": "Cambio de Supervisor", "promotion": "Promoción",
    "mass_absence": "Ausencia Masiva", "desvinculacion": "Desvinculación",
}


def _employee_mass_actions(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    mass_actions = hr.get_mass_actions(company_id, sandbox=sandbox)
    employee_actions = []
    for ma in mass_actions:
        for r in ma.get("results", []):
            if r.get("employeeId") == employee_id:
                employee_actions.append({
                    "id": ma.get("id", ""),
                    "actionType": ma.get("actionType", ""),
                    "actionTypeLabel": MASS_ACTION_LABELS.get(ma.get("actionType", ""), ma.get("actionType", "")),
                    "createdAt": ma.get("createdAt", ""),
                    "createdBy": ma.get("createdBy", ""),
                    "status": ma.get("status", ""),
                    "result": r,
                })
                break
    employee_actions.sort(key=lambda a: a.get("createdAt", ""), reverse=True)
    return employee_actions


def _build_employee_timeline(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    """Construye el timeline de acciones del empleado (con enlaces de detalle)."""
    audit_log = get_audit_log(company_id, entity="employee", entity_id=employee_id,
                              limit=300, sandbox=sandbox)
    status_events = hr.get_employee_status_events(company_id, employee_id, sandbox=sandbox, limit=100)
    employee_actions = _employee_mass_actions(company_id, employee_id, sandbox=sandbox)
    timeline = build_employee_timeline(audit_log, status_events, employee_actions)
    for item in timeline:
        item["detail_url"] = _timeline_detail_url(item, employee_id)
    return timeline


def _filter_timeline(timeline: list, category: str = "", actor: str = "",
                     date_from: str = "", date_to: str = "") -> list:
    """Filtra el timeline por categoría, actor y rango de fechas."""
    result = []
    for it in timeline:
        if category and it.get("category", "") != category:
            continue
        if actor and actor.lower() not in (it.get("actor", "") or "").lower():
            continue
        d = it.get("_date", "")
        if date_from and d and d < date_from:
            continue
        if date_to and d and d > date_to:
            continue
        result.append(it)
    return result


# Días de la semana para el editor de horario: (código, índice 0=Lun..6=Dom)
SCHEDULE_DAYS = [("L", 0), ("M", 1), ("X", 2), ("J", 3), ("V", 4), ("S", 5), ("D", 6)]


def _schedule_map(work_schedule):
    """Convierte un horario semanal en {day_int: entry}."""
    result = {}
    for entry in (work_schedule or []):
        try:
            result[int(entry.get("day", -1))] = entry
        except (ValueError, TypeError):
            continue
    return result


def _resolve_position(company_id, position_id, position_name, sandbox):
    """Retorna (position_id, position_name) resolviendo el nombre desde el catálogo si hace falta."""
    positions = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    for p in positions:
        if position_id and p.get("id") == position_id:
            return p.get("id", ""), p.get("name", "")
    if position_name:
        for p in positions:
            if (p.get("name", "") or "").strip().lower() == (position_name or "").strip().lower():
                return p.get("id", ""), p.get("name", "")
    return position_id or "", position_name or ""


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYEES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees")
def employee_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.db_service import DatabaseService

    employees = hr.get_employees(company_id, sandbox=sandbox)
    from app.services.payroll_service import PayrollService
    from app.services.employee_status_service import EmployeeStatusService
    vac_by_emp = {}
    for r in hr.get_vacation_requests(company_id, sandbox=sandbox):
        vac_by_emp.setdefault(r.get("employeeId", ""), []).append(r)
    for emp in employees:
        taken = EmployeeStatusService.taken_vacation_days(vac_by_emp.get(emp.get("id", ""), []))
        emp["vacationDays"] = PayrollService.calculate_vacation_days(
            emp.get("hireDate", ""), taken_days=taken)

    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id)

    # ── Columnas configurables del grid (visibilidad por usuario) ──
    from app.web.rrhh.employee_columns import (
        EMPLOYEE_GRID_COLUMNS, enrich_employees, get_employee_list_columns,
        format_cell, status_class, FIXED_COLUMNS, DEFAULT_VISIBLE_COLUMNS,
    )
    user_uid = session.get("user", {}).get("uid", "")
    employees = enrich_employees(employees, branches)
    visible_map = get_employee_list_columns(user_uid)
    visible_columns = [c for c in EMPLOYEE_GRID_COLUMNS if visible_map.get(c["key"])]

    # ── Filtros ──
    search = request.args.get("search", "").strip().lower()
    filter_status = request.args.get("status", "").strip()
    filter_department = request.args.get("department", "").strip()
    filter_branch = request.args.get("branch", "").strip()
    if search:
        employees = [e for e in employees if
                     search in (e.get("fullName", "") + " " +
                                e.get("cedula", "") + " " +
                                e.get("idNumber", "") + " " +
                                e.get("position", "") + " " +
                                str(e.get("code", ""))).lower()]
    if filter_status:
        employees = [e for e in employees if e.get("status", "") == filter_status]
    if filter_department:
        employees = [e for e in employees if e.get("department", "") == filter_department or e.get("area", "") == filter_department]
    if filter_branch:
        employees = [e for e in employees if e.get("branchId", "") == filter_branch]

    total = len(employees)
    active_count = sum(1 for e in employees if e.get("status") == "activo")
    inactive_count = sum(1 for e in employees if e.get("status") == "inactivo")
    vacation_count = sum(1 for e in employees if e.get("status") == "vacaciones")
    leave_count = sum(1 for e in employees if e.get("status") == "licencia")

    # ── Departamentos disponibles para filtro ──
    departments_set = sorted(set(e.get("department", "") or e.get("area", "") for e in employees if e.get("department") or e.get("area")))

    # ── Paginación ──
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(10, min(100000, int(request.args.get("per_page", 25))))
    except (ValueError, TypeError):
        page, per_page = 1, 25
    if total == 0:
        per_page = 25
        page = 1
    elif per_page >= total:
        per_page = total
        page = 1
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    paged = employees[start:start + per_page]

    return render_template("rrhh/employee_list.html", active_page="rrhh_employees",
                           employees=paged, page=page, total_pages=total_pages,
                           total=total, per_page=per_page,
                           search=request.args.get("search", ""),
                           filter_status=filter_status, filter_department=filter_department,
                           filter_branch=filter_branch, branches=branches,
                           departments_set=departments_set, active_count=active_count,
                           inactive_count=inactive_count,
                           vacation_count=vacation_count, leave_count=leave_count,
                           grid_columns=EMPLOYEE_GRID_COLUMNS,
                           visible_columns=visible_columns,
                           visible_keys={k for k, v in visible_map.items() if v},
                           fixed_columns=FIXED_COLUMNS,
                           default_visible=DEFAULT_VISIBLE_COLUMNS,
                           fmt=format_cell, status_class=status_class)


@web_rrhh_bp.route("/rrhh/employees/columns", methods=["GET", "POST"])
def employee_list_columns():
    """Lee o guarda la visibilidad de columnas del grid para el usuario actual."""
    if _login_required():
        return jsonify({"error": "No autorizado"}), 401
    from app.web.rrhh.employee_columns import (
        EMPLOYEE_GRID_COLUMNS, get_employee_list_columns, save_employee_list_columns,
        DEFAULT_VISIBLE_COLUMNS, FIXED_COLUMNS,
    )
    user_uid = session.get("user", {}).get("uid", "")

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        columns = data.get("columns")
        if not isinstance(columns, dict):
            return jsonify({"error": "Debe enviar {columns: {key: bool}}"}), 400
        ok = save_employee_list_columns(user_uid, columns)
        return jsonify({"ok": ok})

    visible = get_employee_list_columns(user_uid)
    return jsonify({
        "columns": [c["key"] for c in EMPLOYEE_GRID_COLUMNS],
        "labels": {c["key"]: c["label"] for c in EMPLOYEE_GRID_COLUMNS},
        "visible": visible,
        "default": DEFAULT_VISIBLE_COLUMNS,
        "fixed": list(FIXED_COLUMNS),
    })


@web_rrhh_bp.route("/rrhh/employees/new", methods=["GET", "POST"])
def employee_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_static_data import (
        ID_TYPES, MUNICIPIOS_RD, CONTRACT_TYPES, AREAS, WORKDAYS,
        PAYMENT_METHODS, ACCOUNT_TYPES, PAYROLL_FREQUENCIES,
    )

    if request.method == "POST":
        emp_id = str(uuid.uuid4())
        first_name = request.form.get("firstName", "").strip()
        first_last_name = request.form.get("firstLastName", "").strip()
        middle_name = request.form.get("middleName", "").strip()
        second_last_name = request.form.get("secondLastName", "").strip()

        position_id = request.form.get("positionId", "").strip()
        position_name = request.form.get("position", "").strip()
        position_id, position_name = _resolve_position(company_id, position_id, position_name, sandbox)
        from app.utils.hr_utils import parse_work_schedule_form
        work_schedule = parse_work_schedule_form(request.form)
        work_schedule_custom = request.form.get("workScheduleInherit") != "on"

        data = {
            "id": emp_id,
            "idType": request.form.get("idType", "cedula").strip(),
            "idNumber": re.sub(r'\D', '', request.form.get("idNumber", "")),
            "cedula": re.sub(r'\D', '', request.form.get("idNumber", "")),
            "firstName": first_name,
            "middleName": middle_name,
            "lastName": first_last_name,
            "firstLastName": first_last_name,
            "secondLastName": second_last_name,
            "fullName": " ".join(p for p in [first_name, middle_name, first_last_name, second_last_name] if p),
            "position": position_name,
            "positionId": position_id,
            "area": request.form.get("area", "").strip(),
            "costCenter": request.form.get("costCenter", request.form.get("area", "")).strip(),
            "department": request.form.get("department_catalog", request.form.get("area", "")).strip(),
            "branchId": request.form.get("branchId", "").strip(),
            "hireDate": request.form.get("hireDate", "").strip(),
            "salary": float(request.form.get("salary", 0) or 0),
            "baseSalary": float(request.form.get("salary", 0) or 0),
            "salaryType": "fijo",
            "status": "activo",
            "email": request.form.get("email", "").strip(),
            "phone": re.sub(r'\D', '', request.form.get("phone", "")),
            "address": request.form.get("address", "").strip(),
            "municipality": request.form.get("municipality", "").strip(),
            "contractType": request.form.get("contractType", "").strip(),
            "payrollGroupIds": request.form.getlist("payrollGroupIds"),
            "workday": request.form.get("workday", "completa").strip(),
            "isVigilante": request.form.get("isVigilante") == "si",
            "tssKey": request.form.get("tssKey", "").strip(),
            "paymentMethod": request.form.get("paymentMethod", "").strip(),
            "accountNumber": request.form.get("accountNumber", "").strip(),
            "bank": request.form.get("bank", "").strip(),
            "accountType": request.form.get("accountType", "").strip(),
            "emergencyContact": "",
            "emergencyPhone": "",
            "afpProvider": request.form.get("afpProvider", "").strip(),
            "notes": request.form.get("notes", "").strip(),
            "gender": request.form.get("gender", "").strip(),
            "birthDate": request.form.get("birthDate", "").strip(),
            "probationEndDate": request.form.get("probationEndDate", "").strip(),
            "reportsTo": request.form.get("reportsTo", "").strip(),
            "maritalStatus": request.form.get("maritalStatus", "").strip(),
            "occupationCode": request.form.get("occupationCode", "").strip(),
            "weeklyHours": int(request.form.get("weeklyHours", 44) or 44),
            "workShift": int(request.form.get("workShift", 1) or 1),
            "workSchedule": work_schedule,
            "workScheduleCustom": work_schedule_custom,
            "educationLevel": int(request.form.get("educationLevel", 0) or 0),
            "sirlaEducationCode": request.form.get("sirlaEducationCode", "").strip(),
            "vacationGranted": int(request.form.get("vacationGranted", 1) or 1),
            "sdssNumber": request.form.get("sdssNumber", "").strip(),
            "vacationStartDate": request.form.get("vacationStartDate", "").strip(),
            "vacationEndDate": request.form.get("vacationEndDate", "").strip(),
            "disability": normalize_disability(request.form.getlist("disability")),
            "nationality": int(request.form.get("nationality", 1) or 1),
            "numberOfChildren": int(request.form.get("numberOfChildren", 0) or 0),
            "daysWorked": int(request.form.get("daysWorked", 0) or 0),
            "dailySalary": float(request.form.get("dailySalary", 0) or 0),
            "employeeType": request.form.get("employeeType", "empleado").strip(),
        }
        hr.save_employee(company_id, emp_id, data, sandbox=sandbox)

        # ── Crear entrada inicial en historial de salarios ──
        from app.services import hr_data_service as hr2
        salary = float(request.form.get("salary", 0) or 0)
        if salary > 0:
            history_id = str(uuid.uuid4())
            hr2.save_salary_history_entry(company_id, {
                "id": history_id,
                "employeeId": emp_id,
                "amount": salary,
                "previousAmount": 0.0,
                "effectiveDate": request.form.get("hireDate", date.today().isoformat()).strip(),
                "endDate": "",
                "reason": "Salario inicial",
                "approvedBy": session.get("user", {}).get("email", ""),
                "createdAt": date.today().isoformat(),
            }, sandbox=sandbox)

        from app.services.payroll_audit_service import log_action
        log_action(company_id, "create", "employee", emp_id,
                   session.get("user", {}).get("email", ""),
                   changes={"name": data["fullName"], "salary": salary}, sandbox=sandbox)

        flash("Empleado creado exitosamente.", "success")
        return redirect(url_for("web_rrhh.employee_list"))

    # Obtener reference data del usuario (con respaldo estático)
    ref_data = hr.get_reference_data(company_id, sandbox=sandbox)
    contract_types = ref_data.get("contractTypes", CONTRACT_TYPES)
    areas = ref_data.get("areas", AREAS)
    supervisors = [e for e in hr.get_employees(company_id, sandbox=sandbox) if is_active_equivalent(e.get("status", ""))]
    positions = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    for _p in positions:
        _p["_schedule_map"] = _schedule_map(_p.get("workSchedule"))
    departments = hr.get_catalog(company_id, "departments", sandbox=sandbox)
    payroll_groups = hr.get_payroll_groups(company_id, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))
    from app.services.db_service import DatabaseService
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id)
    bank_entities_list = DatabaseService.get_bank_entities(owner_uid, sandbox=sandbox, company_id=company_id)
    bank_names = [be["name"] for be in bank_entities_list if be.get("active")]

    from app.data.occupations_catalog import OCCUPATIONS
    from app.data.education_catalog import SIRLA_EDUCATION_LEVELS
    return render_template("rrhh/employee_form.html", active_page="rrhh_employees", employee=None,
                           id_types=ID_TYPES, municipios=MUNICIPIOS_RD,
                           contract_types=contract_types, areas=areas,
                           workdays=WORKDAYS, payment_methods=PAYMENT_METHODS,
                           bancos=bank_names, account_types=ACCOUNT_TYPES,
                           supervisors=supervisors,
                           positions=positions, departments=departments,
                           payroll_groups=payroll_groups, schedule_days=SCHEDULE_DAYS,
                           display_schedule={},
                           occupations=OCCUPATIONS, branches=branches,
                           sirla_education_levels=SIRLA_EDUCATION_LEVELS,
                           sirla_nationalities=SIRLA_NATIONALITIES,
                           sirla_disabilities=SIRLA_DISABILITIES)

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/edit", methods=["GET", "POST"])
def employee_edit(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_static_data import (
        ID_TYPES, MUNICIPIOS_RD, CONTRACT_TYPES, AREAS, WORKDAYS,
        PAYMENT_METHODS, ACCOUNT_TYPES, PAYROLL_FREQUENCIES,
    )

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    if request.method == "POST":
        first_name = request.form.get("firstName", "").strip()
        first_last_name = request.form.get("firstLastName", "").strip()
        middle_name = request.form.get("middleName", "").strip()
        second_last_name = request.form.get("secondLastName", "").strip()

        position_id = request.form.get("positionId", "").strip()
        position_name = request.form.get("position", "").strip()
        position_id, position_name = _resolve_position(company_id, position_id, position_name, sandbox)
        from app.utils.hr_utils import parse_work_schedule_form
        work_schedule = parse_work_schedule_form(request.form)
        work_schedule_custom = request.form.get("workScheduleInherit") != "on"

        employee.update({
            "idType": request.form.get("idType", "cedula").strip(),
            "idNumber": re.sub(r'\D', '', request.form.get("idNumber", "")),
            "cedula": re.sub(r'\D', '', request.form.get("idNumber", "")),
            "firstName": first_name,
            "middleName": middle_name,
            "lastName": first_last_name,
            "firstLastName": first_last_name,
            "secondLastName": second_last_name,
            "fullName": " ".join(p for p in [first_name, middle_name, first_last_name, second_last_name] if p),
            "position": position_name,
            "positionId": position_id,
            "area": request.form.get("area", "").strip(),
            "costCenter": request.form.get("costCenter", request.form.get("area", "")).strip(),
            "department": request.form.get("department_catalog", request.form.get("area", "")).strip(),
            "branchId": request.form.get("branchId", "").strip(),
            "hireDate": request.form.get("hireDate", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": re.sub(r'\D', '', request.form.get("phone", "")),
            "address": request.form.get("address", "").strip(),
            "municipality": request.form.get("municipality", "").strip(),
            "contractType": request.form.get("contractType", "").strip(),
            "payrollGroupIds": request.form.getlist("payrollGroupIds"),
            "workday": request.form.get("workday", "completa").strip(),
            "isVigilante": request.form.get("isVigilante") == "si",
            "tssKey": request.form.get("tssKey", "").strip(),
            "paymentMethod": request.form.get("paymentMethod", "").strip(),
            "accountNumber": request.form.get("accountNumber", "").strip(),
            "bank": request.form.get("bank", "").strip(),
            "accountType": request.form.get("accountType", "").strip(),
            "emergencyContact": request.form.get("emergencyContact", "").strip(),
            "emergencyPhone": re.sub(r'\D', '', request.form.get("emergencyPhone", "")),
            "afpProvider": request.form.get("afpProvider", "").strip(),
            "notes": request.form.get("notes", "").strip(),
            "gender": request.form.get("gender", "").strip(),
            "birthDate": request.form.get("birthDate", "").strip(),
            "probationEndDate": request.form.get("probationEndDate", "").strip(),
            "reportsTo": request.form.get("reportsTo", "").strip(),
            "maritalStatus": request.form.get("maritalStatus", "").strip(),
            "occupationCode": request.form.get("occupationCode", "").strip(),
            "weeklyHours": int(request.form.get("weeklyHours", 44) or 44),
            "workShift": int(request.form.get("workShift", 1) or 1),
            "workSchedule": work_schedule,
            "workScheduleCustom": work_schedule_custom,
            "educationLevel": int(request.form.get("educationLevel", 0) or 0),
            "sirlaEducationCode": request.form.get("sirlaEducationCode", "").strip(),
            "vacationGranted": int(request.form.get("vacationGranted", 1) or 1),
            "sdssNumber": request.form.get("sdssNumber", "").strip(),
            "vacationStartDate": request.form.get("vacationStartDate", "").strip(),
            "vacationEndDate": request.form.get("vacationEndDate", "").strip(),
            "disability": normalize_disability(request.form.getlist("disability")),
            "nationality": int(request.form.get("nationality", 1) or 1),
            "numberOfChildren": int(request.form.get("numberOfChildren", 0) or 0),
            "daysWorked": int(request.form.get("daysWorked", 0) or 0),
            "dailySalary": float(request.form.get("dailySalary", 0) or 0),
            "employeeType": request.form.get("employeeType", "empleado").strip(),
        })
        hr.save_employee(company_id, employee_id, employee, sandbox=sandbox)

        # ── Historial de cambios estructurales ──
        new_position = position_name
        new_department = request.form.get("department_catalog", "").strip()
        new_supervisor = request.form.get("reportsTo", "").strip()
        old_position = employee.get("position", "")
        old_department = employee.get("department", "") or employee.get("area", "")
        old_supervisor = employee.get("reportsTo", "")

        if new_position != old_position or new_department != old_department or new_supervisor != old_supervisor:
            changes = []
            if new_position != old_position: changes.append(f"Cargo: {old_position} → {new_position}")
            if new_department != old_department: changes.append(f"Depto: {old_department} → {new_department}")
            if new_supervisor != old_supervisor: changes.append(f"Supervisor: {old_supervisor} → {new_supervisor}")
            hr.save_employment_history(company_id, {
                "id": str(uuid.uuid4()), "employeeId": employee_id,
                "changedAt": datetime.now(timezone.utc).isoformat(),
                "changedBy": session.get("user", {}).get("email", ""),
                "changes": changes, "newPosition": new_position, "newDepartment": new_department,
            }, sandbox=sandbox)

        from app.services.payroll_audit_service import log_action
        log_action(company_id, "update", "employee", employee_id,
                   session.get("user", {}).get("email", ""),
                   changes={"position": new_position, "department": new_department, "supervisor": new_supervisor}, sandbox=sandbox)

        flash("Empleado actualizado exitosamente.", "success")
        return redirect(url_for("web_rrhh.employee_list"))

    ref_data = hr.get_reference_data(company_id, sandbox=sandbox)
    contract_types = ref_data.get("contractTypes", CONTRACT_TYPES)
    areas = ref_data.get("areas", AREAS)
    supervisors = [e for e in hr.get_employees(company_id, sandbox=sandbox)
                   if is_active_equivalent(e.get("status", "")) and e.get("id") != employee_id]
    positions = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    for _p in positions:
        _p["_schedule_map"] = _schedule_map(_p.get("workSchedule"))
    departments = hr.get_catalog(company_id, "departments", sandbox=sandbox)
    payroll_groups = hr.get_payroll_groups(company_id, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))
    from app.services.db_service import DatabaseService
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id)
    bank_entities_list = DatabaseService.get_bank_entities(owner_uid, sandbox=sandbox, company_id=company_id)
    bank_names = [be["name"] for be in bank_entities_list if be.get("active")]

    # Horario a mostrar: propio (si personalizado) o heredado del puesto
    display_schedule = {}
    if employee.get("workScheduleCustom"):
        display_schedule = _schedule_map(employee.get("workSchedule"))
    else:
        _pos = next((p for p in positions
                     if p.get("id") == employee.get("positionId")
                     or (p.get("name", "") or "").strip().lower() == (employee.get("position", "") or "").strip().lower()), None)
        if _pos:
            display_schedule = _schedule_map(_pos.get("workSchedule"))

    from app.data.occupations_catalog import OCCUPATIONS
    from app.data.education_catalog import SIRLA_EDUCATION_LEVELS
    return render_template("rrhh/employee_form.html", active_page="rrhh_employees", employee=employee,
                           id_types=ID_TYPES, municipios=MUNICIPIOS_RD,
                           contract_types=contract_types, areas=areas,
                           workdays=WORKDAYS, payment_methods=PAYMENT_METHODS,
                           bancos=bank_names, account_types=ACCOUNT_TYPES,
                           supervisors=supervisors,
                           positions=positions, departments=departments,
                           payroll_groups=payroll_groups, schedule_days=SCHEDULE_DAYS,
                           display_schedule=display_schedule,
                           occupations=OCCUPATIONS, branches=branches,
                           sirla_education_levels=SIRLA_EDUCATION_LEVELS,
                           sirla_nationalities=SIRLA_NATIONALITIES,
                           sirla_disabilities=SIRLA_DISABILITIES)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/view")
def employee_view(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    from app.services.db_service import DatabaseService

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    from app.services.employee_status_service import EmployeeStatusService
    EmployeeStatusService.sync_employee(
        company_id, employee_id, sandbox=sandbox,
        actor=session["user"].get("email", ""))
    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)

    emp_vac_requests = [
        r for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
        if r.get("employeeId") == employee_id
    ]
    taken_days = EmployeeStatusService.taken_vacation_days(emp_vac_requests)
    vacation_days = PayrollService.calculate_vacation_days(
        employee.get("hireDate", ""), taken_days=taken_days)
    active_requests = EmployeeStatusService.get_active_requests(
        company_id, employee_id, sandbox=sandbox)
    severance = PayrollService.calculate_severance(
        employee.get("baseSalary", 0), employee.get("hireDate", "")
    )

    # Salario promedio (auto-calculado, últimos 12 meses, conceptos que cotizan TSS)
    average_salary = float(employee.get("averageSalary", 0) or 0)
    try:
        from app.services.liquidacion_service import LiquidacionService
        txs = hr.get_payroll_transactions(company_id, employee_id=employee_id, sandbox=sandbox)
        prom = LiquidacionService.calcular_salario_promedio_mensual(txs)
        if prom.get("promedio_mensual", 0) > 0:
            average_salary = prom["promedio_mensual"]
    except Exception:
        pass
    evals = [e for e in hr.get_evaluations(company_id, sandbox=sandbox) if e.get("employeeId") == employee_id]
    trainings = [t for t in hr.get_trainings(company_id, sandbox=sandbox) if t.get("employeeId") == employee_id]
    docs = hr.get_employee_documents(company_id, employee_id, sandbox=sandbox)

    # Historial de pagos (últimos 24 períodos)
    periods = hr.get_payroll_periods(company_id, sandbox=sandbox)
    payment_history = []
    for p in sorted(periods, key=lambda x: x.get("periodKey", ""), reverse=True)[:24]:
        lines = hr.get_payroll_lines(company_id, p.get("id", ""), sandbox=sandbox)
        for l in lines:
            if l.get("employeeId") == employee_id:
                payment_history.append({"period": p, "line": l})
                break

    # ── Historial de acciones unificado (audit log + estados + acciones masivas) ──
    timeline = _build_employee_timeline(company_id, employee_id, sandbox=sandbox)

    dependents = hr.get_employee_dependents(company_id, employee_id, sandbox=sandbox)
    from app.utils.hr_utils import calculate_age, is_minor, RELATIONSHIP_CATALOG
    for d in dependents:
        d["_age"] = calculate_age(d.get("birthDate", ""))
        d["_isMinor"] = is_minor(d.get("birthDate", ""))
    dep_minor = sum(1 for d in dependents if d.get("_isMinor"))
    dep_adult = sum(1 for d in dependents if d.get("active", True) and not d.get("_isMinor"))
    dep_financial = sum(1 for d in dependents if d.get("active", True) and d.get("isFinancialDependent", True))
    dep_student = sum(1 for d in dependents if d.get("active", True) and d.get("isStudent"))

    from app.services.herramientas_service import get_asignaciones_por_empleado

    herramientas_asignadas = get_asignaciones_por_empleado(owner_uid, employee_id, sandbox=sandbox)

    # ── Movimientos recurrentes del empleado (tab de la ficha) ──
    from app.services.recurring_service import get_applications_by_employee
    recurring_movements = hr.get_recurring_movements(
        company_id, employee_id=employee_id, sandbox=sandbox)
    recurring_movements.sort(
        key=lambda m: (m.get("status") != "active", m.get("priority", 50)))
    _apps_by_mv = {}
    for _app in get_applications_by_employee(company_id, employee_id, sandbox=sandbox):
        _apps_by_mv.setdefault(_app.get("recurringMovementId", ""), []).append(_app)
    for _mv in recurring_movements:
        _mv["_applications"] = _apps_by_mv.get(_mv.get("id", ""), [])
        _mv["_totalApplied"] = sum(
            float(_a.get("appliedAmount", 0) or 0)
            for _a in _mv["_applications"] if _a.get("action") == "applied")

    offboarding_requests = []
    offboarding_states = {}
    try:
        from app.services.offboarding_data_service import list_requests as _list_offboard_reqs
        from app.models.offboarding import OFFBOARDING_STATES as _off_states
        offboarding_requests = _list_offboard_reqs(company_id, sandbox, limit=5)
        offboarding_requests = [r for r in offboarding_requests if r.get("employeeId") == employee_id]
        offboarding_states = _off_states
    except Exception:
        pass

    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id)
    employee_work_days = PayrollService.resolve_employee_work_days(company_id, employee, sandbox=sandbox)
    from app.data.education_catalog import get_education_label
    from app.data.nationality_catalog import get_nationality_name
    from app.data.disability_catalog import get_disability_name, normalize_disability
    _dis_names = [
        get_disability_name(c)
        for c in normalize_disability(employee.get("disability")).split(",")
        if get_disability_name(c)
    ]
    return render_template("rrhh/employee_view.html", active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee), vacation_days=vacation_days,
                           severance=severance, evaluations=evals, trainings=trainings,
                           documents=docs, payment_history=payment_history,
                           timeline=timeline,
                           active_requests=active_requests,
                           average_salary=average_salary,
                           payroll_groups=hr.get_payroll_groups(company_id, sandbox=sandbox),
                           branches=branches,
                           dependents=dependents, dep_minor=dep_minor, dep_adult=dep_adult,
                           dep_financial=dep_financial, dep_student=dep_student,
                           relationship_catalog=RELATIONSHIP_CATALOG,
                           herramientas_asignadas=herramientas_asignadas,
                           recurring_movements=recurring_movements,
                           offboarding_requests=offboarding_requests,
                           states=offboarding_states,
                           sirla_education_label=get_education_label(employee.get("sirlaEducationCode", "")),
                           sirla_nationality_name=get_nationality_name(employee.get("nationality", 1)),
                           sirla_disability_names=", ".join(_dis_names),
                           employee_work_days=employee_work_days)


def _timeline_export_query() -> dict:
    return {
        "category": request.args.get("type", "").strip(),
        "actor": request.args.get("actor", "").strip(),
        "date_from": request.args.get("date_from", "").strip(),
        "date_to": request.args.get("date_to", "").strip(),
    }


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/actions/export.csv")
def employee_actions_export_csv(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    timeline = _filter_timeline(_build_employee_timeline(company_id, employee_id, sandbox=sandbox),
                                **_timeline_export_query())

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Hora", "Tipo", "Detalle", "Registrado por"])
    for it in timeline:
        writer.writerow([
            it.get("_date", ""), it.get("_time", ""),
            it.get("label", ""), it.get("detail", ""), it.get("actor", ""),
        ])
    buffer = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(buffer, mimetype="text/csv", as_attachment=True,
                     download_name=f"historial_acciones_{employee_id}.csv")


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/actions/export.pdf")
def employee_actions_export_pdf(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    timeline = _filter_timeline(_build_employee_timeline(company_id, employee_id, sandbox=sandbox),
                                **_timeline_export_query())

    try:
        from weasyprint import HTML as WeasyprintHTML
        from app.utils.pdf import pdf_write_options
        rendered = render_template("rrhh/employee_actions_pdf.html",
                                   employee=employee, timeline=timeline,
                                   now=date.today().strftime("%d/%m/%Y"))
        pdf_bytes = WeasyprintHTML(string=rendered, base_url=request.host_url).write_pdf(**pdf_write_options())
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True,
                         download_name=f"historial_acciones_{employee_id}.pdf")
    except Exception as e:
        print(f"Error generando PDF de historial de acciones: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/rehire", methods=["POST"])
def employee_rehire(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    hr_serv = hr
    employee = hr_serv.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    if is_active_equivalent(employee.get("status", "")):
        flash("El empleado ya está activo.", "warning")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    new_hire_date = request.form.get("newHireDate", "").strip()
    new_position = request.form.get("newPosition", "").strip()
    new_department = request.form.get("newDepartment", "").strip()
    new_salary = float(request.form.get("newSalary", "0") or 0)
    preserves_seniority = request.form.get("preservesSeniority") == "1"
    reset_vacation = request.form.get("resetVacation") == "1"

    employee["status"] = "activo"
    employee["hireDate"] = new_hire_date or employee.get("hireDate", "")

    if not preserves_seniority:
        employee["originalHireDate"] = employee.get("hireDate", "")
        employee["hireDate"] = new_hire_date or employee.get("hireDate", "")
        employee["rehireAdjustedSeniority"] = False

    if new_position:
        employee["position"] = new_position
    if new_department:
        employee["departmentId"] = new_department
    if new_salary > 0:
        employee["baseSalary"] = new_salary
        employee["salary"] = new_salary

    employee.pop("terminationDate", None)
    employee.pop("terminationReason", None)
    employee["rehireDate"] = datetime.now(timezone.utc).isoformat()
    employee["rehireCount"] = employee.get("rehireCount", 0) + 1

    if reset_vacation:
        employee["vacationGranted"] = 0

    hr_serv.save_employee(company_id, employee_id, employee, sandbox=sandbox)

    from app.services.payroll_audit_service import log_action
    log_action(company_id, "rehire", "employee", employee_id,
               session.get("user", {}).get("email", ""),
               changes={"status": "activo", "rehireDate": employee["rehireDate"]},
               sandbox=sandbox)

    flash(f"Empleado {employee.get('fullName', '')} recontratado exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/photo", methods=["POST"])
def employee_photo_upload(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    
    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))
        
    file = request.files.get("photo")
    if not file or not file.filename:
        flash("No se seleccionó ninguna imagen.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))
        
    content = file.read()
    max_size = 2 * 1024 * 1024  # 2MB
    if len(content) > max_size:
        flash("La imagen excede el tamaño máximo de 2MB.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))
        
    mime_type = file.content_type or "image/jpeg"
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    from app.services.db_service import DatabaseService
    destination_path = f"users/{owner_uid}/employees/{employee_id}/photo_{uuid.uuid4().hex[:8]}.{ext}"
    photo_url = DatabaseService.upload_file_to_storage(content, destination_path, mime_type)

    employee["photoUrl"] = photo_url
    employee.pop("photoBase64", None)
    hr.save_employee(company_id, employee_id, employee, sandbox=sandbox)
    
    flash("Foto de perfil actualizada exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))
