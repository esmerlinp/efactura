"""Blueprint de RRHH: empleados, asistencia, vacaciones, permisos, nómina, evaluaciones, capacitaciones."""

import io
import os
import csv
import json
import uuid
import calendar
import re
import html
import threading
from datetime import datetime, timezone, date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file, current_app

web_rrhh_bp = Blueprint("web_rrhh", __name__, template_folder="templates")


def _get_owner_uid_and_sandbox():
    uid = session.get("user", {}).get("ownerUID", "")
    sandbox = session.get("is_sandbox_mode", True)
    return uid, sandbox


def _login_required():
    return "user" not in session


def _is_hr_role():
    user = session.get("user", {})
    role = user.get("role", "")
    perms = user.get("permissions", {})
    return role == "owner" or perms.get("canHR", True)


def _sanitize_for_role(employee: dict) -> dict:
    if _is_hr_role():
        return employee
    safe = dict(employee)
    for field in ("baseSalary", "salary", "hourlyRate", "accountNumber", "bank", "accountType",
                  "salaryType", "afpProvider", "afpSalaryCap", "sfsSalaryCap", "tssRegistrationNumber"):
        if field in safe:
            safe[field] = "***"
    return safe


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: Generar períodos disponibles según frecuencia
# ═══════════════════════════════════════════════════════════════════════════

MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _filter_employees_by_period(employees, period_key=None, frequency_mode=None):
    """Compatibilidad: ahora todos los empleados del grupo se incluyen sin filtrar."""
    return list(employees), []


def _generate_periods(frequency: str, year: int = None):
    """Genera lista de períodos disponibles para el año."""
    if year is None:
        year = date.today().year
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
                "type": "quincenal",
            })
            periods.append({
                "key": f"{year}-{m:02d}-2",
                "label": f"Q2: 16 {label_m} - {last_day} {label_m}",
                "start": f"{year}-{m:02d}-16",
                "end": f"{year}-{m:02d}-{last_day}",
                "type": "quincenal",
            })
    if frequency in ("mensual", "ambos", "quincenal_y_mensual"):
        for m in range(1, 13):
            label_m = MONTHS_ES[m - 1]
            last_day = calendar.monthrange(year, m)[1]
            periods.append({
                "key": f"{year}-{m:02d}-M",
                "label": f"M: {label_m} {year}",
                "start": f"{year}-{m:02d}-01",
                "end": f"{year}-{m:02d}-{last_day}",
                "type": "mensual",
            })
    return periods


# ═══════════════════════════════════════════════════════════════════════════
# ONBOARDING — Frecuencia de pago
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/onboarding")
def onboarding_guide():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    positions = hr.get_catalog(owner_uid, "positions", sandbox=sandbox)
    departments = hr.get_catalog(owner_uid, "departments", sandbox=sandbox)

    step1_done = bool(config.get("payrollFrequency"))
    step2_done = len(positions) > 0 and len(departments) > 0
    step3_done = len([e for e in employees if e.get("status") == "activo"]) > 0
    step4_done = True  # Concepts have defaults, always seeded
    step5_done = len(periods) > 0

    steps = [
        {"number": 1, "done": step1_done,
         "title": "Frecuencia de pago", "description": "Define si pagas nómina quincenal o mensual.",
         "url": url_for("web_rrhh.payroll_setup"), "action": "Configurar frecuencia"},
        {"number": 2, "done": step2_done,
         "title": "Catálogos", "description": "Define las posiciones (cargos) y departamentos de tu empresa.",
         "url": url_for("web_rrhh.catalog_list", catalog_name="positions"), "action": "Configurar catálogos"},
        {"number": 3, "done": step3_done,
         "title": "Primer empleado", "description": "Registra la información de las personas de tu equipo.",
         "url": url_for("web_rrhh.employee_new"), "action": "Agregar empleado"},
        {"number": 4, "done": step4_done,
         "title": "Conceptos de nómina", "description": "Revisa ingresos, deducciones y aportes configurados.",
         "url": url_for("web_rrhh.concept_list"), "action": "Revisar conceptos"},
        {"number": 5, "done": step5_done,
         "title": "Calcular nómina", "description": "Procesa tu primer período de nómina.",
         "url": url_for("web_rrhh.payroll_new"), "action": "Calcular nómina"},
    ]

    all_done = all(s["done"] for s in steps)
    next_step = next((s["number"] for s in steps if not s["done"]), None)

    return render_template("rrhh/onboarding_guide.html", active_page="rrhh_dashboard",
                           steps=steps, all_done=all_done, next_step=next_step)


@web_rrhh_bp.route("/rrhh/payroll/setup", methods=["GET", "POST"])
def payroll_setup():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from uuid import uuid4

    if request.method == "POST":
        selection = request.form.get("payroll_type", "")
        config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        user_email = session.get("user", {}).get("email", "")

        if selection == "mensual":
            config["payrollFrequency"] = "mensual"
            hr.save_payroll_config(owner_uid, config, sandbox=sandbox)
            gid = str(uuid4())
            hr.save_payroll_group(owner_uid, gid, {
                "id": gid, "name": "Nómina Mensual", "description": "",
                "frequency": "mensual", "isActive": True,
                "createdAt": now_iso, "updatedAt": now_iso, "createdBy": user_email,
            }, sandbox=sandbox)
            flash("Grupo «Nómina Mensual» creado.", "success")

        elif selection == "quincenal":
            config["payrollFrequency"] = "quincenal"
            hr.save_payroll_config(owner_uid, config, sandbox=sandbox)
            gid = str(uuid4())
            hr.save_payroll_group(owner_uid, gid, {
                "id": gid, "name": "Nómina Quincenal", "description": "",
                "frequency": "quincenal", "isActive": True,
                "createdAt": now_iso, "updatedAt": now_iso, "createdBy": user_email,
            }, sandbox=sandbox)
            flash("Grupo «Nómina Quincenal» creado.", "success")

        elif selection == "ambos":
            config["payrollFrequency"] = "mensual"
            hr.save_payroll_config(owner_uid, config, sandbox=sandbox)
            gid1 = str(uuid4())
            hr.save_payroll_group(owner_uid, gid1, {
                "id": gid1, "name": "Nómina Mensual", "description": "",
                "frequency": "mensual", "isActive": True,
                "createdAt": now_iso, "updatedAt": now_iso, "createdBy": user_email,
            }, sandbox=sandbox)
            gid2 = str(uuid4())
            hr.save_payroll_group(owner_uid, gid2, {
                "id": gid2, "name": "Nómina Quincenal", "description": "",
                "frequency": "quincenal", "isActive": True,
                "createdAt": now_iso, "updatedAt": now_iso, "createdBy": user_email,
            }, sandbox=sandbox)
            flash("Grupos «Nómina Mensual» y «Nómina Quincenal» creados.", "success")

        else:
            flash("Selecciona una opción válida.", "error")
            return redirect(url_for("web_rrhh.payroll_setup"))

        config["onboardingCompleted"] = True
        hr.save_payroll_config(owner_uid, config, sandbox=sandbox)
        flash("¡Configuración de nómina guardada exitosamente!", "success")
        return redirect(url_for("web_rrhh.onboarding_guide"))

    return render_template("rrhh/payroll_onboarding.html", active_page="rrhh_dashboard")


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/dashboard")
def payroll_dashboard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_static_data import DEFAULT_PAYROLL_CONFIG

    # Verificar onboarding
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    if not config.get("onboardingCompleted"):
        return redirect(url_for("web_rrhh.onboarding_guide"))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    user_name = session.get("user", {}).get("displayName", "")

    # ── Onboarding steps ──
    positions = hr.get_catalog(owner_uid, "positions", sandbox=sandbox)
    departments = hr.get_catalog(owner_uid, "departments", sandbox=sandbox)
    onboard_steps = {
        "frequency": bool(config.get("payrollFrequency")),
        "catalogs": len(positions) > 0 and len(departments) > 0,
        "employees": len([e for e in employees if e.get("status") == "activo"]) > 0,
        "concepts": True,
        "payroll": len(periods) > 0,
    }
    onboard_done_count = sum(1 for v in onboard_steps.values() if v)
    onboard_all_done = all(onboard_steps.values())

    # ── Greeting dinámico según hora del día ──
    now = datetime.now()
    hour = now.time().hour
    if hour < 12:
        greeting = f"¡Buenos días, {user_name}!"
    elif hour < 18:
        greeting = f"¡Buenas tardes, {user_name}!"
    else:
        greeting = f"¡Buenas noches, {user_name}!"

    # ── Steps reales (4 pasos definidos) ──
    steps = 0
    if config.get("payrollFrequency"):
        steps += 1  # Paso 1: Frecuencia configurada
    if employees:
        steps += 1  # Paso 2: Al menos 1 empleado registrado
    calculated = [p for p in periods if p.get("status") in ("calculada", "validada", "aprobada", "contabilizada", "pagada", "cerrada", "procesada")]
    if calculated:
        steps += 1  # Paso 3: Al menos 1 período calculado
    closed_or_paid = [p for p in periods if p.get("status") in ("pagada", "cerrada", "contabilizada")]
    if closed_or_paid:
        steps += 1  # Paso 4: Al menos 1 período pagado o cerrado
    progress_percent = int((steps / 4) * 100)

    # ── Grupos de nómina para dashboard ──
    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))
    for g in payroll_groups:
        g["_employee_count"] = len([e for e in employees if g["id"] in e.get("payrollGroupIds", [])])
        g["_period_count"] = len([p for p in periods if p.get("payrollGroupId") == g["id"]])

    # Periodo actual
    # Periodo actual
    frequency = config.get("payrollFrequency", "mensual")
    now = date.today()
    current_period = ""
    if frequency in ("quincenal",):
        day = now.day
        label_m = MONTHS_ES[now.month - 1]
        last_day = calendar.monthrange(now.year, now.month)[1]
        if day <= 15:
            current_period = f"Q1: 1 {label_m} - 15 {label_m}"
        else:
            current_period = f"Q2: 16 {label_m} - {last_day} {label_m}"
    else:
        current_period = f"{MONTHS_ES[now.month - 1]} {now.year}"

    # Totales
    active_emps = [e for e in employees if e.get("status") == "activo"]
    total_pago = sum(p.get("totalNet", 0) for p in periods)
    total_costo = sum(p.get("totalGross", 0) + p.get("totalEmployerContrib", 0) for p in periods)

    # Gráficas
    sorted_periods = sorted(periods, key=lambda p: p.get("processedDate", ""))
    chart_labels = []
    costo_data = []
    pago_data = []
    for p in sorted_periods[-6:]:  # Últimos 6 períodos
        label = p.get("periodRange") or p.get("periodKey", "")
        if len(label) > 14:
            parts = label.split(" - ")
            label = parts[0] if len(label) > 14 else label
        chart_labels.append(label)
        costo_data.append(round(p.get("totalGross", 0) + p.get("totalEmployerContrib", 0), 2))
        pago_data.append(round(p.get("totalNet", 0), 2))

    # Contrataciones por mes
    hiring_by_month = {}
    for emp in employees:
        try:
            hd = emp.get("hireDate", "")
            if hd:
                dt = datetime.strptime(hd[:10], "%Y-%m-%d")
                key = f"{MONTHS_ES[dt.month - 1]}"
                hiring_by_month[key] = hiring_by_month.get(key, 0) + 1
        except (ValueError, TypeError):
            pass

    # Terminaciones por mes (rotación)
    termination_by_month = {}
    for emp in employees:
        try:
            td = emp.get("terminationDate", "")
            if td and emp.get("status") == "inactivo":
                dt = datetime.strptime(td[:10], "%Y-%m-%d")
                key = f"{MONTHS_ES[dt.month - 1]}"
                termination_by_month[key] = termination_by_month.get(key, 0) + 1
        except (ValueError, TypeError):
            pass

    rotation_labels = []
    rotation_hires = []
    rotation_terms = []
    for m in MONTHS_ES:
        if m in hiring_by_month or m in termination_by_month:
            rotation_labels.append(m)
            rotation_hires.append(hiring_by_month.get(m, 0))
            rotation_terms.append(termination_by_month.get(m, 0))

    hiring_labels = []
    hiring_data = []
    for m in MONTHS_ES:
        if m in hiring_by_month:
            hiring_labels.append(m)
            hiring_data.append(hiring_by_month[m])

    # Períodos recientes
    recent = sorted(periods, key=lambda p: p.get("processedDate", ""), reverse=True)[:5]

    indicators = {
        "year": config.get("year", 2026),
        "minSalary": config.get("minSalary", 23223.00),
        "afpTotal": config.get("afpTotal", 464460.00),
        "sfsTotal": config.get("sfsTotal", 232230.00),
        "srlTotal": config.get("srlTotal", 92892.40),
    }

    return render_template("rrhh/payroll_dashboard.html", active_page="rrhh_dashboard",
                           user_name=user_name, greeting=greeting, employee_count=len(active_emps),
                           current_period=current_period,
                           total_pago=total_pago, total_costo=total_costo,
                           steps_completed=steps, progress_percent=progress_percent,
                           chart_labels=chart_labels, costo_data=costo_data, pago_data=pago_data,
                           hiring_labels=hiring_labels, hiring_data=hiring_data,
                           rotation_labels=rotation_labels, rotation_hires=rotation_hires,
                           rotation_terms=rotation_terms,
                           recent_periods=recent, indicators=indicators,
                           onboard_steps=onboard_steps, onboard_done_count=onboard_done_count,
                           onboard_all_done=onboard_all_done,
                           payroll_groups=payroll_groups, payroll_frequency=frequency)


# ═══════════════════════════════════════════════════════════════════════════
# REDIRECT: /rrhh/payroll → dashboard (o onboarding)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll")
def payroll_redirect():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return redirect(url_for("web_rrhh.payroll_dashboard"))


# ═══════════════════════════════════════════════════════════════════════════
# LANDING PAGES — Índices con tarjetas de navegación
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/empleados")
def employees_index():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/employees_index.html", active_page="rrhh_employees")


@web_rrhh_bp.route("/rrhh/asistencia")
def attendance_index():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/attendance_index.html", active_page="rrhh_attendance")


@web_rrhh_bp.route("/rrhh/nomina")
def payroll_index():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/payroll_index.html", active_page="rrhh_payroll")


@web_rrhh_bp.route("/rrhh/desarrollo")
def development_index():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/development_index.html", active_page="rrhh_development")


@web_rrhh_bp.route("/rrhh/configuracion")
def settings_index():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/settings_index.html", active_page="rrhh_settings")


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYEES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees")
def employee_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    from app.services.payroll_service import PayrollService
    for emp in employees:
        emp["vacationDays"] = PayrollService.calculate_vacation_days(emp.get("hireDate", ""))

    # ── Filtros ──
    search = request.args.get("search", "").strip().lower()
    filter_status = request.args.get("status", "").strip()
    filter_area = request.args.get("area", "").strip()
    if search:
        employees = [e for e in employees if
                     search in (e.get("fullName", "") + " " +
                               e.get("cedula", "") + " " +
                               e.get("idNumber", "") + " " +
                               e.get("position", "")).lower()]
    if filter_status:
        employees = [e for e in employees if e.get("status", "") == filter_status]
    if filter_area:
        employees = [e for e in employees if e.get("area", "") == filter_area or e.get("department", "") == filter_area]

    total = len(employees)
    active_count = sum(1 for e in employees if e.get("status") == "activo")
    inactive_count = sum(1 for e in employees if e.get("status") == "inactivo")

    # ── Áreas disponibles para filtro ──
    areas_set = sorted(set(e.get("area", "") or e.get("department", "") for e in employees if e.get("area") or e.get("department")))

    # ── Paginación ──
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(10, min(100, int(request.args.get("per_page", 25))))
    except (ValueError, TypeError):
        page, per_page = 1, 25
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    paged = employees[start:start + per_page]

    return render_template("rrhh/employee_list.html", active_page="rrhh_employees",
                           employees=paged, page=page, total_pages=total_pages,
                           total=total, per_page=per_page,
                           search=request.args.get("search", ""),
                           filter_status=filter_status, filter_area=filter_area,
                           areas_set=areas_set, active_count=active_count,
                           inactive_count=inactive_count)


@web_rrhh_bp.route("/rrhh/employees/new", methods=["GET", "POST"])
def employee_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_static_data import (
        ID_TYPES, MUNICIPIOS_RD, CONTRACT_TYPES, AREAS, WORKDAYS,
        PAYMENT_METHODS, BANCOS_RD, ACCOUNT_TYPES, PAYROLL_FREQUENCIES,
    )

    if request.method == "POST":
        emp_id = str(uuid.uuid4())
        first_name = request.form.get("firstName", "").strip()
        first_last_name = request.form.get("firstLastName", "").strip()
        middle_name = request.form.get("middleName", "").strip()
        second_last_name = request.form.get("secondLastName", "").strip()

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
            "position": request.form.get("position", "").strip(),
            "area": request.form.get("area", "").strip(),
            "costCenter": request.form.get("costCenter", request.form.get("area", "")).strip(),
            "department": request.form.get("area", "").strip(),
            "branchId": "",
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
            "afpProvider": "",
            "notes": request.form.get("notes", "").strip(),
            "gender": request.form.get("gender", "").strip(),
            "birthDate": request.form.get("birthDate", "").strip(),
            "probationEndDate": request.form.get("probationEndDate", "").strip(),
            "reportsTo": request.form.get("reportsTo", "").strip(),
            "maritalStatus": request.form.get("maritalStatus", "").strip(),
            "occupationCode": request.form.get("occupationCode", "").strip(),
            "weeklyHours": int(request.form.get("weeklyHours", 44) or 44),
            "workShift": int(request.form.get("workShift", 1) or 1),
            "educationLevel": int(request.form.get("educationLevel", 0) or 0),
            "vacationGranted": int(request.form.get("vacationGranted", 1) or 1),
            "nationality": 1,
        }
        hr.save_employee(owner_uid, emp_id, data, sandbox=sandbox)

        # ── Crear entrada inicial en historial de salarios ──
        from app.services import hr_data_service as hr2
        salary = float(request.form.get("salary", 0) or 0)
        if salary > 0:
            history_id = str(uuid.uuid4())
            hr2.save_salary_history_entry(owner_uid, {
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
        log_action(owner_uid, "create", "employee", emp_id,
                   session.get("user", {}).get("email", ""),
                   changes={"name": data["fullName"], "salary": salary}, sandbox=sandbox)

        flash("Empleado creado exitosamente.", "success")
        return redirect(url_for("web_rrhh.employee_list"))

    # Obtener reference data del usuario (con respaldo estático)
    ref_data = hr.get_reference_data(owner_uid, sandbox=sandbox)
    contract_types = ref_data.get("contractTypes", CONTRACT_TYPES)
    areas = ref_data.get("areas", AREAS)
    supervisors = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]
    positions = hr.get_catalog(owner_uid, "positions", sandbox=sandbox)
    departments = hr.get_catalog(owner_uid, "departments", sandbox=sandbox)
    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    from app.data.occupations_catalog import OCCUPATIONS
    return render_template("rrhh/employee_form.html", active_page="rrhh_employees", employee=None,
                           id_types=ID_TYPES, municipios=MUNICIPIOS_RD,
                           contract_types=contract_types, areas=areas,
                           workdays=WORKDAYS, payment_methods=PAYMENT_METHODS,
                           bancos=BANCOS_RD, account_types=ACCOUNT_TYPES,
                           supervisors=supervisors,
                           positions=positions, departments=departments,
                           payroll_groups=payroll_groups,
                           occupations=OCCUPATIONS)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/edit", methods=["GET", "POST"])
def employee_edit(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_static_data import (
        ID_TYPES, MUNICIPIOS_RD, CONTRACT_TYPES, AREAS, WORKDAYS,
        PAYMENT_METHODS, BANCOS_RD, ACCOUNT_TYPES, PAYROLL_FREQUENCIES,
    )

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    if request.method == "POST":
        first_name = request.form.get("firstName", "").strip()
        first_last_name = request.form.get("firstLastName", "").strip()
        middle_name = request.form.get("middleName", "").strip()
        second_last_name = request.form.get("secondLastName", "").strip()

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
            "position": request.form.get("position", "").strip(),
            "area": request.form.get("area", "").strip(),
            "costCenter": request.form.get("costCenter", request.form.get("area", "")).strip(),
            "department": request.form.get("area", "").strip(),
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
            "educationLevel": int(request.form.get("educationLevel", 0) or 0),
            "vacationGranted": int(request.form.get("vacationGranted", 1) or 1),
            "nationality": employee.get("nationality", 1),
        })
        hr.save_employee(owner_uid, employee_id, employee, sandbox=sandbox)

        # ── Historial de cambios estructurales ──
        new_position = request.form.get("position", "").strip()
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
            hr.save_employment_history(owner_uid, {
                "id": str(uuid.uuid4()), "employeeId": employee_id,
                "changedAt": datetime.now(timezone.utc).isoformat(),
                "changedBy": session.get("user", {}).get("email", ""),
                "changes": changes, "newPosition": new_position, "newDepartment": new_department,
            }, sandbox=sandbox)

        from app.services.payroll_audit_service import log_action
        log_action(owner_uid, "update", "employee", employee_id,
                   session.get("user", {}).get("email", ""),
                   changes={"position": new_position, "department": new_department, "supervisor": new_supervisor}, sandbox=sandbox)

        flash("Empleado actualizado exitosamente.", "success")
        return redirect(url_for("web_rrhh.employee_list"))

    ref_data = hr.get_reference_data(owner_uid, sandbox=sandbox)
    contract_types = ref_data.get("contractTypes", CONTRACT_TYPES)
    areas = ref_data.get("areas", AREAS)
    supervisors = [e for e in hr.get_employees(owner_uid, sandbox=sandbox)
                   if e.get("status") == "activo" and e.get("id") != employee_id]
    positions = hr.get_catalog(owner_uid, "positions", sandbox=sandbox)
    departments = hr.get_catalog(owner_uid, "departments", sandbox=sandbox)
    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    from app.data.occupations_catalog import OCCUPATIONS
    return render_template("rrhh/employee_form.html", active_page="rrhh_employees", employee=employee,
                           id_types=ID_TYPES, municipios=MUNICIPIOS_RD,
                           contract_types=contract_types, areas=areas,
                           workdays=WORKDAYS, payment_methods=PAYMENT_METHODS,
                           bancos=BANCOS_RD, account_types=ACCOUNT_TYPES,
                           supervisors=supervisors,
                           positions=positions, departments=departments,
                           payroll_groups=payroll_groups,
                           occupations=OCCUPATIONS)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/view")
def employee_view(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    vacation_days = PayrollService.calculate_vacation_days(employee.get("hireDate", ""))
    severance = PayrollService.calculate_severance(
        employee.get("baseSalary", 0), employee.get("hireDate", "")
    )
    evals = [e for e in hr.get_evaluations(owner_uid, sandbox=sandbox) if e.get("employeeId") == employee_id]
    trainings = [t for t in hr.get_trainings(owner_uid, sandbox=sandbox) if t.get("employeeId") == employee_id]
    docs = hr.get_employee_documents(owner_uid, employee_id, sandbox=sandbox)

    # Historial de pagos (últimos 24 períodos)
    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    payment_history = []
    for p in sorted(periods, key=lambda x: x.get("periodKey", ""), reverse=True)[:24]:
        for l in p.get("lines", []):
            if l.get("employeeId") == employee_id:
                payment_history.append({"period": p, "line": l})
                break

    # Acciones de personal masivas que afectaron a este empleado
    mass_actions = hr.get_mass_actions(owner_uid, sandbox=sandbox)
    ACTION_LABELS = {
        "salary_change": "Cambio Salarial", "position_change": "Cambio de Puesto",
        "supervisor_change": "Cambio de Supervisor", "promotion": "Promoción",
        "mass_absence": "Ausencia Masiva", "desvinculacion": "Desvinculación",
    }
    employee_actions = []
    for ma in mass_actions:
        for r in ma.get("results", []):
            if r.get("employeeId") == employee_id:
                employee_actions.append({
                    "id": ma["id"],
                    "actionType": ma["actionType"],
                    "actionTypeLabel": ACTION_LABELS.get(ma["actionType"], ma["actionType"]),
                    "createdAt": ma.get("createdAt", ""),
                    "createdBy": ma.get("createdBy", ""),
                    "status": ma.get("status", ""),
                    "result": r,
                })
                break
    employee_actions.sort(key=lambda a: a.get("createdAt", ""), reverse=True)

    return render_template("rrhh/employee_view.html", active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee), vacation_days=vacation_days,
                           severance=severance, evaluations=evals, trainings=trainings,
                           documents=docs, payment_history=payment_history,
                           employee_actions=employee_actions,
                           payroll_groups=hr.get_payroll_groups(owner_uid, sandbox=sandbox))


# ═══════════════════════════════════════════════════════════════════════════
# VOLANTE DE PAGO — Ver, Descargar PDF, Enviar por Email
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/payslip/<period_id>")
def employee_payslip(employee_id, period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    line = next((l for l in period.get("lines", []) if l.get("employeeId") == employee_id), None)
    if not line:
        flash("El empleado no tiene línea de nómina en este período.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    return render_template("rrhh/employee_payslip.html", active_page="rrhh_employees",
                           employee=employee, period=period, line=line)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/payslip/<period_id>/pdf")
def employee_payslip_pdf(employee_id, period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not employee or not period:
        return "Empleado o período no encontrado.", 404

    line = next((l for l in period.get("lines", []) if l.get("employeeId") == employee_id), None)
    if not line:
        return "Línea de nómina no encontrada.", 404

    try:
        from weasyprint import HTML as WeasyprintHTML
        rendered = render_template("rrhh/employee_payslip.html",
                                   employee=employee, period=period, line=line)
        pdf_bytes = WeasyprintHTML(string=rendered, base_url=request.host_url).write_pdf()
        filename = f"volante_{period.get('periodKey','')}_{employee.get('fullName','empleado')}.pdf"
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"⚠️ Error generando PDF de volante: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.employee_payslip", employee_id=employee_id, period_id=period_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/payslip/<period_id>/email", methods=["POST"])
def employee_payslip_email(employee_id, period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not employee or not period:
        flash("Empleado o período no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    employee_email = (employee.get("email") or "").strip()
    if not employee_email:
        flash("El empleado no tiene un correo electrónico registrado.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    line = next((l for l in period.get("lines", []) if l.get("employeeId") == employee_id), None)
    if not line:
        flash("Línea de nómina no encontrada.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    try:
        from app.services.mailer import Mailer
        html_body = render_template("rrhh/employee_payslip_email.html",
                                    employee=employee, period=period, line=line)
        period_label = period.get("periodRange") or period.get("periodKey", "")
        subject = f"Volante de pago — {period_label}"
        Mailer.send(
            app=current_app._get_current_object(),
            to_email=employee_email,
            subject=subject,
            html_body=html_body,
            from_name=current_app.config.get("COMPANY_NAME", ""),
            category="noreply",
        )
        flash(f"Volante enviado a {employee_email}.", "success")
    except Exception as e:
        print(f"⚠️ Error enviando volante por email: {e}")
        flash("Error al enviar el volante por correo.", "error")

    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/calculate-payroll", methods=["POST"])
def employee_calculate_payroll(employee_id):
    if _login_required():
        return jsonify({"error": "No autorizado"}), 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        return jsonify({"error": "Empleado no encontrado"}), 404

    base_salary = float(employee.get("baseSalary", 0))
    period_type = request.form.get("period_type", "mensual")
    overtime_hours = float(request.form.get("overtime_hours", 0) or 0)
    commission = float(request.form.get("commission", 0) or 0)
    bonus = float(request.form.get("bonus", 0) or 0)
    other_income = float(request.form.get("other_income", 0) or 0)
    other_deductions = float(request.form.get("other_deductions", 0) or 0)

    tax_rates_data = hr.get_tax_rates(owner_uid, sandbox=sandbox)
    rates = PayrollService.get_rates(tax_rates_data)

    calc = PayrollService.calculate_payroll_line(
        base_salary=base_salary,
        tax_rates=tax_rates_data,
        overtime_hours=overtime_hours,
        commission=commission,
        bonus=bonus,
        other_income=other_income,
        other_deductions=other_deductions,
        period_type=period_type,
    )

    total_employer = calc.get("totalEmployerContrib", 0)
    costo_empresa = round(calc.get("totalIncome", 0) + total_employer, 2)

    return jsonify({
        "period_type": period_type,
        "baseSalary": calc.get("baseSalary"),
        "grossSalary": calc.get("grossSalary"),
        "overtimeHours": overtime_hours,
        "overtimePay": calc.get("overtimePay"),
        "overtimeRate": rates.get("overtime_rate", 1.35),
        "commission": commission,
        "bonus": bonus,
        "otherIncome": other_income,
        "totalIncome": calc.get("totalIncome"),
        "afpEmployee": calc.get("afpEmployee"),
        "afpEmployeeRate": rates.get("afp_employee_rate", 0),
        "sfsEmployee": calc.get("sfsEmployee"),
        "sfsEmployeeRate": rates.get("sfs_employee_rate", 0),
        "infotepEmployee": calc.get("infotepEmployee", 0),
        "isrRetention": calc.get("isrRetention"),
        "otherDeductions": other_deductions,
        "totalDeductions": calc.get("totalDeductions"),
        "netSalary": calc.get("netSalary"),
        "afpEmployer": calc.get("afpEmployer"),
        "sfsEmployer": calc.get("sfsEmployer"),
        "srlEmployer": calc.get("srlEmployer"),
        "infotepEmployer": calc.get("infotepEmployer"),
        "totalEmployerContrib": total_employer,
        "costoEmpresa": costo_empresa,
        "minSalary": rates.get("min_salary", 23223),
        "afpSalaryCap": rates.get("afp_salary_cap", 196750),
        "sfsSalaryCap": rates.get("sfs_salary_cap", 98375),
        "infotepThreshold": rates.get("infotep_threshold_multiplier", 5),
        "workingDaysPerMonth": rates.get("working_days_per_month", 23.83),
        "workingHoursPerDay": rates.get("working_hours_per_day", 8),
    })


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/terminate", methods=["POST"])
def employee_terminate(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    employee["status"] = "inactivo"
    employee["terminationDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    employee["terminationReason"] = request.form.get("reason", "").strip()
    employee["terminationType"] = request.form.get("terminationType", "otro").strip()
    hr.save_employee(owner_uid, employee_id, employee, sandbox=sandbox)
    from app.services.payroll_audit_service import log_action
    log_action(owner_uid, "terminate", "employee", employee_id,
               session.get("user", {}).get("email", ""),
               changes={"status": employee["status"], "reason": employee.get("terminationReason", "")}, sandbox=sandbox)
    flash("Empleado desvinculado.", "success")
    return redirect(url_for("web_rrhh.employee_list"))


# ═══════════════════════════════════════════════════════════════════════════
# LIQUIDACIÓN LABORAL — Cálculo de Prestaciones y Derechos Adquiridos
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/liquidacion", methods=["GET", "POST"])
def employee_liquidacion(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.liquidacion_service import LiquidacionService

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    # ── Auto-calcular vacaciones desde el historial real ──
    hire_date = employee.get("hireDate", "")
    vac_requests = hr.get_vacation_requests(owner_uid, sandbox=sandbox)
    emp_vacs = [v for v in vac_requests
                if v.get("employeeId") == employee_id and v.get("status") == "aprobada"]

    today_str = date.today().isoformat()
    ant_approx = LiquidacionService.calcular_antiguedad(hire_date, today_str)
    ant_years = ant_approx["years"]

    def _add_years(d: str, years: int) -> str:
        try:
            dt = datetime.strptime(d[:10], "%Y-%m-%d")
            y = dt.year + years
            return dt.replace(year=y).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return d

    fecha_ultimo_aniversario = _add_years(hire_date, ant_years) if ant_years > 0 and hire_date else hire_date

    dias_por_anio = 18 if ant_years >= 5 else 14
    taken_before_anniversary = 0
    taken_current = 0

    for v in emp_vacs:
        v_start = v.get("startDate", "")
        if v_start and v_start >= fecha_ultimo_aniversario:
            taken_current += v.get("days", 0)
        else:
            taken_before_anniversary += v.get("days", 0)

    max_expected = ant_years * dias_por_anio
    pending_complete = 0
    if ant_years > 0 and max_expected > taken_before_anniversary:
        pending_complete = (max_expected - taken_before_anniversary) // dias_por_anio

    vacation_auto_pending_complete = max(0, pending_complete)
    vacation_auto_taken_current = max(0, taken_current)
    vacation_auto_total_taken = sum(v.get("days", 0) for v in emp_vacs)
    vacation_auto_total_accrued = max_expected

    resultado = None

    if request.method == "POST":
        termination_type = request.form.get("terminationType", "renuncia").strip()
        termination_date = request.form.get("terminationDate", "").strip()
        preaviso_trabajado = request.form.get("preavisoTrabajado") == "on"
        vacation_pending_complete = int(request.form.get("vacationPendingCompleteYears", "0") or 0)
        vacation_taken_current = int(request.form.get("vacationTakenCurrentPeriod", "0") or 0)
        notes = request.form.get("notes", "").strip()

        base_salary = float(employee.get("baseSalary", 0) or 0)
        salary_frequency = employee.get("paymentFrequency", "") or "mensual"

        # Usar salarios de los últimos 12 meses desde el historial salarial
        salaries_12 = [base_salary]
        try:
            salary_history = hr.get_salary_history(owner_uid, employee_id, sandbox=sandbox)
            if salary_history:
                recent = sorted(salary_history, key=lambda x: x.get("effectiveDate", ""), reverse=True)[:12]
                salaries_12 = [s.get("amount", base_salary) for s in recent if s.get("amount")]
                if not salaries_12:
                    salaries_12 = [base_salary]
        except Exception:
            salaries_12 = [base_salary]

        # Salarios año corriente (enero a fecha de salida)
        try:
            if termination_date:
                td = datetime.strptime(termination_date, "%Y-%m-%d")
                months_ytd = td.month
            else:
                months_ytd = date.today().month
        except ValueError:
            months_ytd = date.today().month
        salaries_ytd = [base_salary] * max(1, months_ytd)

        resultado = LiquidacionService.calcular_liquidacion(
            employee_id=employee_id,
            employee_name=employee.get("fullName", ""),
            cedula=employee.get("cedula", ""),
            hire_date=employee.get("hireDate", ""),
            termination_date=termination_date,
            termination_type=termination_type,
            last_base_salary=base_salary,
            salary_frequency=salary_frequency,
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            preaviso_trabajado=preaviso_trabajado,
            vacation_pending_complete_years=vacation_pending_complete,
            vacation_taken_current_period=vacation_taken_current,
            notes=notes,
            created_by=session.get("user", {}).get("email", ""),
        )

        # Persistir en Firestore
        save_action = request.form.get("save", "").strip()
        if save_action == "1":
            hr.save_liquidacion(owner_uid, resultado["id"], resultado, sandbox=sandbox)
            from app.services.payroll_audit_service import log_action
            log_action(owner_uid, "liquidacion_calculada", "employee", employee_id,
                       session.get("user", {}).get("email", ""),
                       changes={
                           "liquidacionId": resultado["id"],
                           "terminationType": termination_type,
                           "montoTotal": resultado["totales"]["montoTotal"],
                       }, sandbox=sandbox)

            # Desvincular empleado
            if employee.get("status") != "inactivo":
                employee["status"] = "inactivo"
                employee["terminationDate"] = termination_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                employee["terminationType"] = termination_type
                employee["terminationReason"] = notes
                hr.save_employee(owner_uid, employee_id, employee, sandbox=sandbox)
                log_action(owner_uid, "terminate", "employee", employee_id,
                           session.get("user", {}).get("email", ""),
                           changes={"status": "inactivo", "reason": notes}, sandbox=sandbox)

                # Crear registro en historial de acciones de personal
                from uuid import uuid4
                now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                termination_action = {
                    "id": str(uuid4()),
                    "actionType": "desvinculacion",
                    "createdAt": now_iso,
                    "createdBy": session.get("user", {}).get("email", ""),
                    "processedAt": now_iso,
                    "status": "completed",
                    "totalEmployees": 1,
                    "successCount": 1,
                    "errorCount": 0,
                    "selectionCriteria": {"employeeIds": [employee_id]},
                    "payload": {"terminationType": termination_type,
                                "terminationDate": termination_date},
                    "results": [{
                        "employeeId": employee_id,
                        "employeeName": employee.get("fullName", ""),
                        "status": "success",
                        "changes": {
                            "before": {"status": "activo"},
                            "after": {"status": "inactivo",
                                      "terminationDate": termination_date,
                                      "terminationType": termination_type},
                        },
                        "processedAt": now_iso,
                    }],
                    "statusHistory": [{"from": None, "to": "completed",
                                       "at": now_iso,
                                       "by": session.get("user", {}).get("email", "")}],
                }
                hr.save_mass_action(owner_uid, termination_action["id"], termination_action, sandbox=sandbox)

            flash("Liquidación guardada y empleado desvinculado.", "success")
            return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    return render_template("rrhh/employee_liquidacion.html",
                           active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee),
                           resultado=resultado,
                           vacation_auto_pending_complete=vacation_auto_pending_complete,
                           vacation_auto_taken_current=vacation_auto_taken_current,
                           vacation_auto_total_accrued=vacation_auto_total_accrued,
                           vacation_auto_total_taken=vacation_auto_total_taken)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/liquidaciones")
def employee_liquidaciones_list(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    liquidaciones = hr.get_liquidaciones_by_employee(owner_uid, employee_id, sandbox=sandbox)
    return render_template("rrhh/employee_liquidaciones_list.html",
                           active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee),
                           liquidaciones=liquidaciones)

@web_rrhh_bp.route("/rrhh/employees/export")
def employee_export():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    ids = request.args.get("ids", "")
    if ids:
        id_set = set(ids.split(","))
        employees = [e for e in employees if e.get("id") in id_set]

    for emp in employees:
        emp["vacationDays"] = PayrollService.calculate_vacation_days(emp.get("hireDate", ""))

    import io as _io
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empleados"
        ws.append(["Nombre", "Cédula", "Cargo", "Área", "Departamento", "Salario Base",
                    "Tipo Contrato", "Fecha Ingreso", "Estado", "Email", "Teléfono",
                    "Municipio", "Género", "Fecha Nac.", "Supervisor", "Vacaciones"])
        for emp in employees:
            supervisor_name = ""
            sup_id = emp.get("reportsTo", "")
            if sup_id:
                sup = next((e for e in employees if e.get("id") == sup_id), None)
                if sup:
                    supervisor_name = sup.get("fullName", "")
            ws.append([
                emp.get("fullName", ""),
                emp.get("cedula", "") or emp.get("idNumber", ""),
                emp.get("position", ""),
                emp.get("area", "") or emp.get("department", ""),
                emp.get("department", ""),
                emp.get("baseSalary", 0),
                emp.get("contractType", ""),
                emp.get("hireDate", ""),
                emp.get("status", ""),
                emp.get("email", ""),
                emp.get("phone", ""),
                emp.get("municipality", ""),
                emp.get("gender", ""),
                emp.get("birthDate", ""),
                supervisor_name,
                emp.get("vacationDays", 0),
            ])
        output = _io.BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name="empleados.xlsx")
    except ImportError:
        csv_out = _io.StringIO()
        csv_out.write("Nombre,Cédula,Cargo,Área,Salario,Estado,Email,Teléfono,Fecha Ingreso\n")
        for emp in employees:
            csv_out.write(f"{emp.get('fullName','')},{emp.get('cedula','') or emp.get('idNumber','')},"
                         f"{emp.get('position','')},{emp.get('area','') or emp.get('department','')},"
                         f"{emp.get('baseSalary',0)},{emp.get('status','')},{emp.get('email','')},"
                         f"{emp.get('phone','')},{emp.get('hireDate','')}\n")
        buf = _io.BytesIO(csv_out.getvalue().encode("utf-8-sig"))
        return send_file(buf, mimetype="text/csv", as_attachment=True, download_name="empleados.csv")


# ═══════════════════════════════════════════════════════════════════════════
# IMPORTACIÓN MASIVA DE EMPLEADOS — Onboarding de 4 pasos
# ═══════════════════════════════════════════════════════════════════════════

TEMP_IMPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'uploads', 'temp_imports')
JOB_DIR = os.path.join(TEMP_IMPORT_DIR, 'jobs')

EMPLOYEE_CSV_FIELDS = [
    ("*firstName", "Primer nombre", True, ["nombre", "name", "primer_nombre", "firstname", "primer nombre"]),
    ("middleName", "Segundo nombre", False, ["segundo_nombre", "middlename", "segundo nombre"]),
    ("*firstLastName", "Primer apellido", True, ["apellido", "lastname", "primer_apellido", "firstlastname", "primer apellido"]),
    ("secondLastName", "Segundo apellido", False, ["segundo_apellido", "secondlastname", "segundo apellido"]),
    ("*idType", "Tipo de identificación", True, ["tipo", "type", "idtype", "tipo_id", "tipo identificación", "tipo_identificacion"]),
    ("*idNumber", "Número de identificación", True, ["cedula", "rnc", "documento", "identificacion", "identificación", "idnumber", "id", "num_identificacion"]),
    ("*email", "Correo electrónico", True, ["email", "correo", "mail", "correo_electronico"]),
    ("phone", "Teléfono", False, ["telefono", "teléfono", "phone", "celular"]),
    ("*municipality", "Municipio", True, ["municipio", "ciudad", "municipality"]),
    ("*address", "Dirección", True, ["direccion", "dirección", "address", "calle"]),
    ("gender", "Género", False, ["genero", "género", "gender", "sexo"]),
    ("birthDate", "Fecha de nacimiento", False, ["nacimiento", "fecha_nac", "birth", "birthdate", "fecha nacimiento", "fecha_nacimiento"]),
    ("maritalStatus", "Estado civil", False, ["estado_civil", "civil", "marital", "maritalstatus"]),
    ("educationLevel", "Grado de instrucción", False, ["instruccion", "educacion", "educación", "education", "educationlevel", "grado"]),
    ("emergencyContact", "Contacto de emergencia", False, ["emergencia", "emergency", "contacto_emergencia", "emergencycontact"]),
    ("emergencyPhone", "Teléfono de emergencia", False, ["tel_emergencia", "emergencyphone", "telefono_emergencia"]),
    ("afpProvider", "AFP", False, ["afp", "afpprovider", "afp_provider"]),
    ("notes", "Notas", False, ["notas", "notes", "comentario", "comentarios", "observaciones"]),
    ("*hireDate", "Fecha de contratación", True, ["contratacion", "contratación", "hire", "hiredate", "fecha_ingreso", "fecha contratación", "ingreso"]),
    ("*contractType", "Tipo de contrato", True, ["contrato", "contract", "contracttype", "tipo_contrato", "tipo contrato"]),
    ("probationEndDate", "Fin período de prueba", False, ["prueba", "probation", "probationenddate", "fin_prueba"]),
    ("reportsTo", "Supervisor directo", False, ["supervisor", "reportsto", "jefe", "reporta"]),
    ("paymentFrequency", "Frecuencia de pago", False, ["frecuencia", "frequency", "paymentfrequency", "pago_frecuencia"]),
    ("*salary", "Valor salario", True, ["salario", "salary", "sueldo", "salario_base"]),
    ("*workday", "Jornada", True, ["jornada", "workday", "jornada_laboral", "tipo_jornada"]),
    ("isVigilante", "¿Trabaja como vigilante?", False, ["vigilante", "isvigilante", "vigilancia"]),
    ("weeklyHours", "Horas semanales", False, ["horas", "weeklyhours", "horas_semanales", "semanales"]),
    ("workShift", "Turno de trabajo", False, ["turno", "workshift", "turno_trabajo"]),
    ("occupationCode", "Código ocupación (CNO-2019)", False, ["ocupacion", "ocupación", "occupation", "occupationcode", "cno"]),
    ("vacationGranted", "Concesión de vacaciones", False, ["vacaciones", "vacation", "vacationgranted"]),
    ("*tssKey", "TSS Clave nómina", True, ["tss", "tsskey", "clave", "clave_nomina", "clave_tss"]),
    ("*position", "Cargo", True, ["cargo", "position", "puesto", "posicion"]),
    ("department_catalog", "Departamento", False, ["departamento", "department", "depto"]),
    ("*area", "Área", True, ["area", "área", "area_trabajo"]),
    ("costCenter", "Centro de costo", False, ["costo", "costcenter", "centro_costo", "cc"]),
    ("*paymentMethod", "Método de pago", True, ["metodo", "metodo_pago", "paymentmethod", "método", "forma_pago"]),
    ("*accountNumber", "Número de cuenta", True, ["cuenta", "account", "accountnumber", "numero_cuenta", "num_cuenta"]),
    ("*bank", "Banco", True, ["banco", "bank", "entidad", "entidad_bancaria"]),
    ("*accountType", "Tipo de cuenta", True, ["tipo_cuenta", "accounttype", "tipo"]),
]

EMPLOYEE_REQUIRED_FIELDS = [f[0].lstrip("*") for f in EMPLOYEE_CSV_FIELDS if f[2]]
EMPLOYEE_TARGET_FIELDS = [
    {"id": f[0].lstrip("*"), "name": f"{f[1]}{' *' if f[2] else ''}", "required": f[2], "suggestions": f[3]}
    for f in EMPLOYEE_CSV_FIELDS
]

EMPLOYEE_CSV_HEADERS = [f[0] for f in EMPLOYEE_CSV_FIELDS]
EMPLOYEE_EXAMPLE_ROW = [
    "Juan", "Carlos", "Pérez", "Gómez",
    "cedula", "40212345678", "juan.perez@example.com", "8095551234",
    "Santo Domingo Este", "Calle Primera #45, Los Prados", "masculino", "1990-05-15",
    "S", "4", "María Pérez", "8095555678",
    "AFP Popular", "Empleado ejemplar con buen desempeño.", "2024-01-15", "tiempo_indefinido",
    "2024-04-15", "", "quincenal", "35000",
    "completa", "no", "44", "1",
    "2411", "1", "001", "Analista de Sistemas",
    "Tecnología", "Tecnología", "CC-TEC-01", "transferencia",
    "00123456789", "Banco Popular Dominicano", "ahorro",
]


def _get_delimiter(first_line):
    for delimiter in [';', '\t', ',']:
        if delimiter in first_line:
            return delimiter
    return ','


def _strip_asterisk(h):
    return h[1:] if h.startswith('*') else h


def _sanitize_float_import(val, default=0.0):
    if not val:
        return default
    try:
        val_clean = str(val).strip().replace('RD$', '').replace('$', '').replace(' ', '')
        if ',' in val_clean and '.' in val_clean:
            val_clean = val_clean.replace(',', '')
        elif ',' in val_clean:
            val_clean = val_clean.replace(',', '.')
        return float(val_clean)
    except Exception:
        return default


@web_rrhh_bp.route("/rrhh/employees/import")
def employee_import():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/employee_import.html", active_page="rrhh_employees",
                           target_fields=EMPLOYEE_TARGET_FIELDS,
                           required_fields=EMPLOYEE_REQUIRED_FIELDS)


@web_rrhh_bp.route("/rrhh/employees/import/template")
def employee_import_template():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(EMPLOYEE_CSV_HEADERS)
    writer.writerow(EMPLOYEE_EXAMPLE_ROW)
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name="plantilla_empleados.csv")


@web_rrhh_bp.route("/rrhh/employees/import/upload", methods=["POST"])
def employee_import_upload():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    import_type = request.form.get("import_type", "employees")
    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "Por favor sube un archivo CSV válido."}), 400

    from app.utils.security import validate_uploaded_file, sanitize_filename

    valid, err_msg = validate_uploaded_file(file, allowed_extensions={'csv'})
    if not valid:
        return jsonify({"success": False, "error": err_msg}), 400

    os.makedirs(TEMP_IMPORT_DIR, exist_ok=True)
    safe_name = sanitize_filename(file.filename)
    file_id = f"temp_emp_{session['user']['uid']}_{uuid.uuid4().hex}_{safe_name}"
    temp_path = os.path.join(TEMP_IMPORT_DIR, file_id)
    file.save(temp_path)

    try:
        with open(temp_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            first_line = f.readline()
            delimiter = _get_delimiter(first_line)
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            headers = next(reader, None)
            if not headers:
                raise ValueError("El archivo CSV está vacío.")
            headers = [h.strip() for h in headers]
            data_rows = list(reader)
            row_count = len(data_rows)
            preview_rows = []
            for row in data_rows[:5]:
                if row:
                    preview_rows.append([cell.strip() for cell in row])
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "error": f"Error al analizar el archivo: {html.escape(str(e))}"}), 400

    if row_count == 0:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "error": "El archivo CSV no contiene filas de datos. Solo se encontró la cabecera."}), 400

    return jsonify({
        "success": True,
        "headers": headers,
        "preview_rows": preview_rows,
        "temp_filename": file_id,
        "row_count": row_count,
        "delimiter": delimiter,
        "target_fields": EMPLOYEE_TARGET_FIELDS,
    })


@web_rrhh_bp.route("/rrhh/employees/import/process", methods=["POST"])
def employee_import_process():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    temp_filename = request.form.get("temp_filename")
    if not temp_filename:
        return jsonify({"success": False, "error": "Información de importación incompleta."}), 400

    temp_path = os.path.join(TEMP_IMPORT_DIR, temp_filename)
    if not os.path.exists(temp_path):
        return jsonify({"success": False, "error": "El archivo temporal ya no existe. Intenta subirlo de nuevo."}), 400

    mapping = {}
    for key, value in request.form.items():
        if key.startswith("map_") and value:
            field_id = key.replace("map_", "")
            try:
                mapping[field_id] = int(value)
            except ValueError:
                pass

    os.makedirs(JOB_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    job_file = os.path.join(JOB_DIR, f"{job_id}.json")

    def _write_job(state):
        with open(job_file, 'w') as jf:
            json.dump(state, jf, default=str)

    try:
        with open(temp_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            first_line = f.readline()
            delimiter = _get_delimiter(first_line)
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            next(reader, None)
            rows = list(reader)
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al leer el archivo: {html.escape(str(e))}"}), 500

    total = len([r for r in rows if r])
    if total == 0:
        return jsonify({"success": False, "error": "No hay filas de datos para procesar."}), 400

    state = {
        "job_id": job_id, "status": "processing", "total": total,
        "processed": 0, "imported": 0, "skipped": 0, "errors": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write_job(state)

    from app.services import hr_data_service as hr
    from app.services.payroll_audit_service import log_action

    existing_candidates = hr.get_employees(owner_uid, sandbox=sandbox)
    existing_cedulas = set()
    for e in existing_candidates:
        c = (e.get("cedula") or e.get("idNumber") or "").strip()
        if c:
            existing_cedulas.add(c)

    field_defaults = {}
    for key, value in request.form.items():
        if key.startswith("default_") and value.strip():
            field_defaults[key.replace("default_", "")] = value.strip()

    def _get_val(row_data, field_id, default=""):
        if field_id in mapping and len(row_data) > mapping[field_id]:
            val = row_data[mapping[field_id]].strip()
            if val:
                return val
        return field_defaults.get(field_id, default)

    def process_rows():
        imported = 0
        skipped = 0
        errors = []
        processed = 0
        update_every = max(1, total // 20)

        for row_idx, row_data in enumerate(rows):
            if not row_data:
                continue
            processed += 1
            row_num = row_idx + 2

            try:
                first_name = _get_val(row_data, "firstName")
                first_last_name = _get_val(row_data, "firstLastName")
                id_number = re.sub(r'\D', '', _get_val(row_data, "idNumber"))
                email = _get_val(row_data, "email")
                municipality = _get_val(row_data, "municipality")
                address = _get_val(row_data, "address")
                hire_date = _get_val(row_data, "hireDate")
                contract_type = _get_val(row_data, "contractType")
                salary = _sanitize_float_import(_get_val(row_data, "salary"))
                workday = _get_val(row_data, "workday", "completa")
                tss_key = _get_val(row_data, "tssKey")
                position = _get_val(row_data, "position")
                area = _get_val(row_data, "area")
                payment_method = _get_val(row_data, "paymentMethod")
                account_number = _get_val(row_data, "accountNumber")
                bank = _get_val(row_data, "bank")
                account_type = _get_val(row_data, "accountType")

                if not first_name:
                    errors.append({"row": row_num, "reason": "Falta primer nombre (firstName)"})
                    skipped += 1
                    continue
                if not first_last_name:
                    errors.append({"row": row_num, "reason": "Falta primer apellido (firstLastName)"})
                    skipped += 1
                    continue
                if not id_number:
                    errors.append({"row": row_num, "reason": "Falta número de identificación (idNumber)"})
                    skipped += 1
                    continue
                if not email:
                    errors.append({"row": row_num, "reason": "Falta correo electrónico (email)"})
                    skipped += 1
                    continue
                if not municipality:
                    errors.append({"row": row_num, "reason": "Falta municipio (municipality)"})
                    skipped += 1
                    continue
                if not address:
                    errors.append({"row": row_num, "reason": "Falta dirección (address)"})
                    skipped += 1
                    continue
                if not hire_date:
                    errors.append({"row": row_num, "reason": "Falta fecha de contratación (hireDate)"})
                    skipped += 1
                    continue
                try:
                    datetime.strptime(hire_date, "%Y-%m-%d")
                except ValueError:
                    errors.append({"row": row_num, "reason": f"Fecha de contratación inválida: '{hire_date}'. Use YYYY-MM-DD."})
                    skipped += 1
                    continue
                if not contract_type:
                    errors.append({"row": row_num, "reason": "Falta tipo de contrato (contractType)"})
                    skipped += 1
                    continue
                if salary <= 0:
                    errors.append({"row": row_num, "reason": "Salario inválido o faltante (salary)"})
                    skipped += 1
                    continue
                if not workday:
                    errors.append({"row": row_num, "reason": "Falta jornada (workday)"})
                    skipped += 1
                    continue
                if not tss_key or not re.match(r'^\d{3}$', tss_key):
                    errors.append({"row": row_num, "reason": "Falta o es inválida la clave TSS (tssKey). Debe ser 3 dígitos."})
                    skipped += 1
                    continue
                if not position:
                    errors.append({"row": row_num, "reason": "Falta cargo (position)"})
                    skipped += 1
                    continue
                if not area:
                    errors.append({"row": row_num, "reason": "Falta área (area)"})
                    skipped += 1
                    continue
                if not payment_method:
                    errors.append({"row": row_num, "reason": "Falta método de pago (paymentMethod)"})
                    skipped += 1
                    continue
                if not account_number:
                    errors.append({"row": row_num, "reason": "Falta número de cuenta (accountNumber)"})
                    skipped += 1
                    continue
                if not bank:
                    errors.append({"row": row_num, "reason": "Falta banco (bank)"})
                    skipped += 1
                    continue
                if not account_type:
                    errors.append({"row": row_num, "reason": "Falta tipo de cuenta (accountType)"})
                    skipped += 1
                    continue

                if id_number in existing_cedulas:
                    errors.append({"row": row_num, "reason": f"La cédula {id_number} ya está registrada en el sistema."})
                    skipped += 1
                    continue

                middle_name = _get_val(row_data, "middleName")
                second_last_name = _get_val(row_data, "secondLastName")

                emp_id = str(uuid.uuid4())
                data = {
                    "id": emp_id,
                    "idType": _get_val(row_data, "idType", "cedula"),
                    "idNumber": id_number,
                    "cedula": id_number,
                    "firstName": first_name,
                    "middleName": middle_name,
                    "lastName": first_last_name,
                    "firstLastName": first_last_name,
                    "secondLastName": second_last_name,
                    "fullName": " ".join(p for p in [first_name, middle_name, first_last_name, second_last_name] if p),
                    "position": position,
                    "area": area,
                    "costCenter": _get_val(row_data, "costCenter", area),
                    "department": area,
                    "branchId": "",
                    "hireDate": hire_date,
                    "salary": salary,
                    "baseSalary": salary,
                    "salaryType": "fijo",
                    "status": "activo",
                    "email": email,
                    "phone": re.sub(r'\D', '', _get_val(row_data, "phone")),
                    "address": address,
                    "municipality": municipality,
                    "contractType": contract_type,
                    "paymentFrequency": _get_val(row_data, "paymentFrequency"),
                    "workday": workday,
                    "isVigilante": _get_val(row_data, "isVigilante").lower() == "si",
                    "tssKey": tss_key,
                    "paymentMethod": payment_method,
                    "accountNumber": account_number,
                    "bank": bank,
                    "accountType": account_type,
                    "emergencyContact": _get_val(row_data, "emergencyContact"),
                    "emergencyPhone": re.sub(r'\D', '', _get_val(row_data, "emergencyPhone")),
                    "afpProvider": _get_val(row_data, "afpProvider"),
                    "notes": _get_val(row_data, "notes") or "Importado masivamente desde CSV.",
                    "gender": _get_val(row_data, "gender"),
                    "birthDate": _get_val(row_data, "birthDate"),
                    "probationEndDate": _get_val(row_data, "probationEndDate"),
                    "reportsTo": _get_val(row_data, "reportsTo"),
                    "maritalStatus": _get_val(row_data, "maritalStatus"),
                    "occupationCode": _get_val(row_data, "occupationCode"),
                    "weeklyHours": int(_get_val(row_data, "weeklyHours", "44") or 44),
                    "workShift": int(_get_val(row_data, "workShift", "1") or 1),
                    "educationLevel": int(_get_val(row_data, "educationLevel", "0") or 0),
                    "vacationGranted": int(_get_val(row_data, "vacationGranted", "1") or 1),
                    "nationality": 1,
                }

                hr.save_employee(owner_uid, emp_id, data, sandbox=sandbox)

                if salary > 0:
                    history_id = str(uuid.uuid4())
                    hr.save_salary_history_entry(owner_uid, {
                        "id": history_id,
                        "employeeId": emp_id,
                        "amount": salary,
                        "previousAmount": 0.0,
                        "effectiveDate": hire_date,
                        "endDate": "",
                        "reason": "Salario inicial (importación masiva)",
                        "approvedBy": user_email,
                        "createdAt": date.today().isoformat(),
                    }, sandbox=sandbox)

                log_action(owner_uid, "create", "employee", emp_id, user_email,
                           changes={"name": data["fullName"], "salary": salary, "source": "csv_import"},
                           sandbox=sandbox)

                existing_cedulas.add(id_number)
                imported += 1

            except Exception as e:
                errors.append({"row": row_num, "reason": f"Error inesperado: {html.escape(str(e))}"})
                skipped += 1

            if processed % update_every == 0 or processed == total:
                current_state = {
                    "job_id": job_id, "status": "processing", "total": total,
                    "processed": processed, "imported": imported, "skipped": skipped,
                    "errors": errors[-30:],
                }
                _write_job(current_state)

        final_state = {
            "job_id": job_id, "status": "completed", "total": total,
            "processed": processed, "imported": imported, "skipped": skipped,
            "errors": errors,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _write_job(final_state)

    thread = threading.Thread(target=process_rows)
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "job_id": job_id, "total": total})


@web_rrhh_bp.route("/rrhh/employees/import/status/<job_id>")
def employee_import_status(job_id):
    if _login_required():
        return jsonify({"status": "not_found", "error": "No autorizado"}), 401
    job_file = os.path.join(JOB_DIR, job_id + ".json")
    if os.path.exists(job_file):
        try:
            with open(job_file, 'r') as jf:
                state = json.load(jf)
            return jsonify(state)
        except Exception:
            return jsonify({"status": "not_found", "error": "Error al leer el estado del job"}), 500
    return jsonify({"status": "not_found", "error": "Job no encontrado"}), 404


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/salary-history")
def employee_salary_history(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    history = hr.get_salary_history(owner_uid, employee_id, sandbox=sandbox)
    from app.services.payroll_static_data import PAYROLL_FREQUENCIES
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    frequency = config.get("payroll", {}).get("frequency", "mensual")
    try:
        now = date.today()
        payroll_periods = _generate_periods(frequency, now.year)
        if now.month < 12:
            payroll_periods += _generate_periods(frequency, now.year + 1)
    except Exception:
        payroll_periods = []
    return render_template("rrhh/employee_salary_history.html", active_page="rrhh_employees",
                           employee=employee, history=history, frequencies=PAYROLL_FREQUENCIES,
                           today=date.today().isoformat(),
                           payroll_periods=payroll_periods, effective_date=employee.get("effectiveDate", ""))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/salary/add", methods=["POST"])
def employee_salary_add(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    new_amount = float(request.form.get("amount", 0) or 0)
    eff_date = request.form.get("effective_date", date.today().isoformat()).strip()
    reason = request.form.get("reason", "Ajuste salarial").strip()
    payroll_period_key = request.form.get("payrollPeriodKey", "").strip()

    if new_amount <= 0:
        flash("El salario debe ser mayor a 0.", "error")
        return redirect(url_for("web_rrhh.employee_salary_history", employee_id=employee_id))

    # Auto-detectar período si no se especificó
    if not payroll_period_key and eff_date:
        config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
        frequency = config.get("payroll", {}).get("frequency", "mensual")
        try:
            import calendar
            year = eff_date[:4]
            for p in _generate_periods(frequency, int(year)):
                if p["start"] <= eff_date <= p["end"]:
                    payroll_period_key = p["key"]
                    break
        except Exception:
            pass

    old_amount = float(employee.get("baseSalary", 0))
    # Cerrar salario anterior
    hr.close_previous_salary(owner_uid, employee_id, eff_date, sandbox=sandbox)
    # Crear nueva entrada
    history_id = str(uuid.uuid4())
    hr.save_salary_history_entry(owner_uid, {
        "id": history_id, "employeeId": employee_id,
        "amount": new_amount, "previousAmount": old_amount,
        "effectiveDate": eff_date, "endDate": "",
        "reason": reason,
        "approvedBy": session.get("user", {}).get("email", ""),
        "createdAt": date.today().isoformat(),
        "payrollPeriodKey": payroll_period_key,
    }, sandbox=sandbox)
    # Actualizar el salario del empleado
    employee["baseSalary"] = new_amount
    employee["salary"] = new_amount
    hr.save_employee(owner_uid, employee_id, employee, sandbox=sandbox)

    flash(f"Salario actualizado a RD$ {new_amount:,.2f} con vigencia {eff_date}.", "success")
    return redirect(url_for("web_rrhh.employee_salary_history", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/upload", methods=["POST"])
def employee_document_upload(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    category = request.form.get("category", "other")
    notes = request.form.get("notes", "").strip()
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debes seleccionar un archivo.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    import os, base64
    content = base64.b64encode(file.read()).decode("utf-8")
    max_size = 10 * 1024 * 1024
    if len(content) > max_size * 1.4:
        flash("El archivo excede el tamaño máximo de 10MB.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    doc_id = str(uuid.uuid4())
    hr.save_employee_document(owner_uid, {
        "id": doc_id,
        "employeeId": employee_id,
        "name": file.filename,
        "category": category,
        "notes": notes,
        "size": len(content),
        "contentType": file.content_type or "application/octet-stream",
        "data": content,
        "uploadedBy": session.get("user", {}).get("email", ""),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
    }, sandbox=sandbox)

    flash("Documento subido exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/<doc_id>/download")
def employee_document_download(employee_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        return "", 404

    docs = hr.get_employee_documents(owner_uid, employee_id, sandbox=sandbox)
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if not doc or not doc.get("data"):
        return "", 404

    import base64, io as _io
    content = base64.b64decode(doc["data"])
    return send_file(_io.BytesIO(content), mimetype=doc.get("contentType", "application/octet-stream"),
                     as_attachment=True, download_name=doc.get("name", "documento"))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/<doc_id>/delete", methods=["POST"])
def employee_document_delete(employee_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    hr.delete_employee_document(owner_uid, doc_id, sandbox=sandbox)
    flash("Documento eliminado.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/checklist/<checklist_type>")
def employee_checklist(employee_id, checklist_type):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))
    items = hr.get_checklist(owner_uid, employee_id, checklist_type, sandbox=sandbox)
    done = sum(1 for i in items if i.get("completed"))
    total = len(items)
    pct = int(done / total * 100) if total else 0
    titles = {"onboarding": "Onboarding", "offboarding": "Offboarding"}
    return render_template("rrhh/checklist.html", active_page="rrhh_employees",
                           employee=employee, items=items, checklist_type=checklist_type,
                           title=titles.get(checklist_type, checklist_type),
                           done=done, total=total, pct=pct)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/checklist/<checklist_type>/toggle/<item_id>", methods=["POST"])
def employee_checklist_toggle(employee_id, checklist_type, item_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    completed = request.form.get("completed") == "1"
    hr.toggle_checklist_item(owner_uid, employee_id, checklist_type, item_id, completed,
                             session.get("user", {}).get("email", ""), sandbox=sandbox)
    return redirect(url_for("web_rrhh.employee_checklist", employee_id=employee_id, checklist_type=checklist_type))


@web_rrhh_bp.route("/rrhh/org-chart")
def org_chart():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]
    emp_map = {e["id"]: e for e in employees}

    for e in employees:
        e["direct_reports"] = []

    for e in employees:
        supervisor_id = e.get("reportsTo", "")
        if supervisor_id and supervisor_id in emp_map:
            emp_map[supervisor_id]["direct_reports"].append(e)

    root_nodes = [e for e in employees if not e.get("reportsTo") or e.get("reportsTo") not in emp_map]
    flat_employees = []

    return render_template("rrhh/org_chart.html", active_page="rrhh_employees",
                           root_nodes=root_nodes, flat_employees=flat_employees,
                           emp_map=emp_map)


@web_rrhh_bp.route("/rrhh/calendar")
def team_calendar():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    try:
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))
    except (ValueError, TypeError):
        year, month = date.today().year, date.today().month

    vacations = hr.get_vacation_requests(owner_uid, sandbox=sandbox)
    leaves = hr.get_leave_requests(owner_uid, sandbox=sandbox)
    employees = {e["id"]: e for e in hr.get_employees(owner_uid, sandbox=sandbox)}

    events = []
    for v in vacations:
        if v.get("status") == "aprobada":
            events.append({"type": "vacation", "employeeName": v.get("employeeName", ""),
                          "employeeId": v.get("employeeId", ""),
                          "start": v.get("startDate", ""), "end": v.get("endDate", ""),
                          "days": v.get("days", 0)})
    for l in leaves:
        if l.get("status") == "aprobada":
            events.append({"type": "leave", "employeeName": l.get("employeeName", ""),
                          "employeeId": l.get("employeeId", ""),
                          "start": l.get("startDate", ""), "end": l.get("endDate", ""),
                          "days": l.get("days", 0), "leaveType": l.get("leaveType", "")})

    return render_template("rrhh/team_calendar.html", active_page="rrhh_employees",
                           events=events, year=year, month=month,
                           months_es=MONTHS_ES, employees=employees,
                           num_days=calendar.monthrange(year, month)[1])


# ═══════════════════════════════════════════════════════════════════════════
# ASISTENCIA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/attendance", methods=["GET", "POST"])
def attendance():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    now = datetime.now(timezone.utc)
    try:
        sel_month = int(request.args.get("month", now.month))
        sel_year = int(request.args.get("year", now.year))
    except ValueError:
        sel_month, sel_year = now.month, now.year

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]
    records = hr.get_attendance_records(owner_uid, sandbox=sandbox)

    if request.method == "POST":
        for emp in employees:
            emp_id = emp["id"]
            status = request.form.get(f"att_{emp_id}", "")
            check_in = request.form.get(f"checkin_{emp_id}", "")
            check_out = request.form.get(f"checkout_{emp_id}", "")
            att_date = request.form.get("att_date", now.strftime("%Y-%m-%d"))
            if status:
                rec_id = str(uuid.uuid4())
                hr.save_attendance_record(owner_uid, rec_id, {
                    "id": rec_id,
                    "employeeId": emp_id,
                    "employeeName": emp.get("fullName", ""),
                    "date": att_date,
                    "checkIn": check_in,
                    "checkOut": check_out,
                    "status": status,
                    "notes": "",
                }, sandbox=sandbox)
        flash("Asistencia registrada.", "success")
        return redirect(url_for("web_rrhh.attendance", month=sel_month, year=sel_year))

    month_records = [r for r in records if r.get("date", "").startswith(f"{sel_year}-{sel_month:02d}")]
    by_date = {}
    for r in month_records:
        d = r.get("date", "")
        if d not in by_date:
            by_date[d] = {}
        by_date[d][r.get("employeeId", "")] = r

    num_days = calendar.monthrange(sel_year, sel_month)[1]
    days_list = [f"{sel_year}-{sel_month:02d}-{d:02d}" for d in range(1, num_days + 1)]

    return render_template("rrhh/attendance.html", active_page="rrhh_attendance",
                           employees=employees, by_date=by_date, days_list=days_list,
                           sel_month=sel_month, sel_year=sel_year)


# ═══════════════════════════════════════════════════════════════════════════
# VACACIONES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/vacations")
def vacation_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    requests = hr.get_vacation_requests(owner_uid, sandbox=sandbox)
    requests.sort(key=lambda r: r.get("createdDate", ""), reverse=True)
    return render_template("rrhh/vacation_list.html", active_page="rrhh_attendance", requests=requests)


@web_rrhh_bp.route("/rrhh/vacations/new", methods=["GET", "POST"])
def vacation_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
        if not employee:
            flash("Empleado no encontrado.", "error")
            return redirect(url_for("web_rrhh.vacation_list"))

        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        business_days = PayrollService.calculate_business_days(start_date, end_date)
        remaining = PayrollService.calculate_vacation_days(employee.get("hireDate", ""))

        req_id = str(uuid.uuid4())
        hr.save_vacation_request(owner_uid, req_id, {
            "id": req_id,
            "employeeId": emp_id,
            "employeeName": employee.get("fullName", ""),
            "startDate": start_date,
            "endDate": end_date,
            "days": business_days,
            "status": "pendiente",
            "remainingDaysBefore": remaining,
            "notes": request.form.get("notes", "").strip(),
            "createdDate": date.today().isoformat(),
        }, sandbox=sandbox)
        flash(f"Solicitud de vacaciones por {business_days} días creada.", "success")
        return redirect(url_for("web_rrhh.vacation_list"))

    return render_template("rrhh/vacation_form.html", active_page="rrhh_attendance", employees=employees)


@web_rrhh_bp.route("/rrhh/vacations/<request_id>/<action>", methods=["POST"])
def vacation_action(request_id, action):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    req = hr.get_vacation_request(owner_uid, request_id, sandbox=sandbox)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.vacation_list"))

    if action in ("approve", "rechazar"):
        req["status"] = "aprobada" if action == "approve" else "rechazada"
        req["approvedDate"] = date.today().isoformat()
        req["approvedBy"] = session["user"].get("email", "")
        hr.save_vacation_request(owner_uid, request_id, req, sandbox=sandbox)

        # Notificar al empleado si se aprobó
        if action == "approve":
            try:
                employee = hr.get_employee(owner_uid, req.get("employeeId", ""), sandbox=sandbox)
                if employee:
                    from app.services.hr_notifications import notify_vacation_approved
                    notify_vacation_approved(employee, req)
            except Exception:
                pass

        flash(f"Solicitud {'aprobada' if action == 'approve' else 'rechazada'}.", "success")

    return redirect(url_for("web_rrhh.vacation_list"))


# ═══════════════════════════════════════════════════════════════════════════
# PERMISOS / LICENCIAS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/leaves")
def leave_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    requests = hr.get_leave_requests(owner_uid, sandbox=sandbox)
    requests.sort(key=lambda r: r.get("startDate", ""), reverse=True)
    return render_template("rrhh/leave_list.html", active_page="rrhh_attendance", requests=requests)


@web_rrhh_bp.route("/rrhh/leaves/new", methods=["GET", "POST"])
def leave_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
        if not employee:
            flash("Empleado no encontrado.", "error")
            return redirect(url_for("web_rrhh.leave_list"))

        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days + 1

        req_id = str(uuid.uuid4())
        hr.save_leave_request(owner_uid, req_id, {
            "id": req_id,
            "employeeId": emp_id,
            "employeeName": employee.get("fullName", ""),
            "leaveType": request.form.get("leaveType", "otro"),
            "startDate": start_date,
            "endDate": end_date,
            "days": days,
            "status": "pendiente",
            "notes": request.form.get("notes", "").strip(),
        }, sandbox=sandbox)
        flash("Permiso registrado.", "success")
        return redirect(url_for("web_rrhh.leave_list"))

    return render_template("rrhh/leave_form.html", active_page="rrhh_attendance", employees=employees)


@web_rrhh_bp.route("/rrhh/leaves/<request_id>/<action>", methods=["POST"])
def leave_action(request_id, action):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    req = hr.get_leave_request(owner_uid, request_id, sandbox=sandbox)
    if not req:
        flash("Permiso no encontrado.", "error")
        return redirect(url_for("web_rrhh.leave_list"))

    if action in ("approve", "rechazar"):
        req["status"] = "aprobada" if action == "approve" else "rechazada"
        req["approvedBy"] = session["user"].get("email", "")
        hr.save_leave_request(owner_uid, request_id, req, sandbox=sandbox)

        if action == "approve":
            try:
                employee = hr.get_employee(owner_uid, req.get("employeeId", ""), sandbox=sandbox)
                if employee:
                    from app.services.hr_notifications import notify_leave_approved
                    notify_leave_approved(employee, req)
            except Exception:
                pass

        flash(f"Permiso {'aprobado' if action == 'approve' else 'rechazado'}.", "success")

    return redirect(url_for("web_rrhh.leave_list"))


# ═══════════════════════════════════════════════════════════════════════════
# NÓMINA — Procesar
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/new", methods=["GET", "POST"])
def payroll_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    from app.services.payroll_ytd_service import get_ytd, save_ytd, accumulate_ytd
    from app.services.payroll_static_data import DEFAULT_PAYROLL_CONFIG

    # Verificar onboarding
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    if not config.get("onboardingCompleted"):
        return redirect(url_for("web_rrhh.onboarding_guide"))

    all_employees = hr.get_employees(owner_uid, sandbox=sandbox)
    active_employees = [e for e in all_employees if e.get("status") == "activo"]

    # ── Grupos de nómina ──
    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    # Seleccionar grupo (desde query param o form, default = "" para comportamiento legacy)
    selected_group_id = request.args.get("group", "") or request.form.get("payrollGroupId", "")

    # Determinar frecuencia según grupo o config global
    if selected_group_id:
        selected_group = next((g for g in payroll_groups if g["id"] == selected_group_id), None)
        group_frequency = selected_group["frequency"] if selected_group else config.get("payrollFrequency", "mensual")
    else:
        selected_group = None
        group_frequency = config.get("payrollFrequency", "mensual")

    # Filtrar empleados por grupo
    if selected_group_id:
        employees = [e for e in active_employees if selected_group_id in e.get("payrollGroupIds", [])]
        if not employees:
            flash(f"No hay empleados activos asignados al grupo «{selected_group.get('name', '')}».", "warning")
    else:
        employees = active_employees

    now = date.today()
    available_periods = _generate_periods(group_frequency, now.year)

    if request.method == "POST":
        period_key = request.form.get("period_key", "")
        if not period_key:
            flash("Debes seleccionar un período.", "error")
            return redirect(url_for("web_rrhh.payroll_new"))

        # ── Anti-duplicados: verificar si ya existe nómina para este período (mismo grupo) ──
        if selected_group_id:
            existing = hr.get_payroll_period_by_key_and_group(owner_uid, period_key, selected_group_id, sandbox=sandbox)
            if existing:
                flash(f"Ya existe una nómina para el período «{period_key}» en el grupo «{selected_group.get('name', '')}». Puedes verla o recalcularla.", "warning")
                return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                                       employees=employees, now=datetime.now,
                                       available_periods=available_periods, frequency=group_frequency,
                                       show_christmas_bonus=(now.month >= 11),
                                       payroll_groups=payroll_groups,
                                       selected_group_id=selected_group_id,
                                       existing_period=existing)
        else:
            existing = hr.get_payroll_period_by_key(owner_uid, period_key, sandbox=sandbox)
            if existing:
                flash(f"Ya existe una nómina para el período «{period_key}». Puedes verla o recalcularla.", "warning")
                return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                                       employees=employees, now=datetime.now,
                                       available_periods=available_periods, frequency=group_frequency,
                                       show_christmas_bonus=(now.month >= 11),
                                       payroll_groups=payroll_groups,
                                       selected_group_id=selected_group_id,
                                       existing_period=existing)

        # Parse period key
        parts = period_key.split("-")
        year = int(parts[0])
        month = int(parts[1])

        # Get period metadata
        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        period_range = period_info["label"] if period_info else ""
        start_date = period_info["start"] if period_info else ""
        end_date = period_info["end"] if period_info else ""

        # Determinar tipo: desde metadata o por sufijo (-M = mensual, -1/-2 = quincenal)
        period_type = period_info.get("type", "mensual") if period_info else ("quincenal" if len(parts) == 3 and parts[2] != "M" else "mensual")

        # ── Filtrar empleados según frecuencia del período ──
        period_employees, excluded = _filter_employees_by_period(employees, period_key)

        period_id = str(uuid.uuid4())
        lines = []

        # ── Cargar tasas configurables desde Firestore ──
        tax_rates_data = hr.get_tax_rates(owner_uid, sandbox=sandbox)

        total_gross = 0.0
        total_net = 0.0
        total_employer = 0.0

        for emp in period_employees:
            emp_id = emp["id"]
            base = float(emp.get("baseSalary", 0))
            overtime = float(request.form.get(f"overtime_{emp_id}", 0) or 0)
            commission = float(request.form.get(f"commission_{emp_id}", 0) or 0)
            bonus = float(request.form.get(f"bonus_{emp_id}", 0) or 0)
            other_income = float(request.form.get(f"other_income_{emp_id}", 0) or 0)
            other_ded = float(request.form.get(f"other_ded_{emp_id}", 0) or 0)

            # ── Frecuencia de pago: se deriva del grupo/período ──
            emp_period_type = period_type
            emp_is_quincenal = emp_period_type == "quincenal"

            # ── Regalía pascual ──
            if request.form.get("include_christmas_bonus") == "1":
                months_worked = emp.get("hireDate") and max(1, (date.today().month - int(emp["hireDate"][5:7]) + 1)) or 12
                if months_worked > 12:
                    months_worked = 12
                christmas = PayrollService.calculate_christmas_bonus(base, months_worked)
                bonus += christmas

            # ── Prorrateo: entrada/salida/cambio a mitad de período ──
            salary_history = hr.get_salary_history(owner_uid, emp_id, sandbox=sandbox)
            prorated = PayrollService.prorate_salary(
                monthly_salary=base,
                period_start=start_date,
                period_end=end_date,
                hire_date=emp.get("hireDate", ""),
                termination_date=emp.get("terminationDate", ""),
                salary_history=salary_history,
            )

            calc = PayrollService.calculate_payroll_line(
                base_salary=base,
                overtime_hours=overtime,
                commission=commission,
                bonus=bonus,
                other_income=other_income,
                other_deductions=other_ded,
                period_type=emp_period_type,
                prorated_salary=prorated,
                tax_rates=tax_rates_data,
            )
            line = {
                **calc,
                "employeeId": emp_id,
                "employeeName": emp.get("fullName", ""),
                "cedula": emp.get("cedula", ""),
                "position": emp.get("position", ""),
                "department": emp.get("department", ""),
                "periodType": emp_period_type,
            }
            lines.append(line)
            total_gross += line["totalIncome"]
            total_net += line["netSalary"]
            total_employer += line["totalEmployerContrib"]

            # ── YTD: acumulación anual por empleado ──
            try:
                ytd = get_ytd(owner_uid, emp_id, year, sandbox=sandbox)
                ytd = accumulate_ytd(ytd, line, period_factor=24 if emp_is_quincenal else 12)
                save_ytd(owner_uid, emp_id, year, ytd, sandbox=sandbox)
            except Exception as e:
                print(f"⚠️ YTD accumulation error for employee {emp_id}: {e}")

        period_data = {
            "id": period_id,
            "periodKey": period_key,
            "periodType": period_type,
            "periodRange": period_range,
            "startDate": start_date,
            "endDate": end_date,
            "month": month,
            "year": year,
            "payrollGroupId": selected_group_id,
            "status": "calculada",
            "lines": lines,
            "totalGross": round(total_gross, 2),
            "totalNet": round(total_net, 2),
            "totalEmployerContrib": round(total_employer, 2),
            "processedDate": now.isoformat(),
            "notes": request.form.get("notes", "").strip(),
            "calculatedBy": session.get("user", {}).get("email", ""),
            "calculatedAt": now.isoformat(),
            "statusHistory": [{
                "from": "borrador",
                "to": "calculada",
                "by": session.get("user", {}).get("email", ""),
                "at": now.isoformat(),
                "comment": "Nómina calculada",
            }],
        }
        hr.save_payroll_period(owner_uid, period_id, period_data, sandbox=sandbox)

        from app.services.payroll_audit_service import log_action
        log_action(owner_uid, "calculate", "payroll_period", period_id,
                   session.get("user", {}).get("email", ""),
                   changes={"period": period_key, "employees": len(lines), "total_net": round(total_net, 2)}, sandbox=sandbox)

        flash(f"Nómina {period_range or period_key} calculada: {len(lines)} empleados, neto RD$ {total_net:,.2f}.", "success")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                           employees=employees, now=datetime.now,
                           available_periods=available_periods, frequency=group_frequency,
                           show_christmas_bonus=(now.month >= 11),
                           payroll_groups=payroll_groups,
                           selected_group_id=selected_group_id)


# ═══════════════════════════════════════════════════════════════════════════
# SIMULADOR DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/simulate", methods=["GET", "POST"])
def payroll_simulate():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    if not config.get("onboardingCompleted"):
        return redirect(url_for("web_rrhh.payroll_setup"))

    all_active = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]

    # ── Grupos de nómina ──
    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    selected_group_id = request.args.get("group", "") or request.form.get("payrollGroupId", "")

    if selected_group_id:
        selected_group = next((g for g in payroll_groups if g["id"] == selected_group_id), None)
        group_frequency = selected_group["frequency"] if selected_group else config.get("payrollFrequency", "mensual")
        employees = [e for e in all_active if selected_group_id in e.get("payrollGroupIds", [])]
    else:
        selected_group = None
        group_frequency = config.get("payrollFrequency", "mensual")
        employees = all_active

    now = date.today()
    available_periods = _generate_periods(group_frequency, now.year)

    simulation = None

    if request.method == "POST":
        period_key = request.form.get("period_key", "")
        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        start_date = period_info["start"] if period_info else ""
        end_date = period_info["end"] if period_info else ""
        period_type = period_info.get("type", "mensual") if period_info else ("quincenal" if len(period_key.split("-")) == 3 and period_key.split("-")[2] != "M" else "mensual")

        # ── Filtrar empleados según frecuencia del período ──
        period_employees, _sim_excluded = _filter_employees_by_period(employees)

        lines = []
        total_gross = 0.0
        total_net = 0.0
        total_employer = 0.0
        total_costo = 0.0

        # ── Cargar tasas configurables desde Firestore ──
        tax_rates_data = hr.get_tax_rates(owner_uid, sandbox=sandbox)

        for emp in period_employees:
            emp_id = emp["id"]
            base = float(emp.get("baseSalary", 0))
            overtime = float(request.form.get(f"overtime_{emp_id}", 0) or 0)
            commission = float(request.form.get(f"commission_{emp_id}", 0) or 0)
            bonus = float(request.form.get(f"bonus_{emp_id}", 0) or 0)
            other_income = float(request.form.get(f"other_income_{emp_id}", 0) or 0)
            other_ded = float(request.form.get(f"other_ded_{emp_id}", 0) or 0)

            # ── Frecuencia de pago: se deriva del grupo/período ──
            emp_period_type = period_type

            salary_history = hr.get_salary_history(owner_uid, emp_id, sandbox=sandbox)
            prorated = PayrollService.prorate_salary(
                monthly_salary=base, period_start=start_date, period_end=end_date,
                hire_date=emp.get("hireDate", ""),
                termination_date=emp.get("terminationDate", ""),
                salary_history=salary_history,
            )

            calc = PayrollService.calculate_payroll_line(
                base_salary=base, overtime_hours=overtime, commission=commission,
                bonus=bonus, other_income=other_income, other_deductions=other_ded,
                period_type=emp_period_type, prorated_salary=prorated,
                tax_rates=tax_rates_data,
            )
            calc["employeeName"] = emp.get("fullName", "")
            calc["employeeId"] = emp_id
            calc["position"] = emp.get("position", "")
            calc["periodType"] = emp_period_type
            lines.append(calc)
            total_gross += calc["totalIncome"]
            total_net += calc["netSalary"]
            total_employer += calc["totalEmployerContrib"]
            total_costo += calc["totalIncome"] + calc["totalEmployerContrib"]

        simulation = {
            "period_range": period_info["label"] if period_info else period_key,
            "period_type": period_type,
            "employee_count": len(period_employees),
            "excluded_count": len(_sim_excluded),
            "total_gross": round(total_gross, 2),
            "total_net": round(total_net, 2),
            "total_employer": round(total_employer, 2),
            "total_costo": round(total_costo, 2),
            "lines": lines,
        }

    return render_template("rrhh/payroll_simulate.html", active_page="rrhh_payroll",
                           employees=employees, available_periods=available_periods,
                           frequency=group_frequency, simulation=simulation,
                           payroll_groups=payroll_groups,
                           selected_group_id=selected_group_id)


# ═══════════════════════════════════════════════════════════════════════════
# GRUPOS DE NÓMINA — CRUD
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/groups")
def payroll_groups_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    groups.sort(key=lambda g: g.get("name", ""))
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    group_employee_counts = {}
    for g in groups:
        gid = g["id"]
        group_employee_counts[gid] = len([e for e in employees if gid in e.get("payrollGroupIds", [])])
    return render_template("rrhh/payroll_groups.html", active_page="rrhh_payroll",
                           groups=groups, group_employee_counts=group_employee_counts)


@web_rrhh_bp.route("/rrhh/payroll/groups/new", methods=["GET", "POST"])
def payroll_groups_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        desc = request.form.get("description", "").strip()
        frequency = request.form.get("frequency", "mensual").strip()
        if not name:
            flash("El nombre del grupo es obligatorio.", "error")
            return render_template("rrhh/payroll_groups_form.html", active_page="rrhh_payroll", group=None)
        from uuid import uuid4
        gid = str(uuid4())
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {
            "id": gid, "name": name, "description": desc,
            "frequency": frequency,
            "isActive": True,
            "createdAt": now_iso, "updatedAt": now_iso,
            "createdBy": session.get("user", {}).get("email", ""),
        }
        hr.save_payroll_group(owner_uid, gid, data, sandbox=sandbox)
        flash(f"Grupo de nómina «{name}» creado.", "success")
        return redirect(url_for("web_rrhh.payroll_groups_list"))
    return render_template("rrhh/payroll_groups_form.html", active_page="rrhh_payroll", group=None)


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/edit", methods=["GET", "POST"])
def payroll_groups_edit(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    if request.method == "POST":
        group["name"] = request.form.get("name", "").strip()
        group["description"] = request.form.get("description", "").strip()
        group["frequency"] = request.form.get("frequency", "mensual").strip()
        group["isActive"] = request.form.get("isActive") == "on"
        group["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        hr.save_payroll_group(owner_uid, group_id, group, sandbox=sandbox)
        flash(f"Grupo «{group['name']}» actualizado.", "success")
        return redirect(url_for("web_rrhh.payroll_groups_list"))
    return render_template("rrhh/payroll_groups_form.html", active_page="rrhh_payroll", group=group)


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/delete", methods=["POST"])
def payroll_groups_delete(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    hr.delete_payroll_group(owner_uid, group_id, sandbox=sandbox)
    flash("Grupo eliminado.", "success")
    return redirect(url_for("web_rrhh.payroll_groups_list"))


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>")
def payroll_groups_view(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    assigned = [e for e in employees if group_id in e.get("payrollGroupIds", [])]
    unassigned = [e for e in employees if group_id not in e.get("payrollGroupIds", []) and e.get("status") == "activo"]

    periods = [p for p in hr.get_payroll_periods(owner_uid, sandbox=sandbox)
               if p.get("payrollGroupId") == group_id]
    periods.sort(key=lambda p: p.get("periodKey", ""), reverse=True)

    return render_template("rrhh/payroll_groups_view.html", active_page="rrhh_payroll",
                           group=group, assigned=assigned, unassigned=unassigned,
                           periods=periods)


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/assign", methods=["POST"])
def payroll_groups_assign(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    employee_ids = request.form.getlist("employee_ids")
    count = 0
    for emp_id in employee_ids:
        emp = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
        if not emp:
            continue
        current = emp.get("payrollGroupIds", [])
        if group_id not in current:
            current = list(current) + [group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, emp_id, emp, sandbox=sandbox)
            count += 1

    flash(f"{count} empleado(s) asignado(s) al grupo «{group.get('name', '')}».", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/unassign/<employee_id>", methods=["POST"])
def payroll_groups_unassign(group_id, employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    emp = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if emp:
        current = emp.get("payrollGroupIds", [])
        if group_id in current:
            current = [g for g in current if g != group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, employee_id, emp, sandbox=sandbox)

    flash("Empleado removido del grupo.", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/assign-all", methods=["POST"])
def payroll_groups_assign_all(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    count = 0
    for emp in employees:
        if emp.get("status") != "activo":
            continue
        current = emp.get("payrollGroupIds", [])
        if group_id not in current:
            current = list(current) + [group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, emp["id"], emp, sandbox=sandbox)
            count += 1

    flash(f"{count} empleado(s) asignado(s) al grupo «{group.get('name', '')}».", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/unassign-all", methods=["POST"])
def payroll_groups_unassign_all(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    specific_ids = request.form.getlist("employee_ids")
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    if specific_ids:
        employees = [e for e in employees if e["id"] in specific_ids]

    count = 0
    for emp in employees:
        current = emp.get("payrollGroupIds", [])
        if group_id in current:
            current = [g for g in current if g != group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, emp["id"], emp, sandbox=sandbox)
            count += 1

    flash(f"{count} empleado(s) removido(s) del grupo «{group.get('name', '')}».", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


# ═══════════════════════════════════════════════════════════════════════════
# NÓMINA — Historial y detalle
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/history")
def payroll_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    periods.sort(key=lambda p: p.get("periodKey", ""), reverse=True)

    # Filtrar por grupo si se especifica
    filter_group = request.args.get("group", "").strip()
    if filter_group:
        periods = [p for p in periods if p.get("payrollGroupId", "") == filter_group]

    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    group_map = {g["id"]: g["name"] for g in payroll_groups}

    return render_template("rrhh/payroll_list.html", active_page="rrhh_payroll",
                           periods=periods, payroll_groups=payroll_groups,
                           filter_group=filter_group, group_map=group_map)


@web_rrhh_bp.route("/rrhh/payroll/<period_id>")
def payroll_view(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    return render_template("rrhh/payroll_view.html", active_page="rrhh_payroll", period=period)


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/tss")
def payroll_tss_export(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    csv_content = PayrollService.generate_tss_csv(period, employees)

    import io
    buffer = io.BytesIO(csv_content.encode("utf-8-sig"))
    return send_file(buffer, mimetype="text/csv", as_attachment=True,
                     download_name=f"TSS_{period.get('periodKey', '')}.csv")


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/tss-autodeterminacion")
def payroll_tss_autodeterminacion(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    from app.services.db_service import DatabaseService

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    formato = request.args.get("format", "txt").lower()
    employees = hr.get_employees(owner_uid, sandbox=sandbox)

    if formato == "xls":
        company = DatabaseService.get_company_profile(owner_uid)
        employer_rnc = (company.get("companyRNC", "") or "").replace("-", "").strip() if company else ""
        resultado = PayrollService.generate_tss_autodeterminacion_xls(period, employees, employer_rnc=employer_rnc)
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        company = DatabaseService.get_company_profile(owner_uid)
        employer_rnc = (company.get("companyRNC", "") or "").replace("-", "").strip() if company else ""
        resultado = PayrollService.generate_tss_autodeterminacion(period, employees, employer_rnc=employer_rnc)
        mimetype = "text/plain"

    import io
    content = resultado["content"]
    if isinstance(content, str):
        content = content.encode("utf-8-sig")
    buffer = io.BytesIO(content)
    return send_file(buffer, mimetype=mimetype, as_attachment=True,
                     download_name=resultado["filename"])


# ═══════════════════════════════════════════════════════════════════════════
# CATÁLOGOS: Posiciones y Departamentos
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/catalog/<catalog_name>")
def catalog_list(catalog_name):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    items = hr.get_catalog(owner_uid, catalog_name, sandbox=sandbox)
    titles = {"positions": "Posiciones", "departments": "Departamentos"}
    return render_template("rrhh/catalog_list.html", active_page="rrhh_settings",
                           catalog_name=catalog_name, items=items,
                           title=titles.get(catalog_name, catalog_name))


@web_rrhh_bp.route("/rrhh/catalog/<catalog_name>/save", methods=["POST"])
def catalog_save(catalog_name):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    item_id = request.form.get("id", str(uuid.uuid4()))
    hr.save_catalog_item(owner_uid, catalog_name, {
        "id": item_id, "name": request.form.get("name", "").strip(), "active": True,
    }, sandbox=sandbox)
    flash("Guardado.", "success")
    return redirect(url_for("web_rrhh.catalog_list", catalog_name=catalog_name))


@web_rrhh_bp.route("/rrhh/catalog/<catalog_name>/delete/<item_id>", methods=["POST"])
def catalog_delete(catalog_name, item_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    hr.delete_catalog_item(owner_uid, catalog_name, item_id, sandbox=sandbox)
    flash("Eliminado.", "success")
    return redirect(url_for("web_rrhh.catalog_list", catalog_name=catalog_name))


# ═══════════════════════════════════════════════════════════════════════════
# CONCEPTOS DE NÓMINA (configurables)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/concepts")
def concept_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_concept_engine import get_concepts
    concepts = get_concepts(owner_uid, sandbox=sandbox)
    return render_template("rrhh/concepts/list.html", active_page="rrhh_settings", concepts=concepts)


@web_rrhh_bp.route("/rrhh/concepts/new", methods=["GET", "POST"])
def concept_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_concept_engine import save_concept
    if request.method == "POST":
        save_concept(owner_uid, {
            "code": request.form.get("code", "").strip().upper(),
            "name": request.form.get("name", "").strip(),
            "type": request.form.get("type", "earning"),
            "category": request.form.get("category", "fixed"),
            "taxable": request.form.get("taxable") == "on",
            "affects_afp": request.form.get("affects_afp") == "on",
            "affects_sfs": request.form.get("affects_sfs") == "on",
            "affects_isr": request.form.get("affects_isr") == "on",
            "account_debit": request.form.get("account_debit", ""),
            "account_credit": request.form.get("account_credit", ""),
            "priority": int(request.form.get("priority", 99) or 99),
            "active": True,
        }, sandbox=sandbox)
        flash("Concepto creado exitosamente.", "success")
        return redirect(url_for("web_rrhh.concept_list"))
    return render_template("rrhh/concepts/form.html", active_page="rrhh_settings", concept=None)


@web_rrhh_bp.route("/rrhh/concepts/<concept_code>/edit", methods=["GET", "POST"])
def concept_edit(concept_code):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_concept_engine import get_concept, save_concept
    concept = get_concept(owner_uid, concept_code, sandbox=sandbox)
    if not concept:
        flash("Concepto no encontrado.", "error")
        return redirect(url_for("web_rrhh.concept_list"))
    if request.method == "POST":
        concept.update({
            "name": request.form.get("name", "").strip(),
            "type": request.form.get("type", concept.get("type")),
            "category": request.form.get("category", concept.get("category")),
            "taxable": request.form.get("taxable") == "on",
            "affects_afp": request.form.get("affects_afp") == "on",
            "affects_sfs": request.form.get("affects_sfs") == "on",
            "affects_isr": request.form.get("affects_isr") == "on",
            "account_debit": request.form.get("account_debit", ""),
            "account_credit": request.form.get("account_credit", ""),
            "priority": int(request.form.get("priority", 99) or 99),
        })
        save_concept(owner_uid, concept, sandbox=sandbox)
        flash("Concepto actualizado.", "success")
        return redirect(url_for("web_rrhh.concept_list"))
    return render_template("rrhh/concepts/form.html", active_page="rrhh_settings", concept=concept)


@web_rrhh_bp.route("/rrhh/concepts/<concept_code>/toggle", methods=["POST"])
def concept_toggle(concept_code):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_concept_engine import get_concept, save_concept
    concept = get_concept(owner_uid, concept_code, sandbox=sandbox)
    if concept:
        concept["active"] = not concept.get("active", True)
        save_concept(owner_uid, concept, sandbox=sandbox)
        flash(f"Concepto {'activado' if concept['active'] else 'desactivado'}.", "success")
    return redirect(url_for("web_rrhh.concept_list"))


# ═══════════════════════════════════════════════════════════════════════════
# PORTAL DEL EMPLEADO (Self-Service)
# ═══════════════════════════════════════════════════════════════════════════

def _get_my_employee(owner_uid, sandbox):
    from app.services import hr_data_service as hr
    email = session.get("user", {}).get("email", "")
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    for emp in employees:
        if emp.get("email", "").strip().lower() == email.strip().lower():
            return emp
    return None


@web_rrhh_bp.route("/mi-perfil")
def employee_portal_dashboard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_service import PayrollService
    employee = _get_my_employee(owner_uid, sandbox)
    if not employee:
        flash("No se encontró tu perfil de empleado. Contacta a RRHH.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))

    vacation_days = PayrollService.calculate_vacation_days(employee.get("hireDate", ""))
    return render_template("rrhh/portal/dashboard.html", employee=employee, vacation_days=vacation_days)


@web_rrhh_bp.route("/mi-perfil/payslips")
def employee_portal_payslips():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(owner_uid, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))

    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    my_payslips = []
    for p in sorted(periods, key=lambda x: x.get("periodKey", ""), reverse=True)[:24]:
        for l in p.get("lines", []):
            if l.get("employeeId") == employee["id"]:
                my_payslips.append({"period": p, "line": l})
                break

    return render_template("rrhh/portal/payslips.html", employee=employee, payslips=my_payslips)


@web_rrhh_bp.route("/mi-perfil/payslips/<period_id>")
def employee_portal_payslip_detail(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(owner_uid, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_portal_payslips"))
    line = None
    for l in period.get("lines", []):
        if l.get("employeeId") == employee["id"]:
            line = l
            break
    if not line:
        flash("No tienes datos en este período.", "error")
        return redirect(url_for("web_rrhh.employee_portal_payslips"))
    return render_template("rrhh/portal/payslip_detail.html", employee=employee, period=period, line=line)


@web_rrhh_bp.route("/mi-perfil/vacations/new", methods=["GET", "POST"])
def employee_portal_vacation_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    employee = _get_my_employee(owner_uid, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    if request.method == "POST":
        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        business_days = PayrollService.calculate_business_days(start_date, end_date)
        remaining = PayrollService.calculate_vacation_days(employee.get("hireDate", ""))
        req_id = str(uuid.uuid4())
        hr.save_vacation_request(owner_uid, req_id, {
            "id": req_id, "employeeId": employee["id"],
            "employeeName": employee.get("fullName", ""),
            "startDate": start_date, "endDate": end_date,
            "days": business_days, "status": "pendiente",
            "remainingDaysBefore": remaining,
            "notes": request.form.get("notes", "").strip(),
            "createdDate": date.today().isoformat(),
        }, sandbox=sandbox)
        flash(f"Solicitud de vacaciones por {business_days} días enviada.", "success")
        return redirect(url_for("web_rrhh.employee_portal_dashboard"))
    remaining = PayrollService.calculate_vacation_days(employee.get("hireDate", ""))
    return render_template("rrhh/portal/vacation_form.html", employee=employee, remaining=remaining)


@web_rrhh_bp.route("/mi-perfil/evaluations")
def employee_portal_evaluations():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(owner_uid, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    evals = [e for e in hr.get_evaluations(owner_uid, sandbox=sandbox) if e.get("employeeId") == employee["id"]]
    return render_template("rrhh/portal/evaluations.html", employee=employee, evaluations=evals)


@web_rrhh_bp.route("/mi-perfil/trainings")
def employee_portal_trainings():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(owner_uid, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    trainings = [t for t in hr.get_trainings(owner_uid, sandbox=sandbox) if t.get("employeeId") == employee["id"]]
    return render_template("rrhh/portal/trainings.html", employee=employee, trainings=trainings)


@web_rrhh_bp.route("/mi-perfil/leave/new", methods=["GET", "POST"])
def employee_portal_leave_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(owner_uid, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    if request.method == "POST":
        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days + 1
        req_id = str(uuid.uuid4())
        hr.save_leave_request(owner_uid, req_id, {
            "id": req_id, "employeeId": employee["id"],
            "employeeName": employee.get("fullName", ""),
            "leaveType": request.form.get("leaveType", "otro"),
            "startDate": start_date, "endDate": end_date, "days": days,
            "status": "pendiente", "notes": request.form.get("notes", "").strip(),
        }, sandbox=sandbox)
        flash("Permiso registrado.", "success")
        return redirect(url_for("web_rrhh.employee_portal_dashboard"))
    return render_template("rrhh/portal/leave_form.html", employee=employee)


# ═══════════════════════════════════════════════════════════════════════════
# AUDITORÍA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/audit-log")
def audit_log():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_audit_service import get_audit_log
    entity = request.args.get("entity", "")
    limit = min(int(request.args.get("limit", 100) or 100), 500)
    logs = get_audit_log(owner_uid, entity=entity or None, limit=limit, sandbox=sandbox)
    return render_template("rrhh/audit_log.html", active_page="rrhh_settings",
                           logs=logs, entity=entity, limit=limit)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

def _parse_cost_center_accounts(form) -> dict:
    """Parsea las cuentas de centro de costo desde el formulario."""
    accounts = {}
    i = 0
    while True:
        name_key = f"cc_name_{i}"
        code_key = f"cc_code_{i}"
        name = form.get(name_key, "").strip()
        code = form.get(code_key, "").strip()
        if not name or not code:
            break
        accounts[name] = code
        i += 1
    if not accounts:
        accounts = {
            "General": "6.2.1.01",
            "Ventas": "6.2.1.01.01",
            "Produccion": "6.2.1.01.02",
            "Administrativa": "6.2.1.01.03",
        }
    return accounts


@web_rrhh_bp.route("/rrhh/payroll/settings", methods=["GET", "POST"])
def payroll_settings():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    rates = hr.get_tax_rates(owner_uid, sandbox=sandbox)
    default_rates = PayrollService.get_rates({})
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    config_updated = False

    if request.method == "POST":
        action = request.form.get("action", "save")

        # ── Guardar frecuencia por defecto (solo se usa como fallback) ──
        new_freq = request.form.get("payroll_frequency", "")
        if new_freq in ("quincenal", "mensual"):
            config["payrollFrequency"] = new_freq
            hr.save_payroll_config(owner_uid, config, sandbox=sandbox)

        if action == "reset":
            hr.save_tax_rates(owner_uid, {
                "year": date.today().year,
                "afpEmployeeRate": default_rates["afp_employee_rate"],
                "afpEmployerRate": default_rates["afp_employer_rate"],
                "sfsEmployeeRate": default_rates["sfs_employee_rate"],
                "sfsEmployerRate": default_rates["sfs_employer_rate"],
                "srlEmployerRate": default_rates["srl_employer_rate"],
                "infotepRate": default_rates["infotep_rate"],
                "afpSalaryCap": default_rates["afp_salary_cap"],
                "sfsSalaryCap": default_rates["sfs_salary_cap"],
                "minSalary": default_rates["min_salary"],
                "educationDeduction": default_rates["education_deduction"],
                "isrAnnualTable": default_rates["isr_table"],
                "overtimeRate": default_rates["overtime_rate"],
                "workingDaysPerMonth": default_rates["working_days_per_month"],
                "workingHoursPerDay": default_rates["working_hours_per_day"],
                "infotepThresholdMultiplier": default_rates["infotep_threshold_multiplier"],
                "accountSalariesPayable": default_rates["account_salaries_payable"],
                "accountAfpEmployee": default_rates["account_afp_employee"],
                "accountSfsEmployee": default_rates["account_sfs_employee"],
                "accountIsrEmployee": default_rates["account_isr_employee"],
                "accountAfpEmployer": default_rates["account_afp_employer"],
                "accountSfsEmployer": default_rates["account_sfs_employer"],
                "accountSrlEmployer": default_rates["account_srl_employer"],
                "accountInfotepEmployer": default_rates["account_infotep_employer"],
                "costCenterAccounts": default_rates["cost_center_accounts"],
                "updatedBy": session.get("user", {}).get("email", ""),
            }, sandbox=sandbox)
        else:
            isr_table = []
            i = 0
            while True:
                desde_key = f"isr_from_{i}"
                if not request.form.get(desde_key):
                    break
                desde = float(request.form.get(desde_key, 0) or 0)
                hasta_raw = request.form.get(f"isr_to_{i}", "0")
                tasa = float(request.form.get(f"isr_rate_{i}", 0) or 0) / 100.0
                fija = float(request.form.get(f"isr_fixed_{i}", 0) or 0)
                # Ultima fila: el "hasta" puede venir como hidden "999999999" o como "inf"
                if hasta_raw in ("999999999", "inf", ""):
                    hasta = float("inf")
                else:
                    hasta = float(hasta_raw or 0)
                isr_table.append([desde, hasta, tasa, fija])
                i += 1
            hr.save_tax_rates(owner_uid, {
                "year": date.today().year,
                "afpEmployeeRate": float(request.form.get("afpEmployeeRate", 0) or 0) / 100.0,
                "afpEmployerRate": float(request.form.get("afpEmployerRate", 0) or 0) / 100.0,
                "sfsEmployeeRate": float(request.form.get("sfsEmployeeRate", 0) or 0) / 100.0,
                "sfsEmployerRate": float(request.form.get("sfsEmployerRate", 0) or 0) / 100.0,
                "srlEmployerRate": float(request.form.get("srlEmployerRate", 0) or 0) / 100.0,
                "infotepRate": float(request.form.get("infotepRate", 0) or 0) / 100.0,
                "afpSalaryCap": float(request.form.get("afpSalaryCap", 0) or 0),
                "sfsSalaryCap": float(request.form.get("sfsSalaryCap", 0) or 0),
                "minSalary": float(request.form.get("minSalary", 0) or 0),
                "educationDeduction": float(request.form.get("educationDeduction", 0) or 0),
                "isrAnnualTable": isr_table,
                "overtimeRate": float(request.form.get("overtimeRate", 135) or 135) / 100.0,
                "workingDaysPerMonth": float(request.form.get("workingDaysPerMonth", 23.83) or 23.83),
                "workingHoursPerDay": float(request.form.get("workingHoursPerDay", 8) or 8),
                "infotepThresholdMultiplier": float(request.form.get("infotepThresholdMultiplier", 5) or 5),
                "accountSalariesPayable": request.form.get("accountSalariesPayable", "2.1.2.1.02").strip(),
                "accountAfpEmployee": request.form.get("accountAfpEmployee", "2.1.2.1.05").strip(),
                "accountSfsEmployee": request.form.get("accountSfsEmployee", "2.1.2.1.06").strip(),
                "accountIsrEmployee": request.form.get("accountIsrEmployee", "2.1.2.1.08").strip(),
                "accountAfpEmployer": request.form.get("accountAfpEmployer", "2.1.2.1.10").strip(),
                "accountSfsEmployer": request.form.get("accountSfsEmployer", "2.1.2.1.09").strip(),
                "accountSrlEmployer": request.form.get("accountSrlEmployer", "2.1.2.1.11").strip(),
                "accountInfotepEmployer": request.form.get("accountInfotepEmployer", "2.1.2.1.12").strip(),
                "costCenterAccounts": _parse_cost_center_accounts(request.form),
                "updatedBy": session.get("user", {}).get("email", ""),
            }, sandbox=sandbox)
        config_updated = True
        rates = hr.get_tax_rates(owner_uid, sandbox=sandbox)

    if not rates:
        rates = {
            "year": date.today().year,
            "afpEmployeeRate": default_rates["afp_employee_rate"],
            "afpEmployerRate": default_rates["afp_employer_rate"],
            "sfsEmployeeRate": default_rates["sfs_employee_rate"],
            "sfsEmployerRate": default_rates["sfs_employer_rate"],
            "srlEmployerRate": default_rates["srl_employer_rate"],
            "infotepRate": default_rates["infotep_rate"],
            "afpSalaryCap": default_rates["afp_salary_cap"],
            "sfsSalaryCap": default_rates["sfs_salary_cap"],
            "minSalary": default_rates["min_salary"],
            "educationDeduction": default_rates["education_deduction"],
            "isrAnnualTable": default_rates["isr_table"],
            "overtimeRate": default_rates["overtime_rate"],
            "workingDaysPerMonth": default_rates["working_days_per_month"],
            "workingHoursPerDay": default_rates["working_hours_per_day"],
            "infotepThresholdMultiplier": default_rates["infotep_threshold_multiplier"],
            "accountSalariesPayable": default_rates["account_salaries_payable"],
            "accountAfpEmployee": default_rates["account_afp_employee"],
            "accountSfsEmployee": default_rates["account_sfs_employee"],
            "accountIsrEmployee": default_rates["account_isr_employee"],
            "accountAfpEmployer": default_rates["account_afp_employer"],
            "accountSfsEmployer": default_rates["account_sfs_employer"],
            "accountSrlEmployer": default_rates["account_srl_employer"],
            "accountInfotepEmployer": default_rates["account_infotep_employer"],
            "costCenterAccounts": default_rates["cost_center_accounts"],
            "updatedAt": "",
            "updatedBy": "",
        }

    # Recargar config después de posibles cambios
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    # Asegurar que todos los campos tengan valores por defecto
    rates.setdefault("overtimeRate", default_rates["overtime_rate"])
    rates.setdefault("workingDaysPerMonth", default_rates["working_days_per_month"])
    rates.setdefault("workingHoursPerDay", default_rates["working_hours_per_day"])
    rates.setdefault("infotepThresholdMultiplier", default_rates["infotep_threshold_multiplier"])
    rates.setdefault("accountSalariesPayable", default_rates["account_salaries_payable"])
    rates.setdefault("accountAfpEmployee", default_rates["account_afp_employee"])
    rates.setdefault("accountSfsEmployee", default_rates["account_sfs_employee"])
    rates.setdefault("accountIsrEmployee", default_rates["account_isr_employee"])
    rates.setdefault("accountAfpEmployer", default_rates["account_afp_employer"])
    rates.setdefault("accountSfsEmployer", default_rates["account_sfs_employer"])
    rates.setdefault("accountSrlEmployer", default_rates["account_srl_employer"])
    rates.setdefault("accountInfotepEmployer", default_rates["account_infotep_employer"])
    rates.setdefault("costCenterAccounts", default_rates["cost_center_accounts"])
    from types import SimpleNamespace
    # ── Grupos de nómina para integrar en settings ──
    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))
    all_employees = hr.get_employees(owner_uid, sandbox=sandbox)
    assigned_group_ids = set()
    for emp in all_employees:
        for gid in emp.get("payrollGroupIds", []):
            assigned_group_ids.add(gid)
    unassigned_employees = [e for e in all_employees if e.get("status") == "activo"
                            and not any(gid in e.get("payrollGroupIds", []) for gid in [g["id"] for g in payroll_groups])]
    return render_template("rrhh/settings.html", active_page="rrhh_settings",
                           tax_rates=SimpleNamespace(**rates), config_updated=config_updated,
                           payroll_frequency=config.get("payrollFrequency", "mensual"),
                           payroll_groups=payroll_groups,
                           unassigned_employees=unassigned_employees,
                           group_employee_counts={g["id"]: len([e for e in all_employees if g["id"] in e.get("payrollGroupIds", [])]) for g in payroll_groups})


# ═══════════════════════════════════════════════════════════════════════════
# REPORTES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/reports/ir18")
def report_ir18_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_ytd_service import get_ytd

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    try:
        year = int(request.args.get("year", date.today().year))
    except (ValueError, TypeError):
        year = date.today().year

    employee_ytds = []
    for emp in employees:
        if emp.get("status") != "activo":
            continue
        ytd = get_ytd(owner_uid, emp["id"], year, sandbox=sandbox)
        if ytd.get("grossIncome", 0) > 0:
            employee_ytds.append({
                "employee": emp,
                "ytd": ytd,
            })

    return render_template("rrhh/reports/ir18_list.html", active_page="rrhh_reports",
                           employee_ytds=employee_ytds, year=year)


@web_rrhh_bp.route("/rrhh/reports/ir18/<employee_id>")
def report_ir18_view(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_ytd_service import get_ytd

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.report_ir18_list"))

    try:
        year = int(request.args.get("year", date.today().year))
    except (ValueError, TypeError):
        year = date.today().year

    ytd = get_ytd(owner_uid, employee_id, year, sandbox=sandbox)
    return render_template("rrhh/reports/ir18_detail.html", active_page="rrhh_reports",
                           employee=employee, ytd=ytd, year=year, today=date.today())


@web_rrhh_bp.route("/rrhh/reports")
def reports_index():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/reports/index.html", active_page="rrhh_reports")


@web_rrhh_bp.route("/rrhh/reports/department")
def report_department():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    period_key = request.args.get("period", "")
    period = next((p for p in periods if p.get("periodKey") == period_key), None) if period_key else None
    by_dept = {}
    if period:
        for l in period.get("lines", []):
            dept = l.get("department", "Sin depto")
            if dept not in by_dept:
                by_dept[dept] = {"count": 0, "gross": 0.0, "net": 0.0, "employer": 0.0}
            by_dept[dept]["count"] += 1
            by_dept[dept]["gross"] += l.get("totalIncome", 0)
            by_dept[dept]["net"] += l.get("netSalary", 0)
            by_dept[dept]["employer"] += l.get("totalEmployerContrib", 0)
    period_keys = sorted(set(p.get("periodKey", "") for p in periods), reverse=True)
    return render_template("rrhh/reports/department.html", active_page="rrhh_reports",
                           by_dept=by_dept, period_keys=period_keys, selected=period_key)


@web_rrhh_bp.route("/rrhh/reports/tss")
def report_tss():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    try:
        year = int(request.args.get("year", date.today().year))
    except (ValueError, TypeError):
        year = date.today().year
    monthly = {}
    for m in range(1, 13):
        key = f"{year}-{m:02d}"
        monthly[key] = {"afp_emp": 0, "sfs_emp": 0, "afp_empl": 0, "sfs_empl": 0, "srl": 0, "infotep": 0}
    for p in periods:
        pk = p.get("periodKey", "")
        if str(year) not in pk:
            continue
        base_key = pk[:7] if len(pk) >= 7 else pk
        if base_key in monthly:
            for l in p.get("lines", []):
                monthly[base_key]["afp_emp"] += l.get("afpEmployee", 0)
                monthly[base_key]["sfs_emp"] += l.get("sfsEmployee", 0)
                monthly[base_key]["afp_empl"] += l.get("afpEmployer", 0)
                monthly[base_key]["sfs_empl"] += l.get("sfsEmployer", 0)
                monthly[base_key]["srl"] += l.get("srlEmployer", 0)
                monthly[base_key]["infotep"] += l.get("infotepEmployer", 0)
    return render_template("rrhh/reports/tss.html", active_page="rrhh_reports",
                           monthly=monthly, year=year, months_es=MONTHS_ES)


@web_rrhh_bp.route("/rrhh/reports/comparative")
def report_comparative():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    periods.sort(key=lambda p: p.get("periodKey", ""), reverse=True)
    p1_key = request.args.get("p1", "")
    p2_key = request.args.get("p2", "")
    p1 = next((p for p in periods if p.get("periodKey") == p1_key), None) if p1_key else None
    p2 = next((p for p in periods if p.get("periodKey") == p2_key), None) if p2_key else None
    comparison = None
    if p1 and p2:
        def pt(p):
            return {
                "gross": round(sum(l.get("totalIncome", 0) for l in p.get("lines", [])), 2),
                "net": round(sum(l.get("netSalary", 0) for l in p.get("lines", [])), 2),
                "employer": round(sum(l.get("totalEmployerContrib", 0) for l in p.get("lines", [])), 2),
                "count": len(p.get("lines", [])),
            }
        t1 = pt(p1)
        t2 = pt(p2)
        comparison = {
            "p1_label": p1.get("periodRange") or p1.get("periodKey"),
            "p2_label": p2.get("periodRange") or p2.get("periodKey"),
            "count_diff": t1["count"] - t2["count"],
            "gross_diff": round(t1["gross"] - t2["gross"], 2),
            "gross_pct": round((t1["gross"] - t2["gross"]) / t2["gross"] * 100, 1) if t2["gross"] else 0,
            "net_diff": round(t1["net"] - t2["net"], 2),
            "net_pct": round((t1["net"] - t2["net"]) / t2["net"] * 100, 1) if t2["net"] else 0,
            "employer_diff": round(t1["employer"] - t2["employer"], 2),
            "t1": t1, "t2": t2,
        }
    period_keys = [p.get("periodKey", "") for p in periods]
    return render_template("rrhh/reports/comparative.html", active_page="rrhh_reports",
                           period_keys=period_keys, comparison=comparison,
                           p1_key=p1_key, p2_key=p2_key)


# ═══════════════════════════════════════════════════════════════════════════
# REPORTE: NÓMINA NETA SIN PROVISIONES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/reports/net-payroll")
def report_net_payroll():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    periods.sort(key=lambda p: p.get("periodKey", ""), reverse=True)

    # Filtro por período
    period_key = request.args.get("period", "")
    selected = None
    if period_key:
        selected = next((p for p in periods if p.get("periodKey") == period_key), None)

    period_keys = [p.get("periodKey", "") for p in periods]
    lines = selected.get("lines", []) if selected else []

    return render_template("rrhh/reports/net_payroll.html", active_page="rrhh_reports",
                           period_keys=period_keys, selected=selected,
                           lines=lines, period_key=period_key)


@web_rrhh_bp.route("/rrhh/reports/net-payroll/export")
def report_net_payroll_export():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period_key = request.args.get("period", "")
    period = hr.get_payroll_period_by_key(owner_uid, period_key, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.report_net_payroll"))

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Empleado", "Cedula", "Cargo", "Salario Base", "Horas Extra",
                      "Comisiones", "Total Bruto", "Otras Ded.", "Neto sin Provisiones"])
    for l in period.get("lines", []):
        neto_sin_provisiones = round(l.get("netSalary", 0) + l.get("afpEmployee", 0) +
                                     l.get("sfsEmployee", 0) + l.get("infotepEmployee", 0) +
                                     l.get("isrRetention", 0), 2)
        writer.writerow([
            l.get("employeeName", ""), l.get("cedula", ""), l.get("position", ""),
            f"{l.get('baseSalary', 0):.2f}", f"{l.get('overtimeHours', 0):.2f}",
            f"{l.get('commission', 0):.2f}", f"{l.get('totalIncome', 0):.2f}",
            f"{l.get('otherDeductions', 0):.2f}", f"{neto_sin_provisiones:.2f}",
        ])
    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode("utf-8"))
    dest.seek(0)
    period_label = period_key or "nomina"
    filename = f"nomina_neta_{period_label}.csv"
    return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)


# ═══════════════════════════════════════════════════════════════════════════
# EXPORTACIÓN CSV DE NÓMINA GENERAL CONSOLIDADA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/<period_id>/export-csv")
def payroll_export_csv(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Empleado", "Cedula", "Cargo", "Salario Base", "Bruto",
                      "AFP Emp.", "SFS Emp.", "INFOTEP Emp.", "ISR", "Otras Ded.",
                      "Neto", "AFP Empl.", "SFS Empl.", "SRL", "INFOTEP Empl.",
                      "Aportes Empleador"])
    for l in period.get("lines", []):
        writer.writerow([
            l.get("employeeName", ""), l.get("cedula", ""), l.get("position", ""),
            f"{l.get('baseSalary', 0):.2f}", f"{l.get('totalIncome', 0):.2f}",
            f"{l.get('afpEmployee', 0):.2f}", f"{l.get('sfsEmployee', 0):.2f}",
            f"{l.get('infotepEmployee', 0):.2f}", f"{l.get('isrRetention', 0):.2f}",
            f"{l.get('otherDeductions', 0):.2f}", f"{l.get('netSalary', 0):.2f}",
            f"{l.get('afpEmployer', 0):.2f}", f"{l.get('sfsEmployer', 0):.2f}",
            f"{l.get('srlEmployer', 0):.2f}", f"{l.get('infotepEmployer', 0):.2f}",
            f"{l.get('totalEmployerContrib', 0):.2f}",
        ])
    # Totales
    writer.writerow([])
    writer.writerow(["TOTALES", "", "", "",
                     f"{period.get('totalGross', 0):.2f}", "", "", "", "", "",
                     f"{period.get('totalNet', 0):.2f}", "", "", "", "",
                     f"{period.get('totalEmployerContrib', 0):.2f}"])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode("utf-8"))
    dest.seek(0)
    period_label = period.get("periodKey", "nomina")
    filename = f"nomina_general_{period_label}.csv"
    return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)


# ═══════════════════════════════════════════════════════════════════════════
# REPORTE: RETENCIONES ISR NÓMINA (suma quincenas para DGII)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/reports/isr-retentions")
def report_isr_retentions():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    try:
        year = int(request.args.get("year", date.today().year))
    except (ValueError, TypeError):
        year = date.today().year

    # Agrupar por mes: sumar quincenas si existen
    monthly = {}
    for m in range(1, 13):
        key = f"{year}-{m:02d}"
        monthly[key] = {"isr": 0.0, "afp_emp": 0.0, "sfs_emp": 0.0, "employees": 0, "lines": []}

    for p in periods:
        pk = p.get("periodKey", "")
        if str(year) not in pk:
            continue
        base_key = pk[:7]
        if base_key in monthly:
            for l in p.get("lines", []):
                monthly[base_key]["isr"] += l.get("isrRetention", 0)
                monthly[base_key]["afp_emp"] += l.get("afpEmployee", 0)
                monthly[base_key]["sfs_emp"] += l.get("sfsEmployee", 0)
                monthly[base_key]["employees"] += 1
                monthly[base_key]["lines"].append(l)

    return render_template("rrhh/reports/isr_retentions.html", active_page="rrhh_reports",
                           monthly=monthly, year=year, months_es=MONTHS_ES)


@web_rrhh_bp.route("/rrhh/reports/isr-retentions/export")
def report_isr_retentions_export():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    try:
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))
    except (ValueError, TypeError):
        year = date.today().year
        month = date.today().month

    # Agrupar para el mes seleccionado
    base_key = f"{year}-{month:02d}"
    isr_lines = []
    for p in periods:
        pk = p.get("periodKey", "")
        if pk[:7] == base_key:
            for l in p.get("lines", []):
                if l.get("isrRetention", 0) > 0:
                    isr_lines.append(l)

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["RNC Agente", "Período", "Cédula Retenido", "Nombre Retenido",
                      "ISR Retenido", "Salario Bruto", "Período Nómina"])
    period_label = f"{year:04d}{month:02d}"
    for l in isr_lines:
        writer.writerow([
            "", period_label, l.get("cedula", ""), l.get("employeeName", ""),
            f"{l.get('isrRetention', 0):.2f}", f"{l.get('totalIncome', 0):.2f}",
            l.get("periodType", ""),
        ])
    writer.writerow([])
    total_isr = sum(l.get("isrRetention", 0) for l in isr_lines)
    writer.writerow(["TOTAL", "", "", "", f"{total_isr:.2f}", "", ""])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode("utf-8"))
    dest.seek(0)
    filename = f"isr_retenciones_{period_label}.csv"
    return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW DE APROBACIÓN Y CONTABILIZACIÓN
# ═══════════════════════════════════════════════════════════════════════════

_VALID_TRANSITIONS = {
    "borrador":     ["calculada"],
    "calculada":    ["validada", "borrador"],
    "validada":     ["aprobada", "calculada", "borrador"],
    "aprobada":     ["contabilizada", "validada"],
    "contabilizada": ["pagada", "aprobada"],
    "pagada":       ["cerrada", "contabilizada"],
    "cerrada":      [],
}

STATUS_LABELS = {
    "borrador": "Borrador",
    "calculada": "Calculada",
    "validada": "Validada",
    "aprobada": "Aprobada",
    "contabilizada": "Contabilizada",
    "pagada": "Pagada",
    "cerrada": "Cerrada",
}


def _transition(period, to_status, comment="", owner_uid="", sandbox=True):
    user_email = session.get("user", {}).get("email", "")
    now_iso = datetime.now(timezone.utc).isoformat()
    from_status = period.get("status", "borrador")

    if to_status not in _VALID_TRANSITIONS.get(from_status, []):
        return False, f"Transición inválida: no se puede pasar de «{STATUS_LABELS.get(from_status, from_status)}» a «{STATUS_LABELS.get(to_status, to_status)}»."

    period["status"] = to_status
    history = period.get("statusHistory", [])
    history.append({
        "from": from_status,
        "to": to_status,
        "by": user_email,
        "at": now_iso,
        "comment": comment,
    })
    period["statusHistory"] = history

    if to_status == "calculada":
        period["calculatedBy"] = user_email
        period["calculatedAt"] = now_iso
    elif to_status == "validada":
        period["validatedBy"] = user_email
        period["validatedAt"] = now_iso
    elif to_status == "aprobada":
        period["approvedBy"] = user_email
        period["approvedAt"] = now_iso
    elif to_status == "contabilizada":
        period["postedBy"] = user_email
        period["postedAt"] = now_iso
    elif to_status == "pagada":
        period["paidBy"] = user_email
        period["paidAt"] = now_iso
    elif to_status == "cerrada":
        period["closedBy"] = user_email
        period["closedAt"] = now_iso

    # ── Snapshot de empleados para DGT-4 ──
    if to_status in ("calculada", "cerrada") and owner_uid:
        try:
            from app.services import hr_data_service as hr
            employees = hr.get_employees(owner_uid, sandbox=sandbox)
            snapshot = []
            for emp in employees:
                if emp.get("status") == "activo":
                    snapshot.append({
                        "employeeId": emp.get("id", ""),
                        "cedula": (emp.get("cedula") or emp.get("idNumber", "")).replace("-", ""),
                        "fullName": emp.get("fullName", ""),
                        "position": emp.get("position", ""),
                        "baseSalary": emp.get("baseSalary", emp.get("salary", 0)),
                        "contractType": emp.get("contractType", ""),
                        "status": emp.get("status", ""),
                        "hireDate": emp.get("hireDate", ""),
                        "terminationDate": emp.get("terminationDate", ""),
                    })
            period["employeeSnapshot"] = snapshot
        except Exception as e:
            print(f"⚠️ Error guardando snapshot empleados para DGT-4: {e}")

    if owner_uid:
        from app.services.payroll_audit_service import log_action
        log_action(owner_uid, to_status, "payroll_period", period.get("id", ""),
                   user_email, changes={"from": from_status, "to": to_status}, comment=comment, sandbox=sandbox)

    return True, "OK"


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/bank-export")
def payroll_bank_export(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.bank_export_service import generate_bank_file

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    bank = request.args.get("bank", "popular")
    employees_list = hr.get_employees(owner_uid, sandbox=sandbox)
    emp_map = {e["id"]: e for e in employees_list}
    content = generate_bank_file(period, emp_map, bank=bank)

    import io as _io
    buffer = _io.BytesIO(content)
    return send_file(buffer, mimetype="text/plain", as_attachment=True,
                     download_name=f"Nomina_{period.get('periodKey','')}_{bank}.txt")


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/validate", methods=["POST"])
def payroll_validate(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    ok, msg = _transition(period, "validada", request.form.get("comment", ""),
                          owner_uid=owner_uid, sandbox=sandbox)
    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)
        flash("Nómina validada.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/approve", methods=["POST"])
def payroll_approve(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    ok, msg = _transition(period, "aprobada", request.form.get("comment", ""),
                          owner_uid=owner_uid, sandbox=sandbox)
    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)
        flash("Nómina aprobada.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/post", methods=["POST"])
def payroll_post(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    # Generar asiento contable
    try:
        from app.services.accounting_service import AccountingService
        from app.services.db_service import DatabaseService
        tax_rates_data = hr.get_tax_rates(owner_uid, sandbox=sandbox)
        now_str = date.today().isoformat()
        employees_list = hr.get_employees(owner_uid, sandbox=sandbox)
        emp_map = {e["id"]: e for e in employees_list}
        acct_lines = PayrollService.build_payroll_accounting_lines(period, employees=emp_map, tax_rates=tax_rates_data)
        if acct_lines:
            AccountingService.seed_default_accounts(owner_uid)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
            full_lines = []
            for al in acct_lines:
                acc = next((a for a in accounts if a.get("code") == al["accountCode"]), None)
                if acc:
                    full_lines.append({
                        "accountId": acc["id"],
                        "accountCode": al["accountCode"],
                        "accountName": al["accountName"],
                        "debit": al["debit"],
                        "credit": al["credit"],
                        "description": al["description"],
                    })
            if full_lines:
                AccountingService.generate_entry(owner_uid, {
                    "entryType": "payroll",
                    "date": now_str,
                    "concept": f"Nómina período {period.get('periodRange') or period.get('periodKey')}",
                    "referenceType": "payroll",
                    "referenceId": period_id,
                    "referenceNumber": period.get("periodKey", ""),
                    "lines": full_lines,
                    "createdBy": session.get("user", {}).get("email", "system"),
                    "prefix": "NOM",
                }, sandbox=sandbox)
                period["accountingEntryGenerated"] = True
        else:
            flash("No se generaron líneas contables para este período.", "warning")
    except Exception as e:
        flash(f"Error al generar asiento contable: {e}", "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    ok, msg = _transition(period, "contabilizada", request.form.get("comment", ""),
                          owner_uid=owner_uid, sandbox=sandbox)
    if not ok:
        flash(msg, "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)
    flash("Nómina contabilizada exitosamente.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/pay", methods=["POST"])
def payroll_pay(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    ok, msg = _transition(period, "pagada", request.form.get("comment", ""),
                          owner_uid=owner_uid, sandbox=sandbox)
    if not ok:
        flash(msg, "error")
    else:
        period["paidDate"] = date.today().isoformat()
        hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)
        flash("Nómina marcada como pagada.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/close", methods=["POST"])
def payroll_close(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    ok, msg = _transition(period, "cerrada", request.form.get("comment", ""),
                          owner_uid=owner_uid, sandbox=sandbox)
    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)
        flash("Nómina cerrada. No se permiten más modificaciones.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/send-payslips", methods=["POST"])
def payroll_send_payslips(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    lines = period.get("lines", [])
    employees_list = hr.get_employees(owner_uid, sandbox=sandbox)
    emp_map = {e["id"]: e for e in employees_list}

    try:
        from app.services.mailer import Mailer
    except Exception as e:
        flash("Error al cargar dependencias de correo.", "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    period_label = period.get("periodRange") or period.get("periodKey", "")
    sent = 0
    skipped = 0
    errors = 0

    for line in lines:
        emp_id = line.get("employeeId", "")
        emp = emp_map.get(emp_id, {})
        email = (emp.get("email") or "").strip()
        if not email:
            skipped += 1
            continue
        try:
            html_body = render_template("rrhh/employee_payslip_email.html",
                                        employee=emp, period=period, line=line)
            subject = f"Volante de pago — {period_label}"
            Mailer.send(
                app=current_app._get_current_object(),
                to_email=email,
                subject=subject,
                html_body=html_body,
                from_name=current_app.config.get("COMPANY_NAME", ""),
                category="noreply",
            )
            sent += 1
        except Exception as e:
            print(f"⚠️ Error enviando volante a {email}: {e}")
            errors += 1

    period["payslipsSentAt"] = datetime.now(timezone.utc).isoformat()
    period["payslipsSentBy"] = session.get("user", {}).get("email", "")
    hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)

    if sent > 0 and errors == 0:
        flash(f"Volantes enviados a {sent} empleado(s). {skipped} omitido(s) sin email.", "success")
    elif sent > 0:
        flash(f"{sent} enviado(s), {errors} error(es), {skipped} omitido(s) sin email.", "warning")
    else:
        flash(f"No se envió ningún volante. {skipped} empleado(s) sin email.", "warning")

    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/send-payslips/async", methods=["POST"])
def payroll_send_payslips_async(period_id):
    if _login_required():
        return jsonify({"error": "unauthorized"}), 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_async_service import create_job, update_job

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        return jsonify({"error": "period not found"}), 404

    lines = period.get("lines", [])
    employees_list = hr.get_employees(owner_uid, sandbox=sandbox)
    emp_map = {e["id"]: e for e in employees_list}

    try:
        from app.services.mailer import Mailer
    except Exception as e:
        return jsonify({"error": "mailer unavailable"}), 500

    job_id = create_job(owner_uid, sandbox=sandbox)
    if not job_id:
        return jsonify({"error": "could not create job"}), 500

    period_label = period.get("periodRange") or period.get("periodKey", "")
    total = len(lines)

    update_job(owner_uid, job_id, {
        "status": "running",
        "progress": 0,
        "total": total,
        "message": "Iniciando envío de volantes...",
    }, sandbox=sandbox)

    def _send_worker():
        import flask
        sent = 0
        skipped = 0
        errors = 0
        for idx, line in enumerate(lines):
            emp_id = line.get("employeeId", "")
            emp = emp_map.get(emp_id, {})
            email = (emp.get("email") or "").strip()
            if not email:
                skipped += 1
                update_job(owner_uid, job_id, {
                    "progress": idx + 1,
                    "message": f"Omitido {idx+1}/{total}: {emp.get('fullName','')} sin email",
                }, sandbox=sandbox)
                continue
            try:
                with current_app.app_context():
                    html_body = flask.render_template("rrhh/employee_payslip_email.html",
                                                       employee=emp, period=period, line=line)
                    subject = f"Volante de pago — {period_label}"
                    Mailer.send(
                        app=current_app._get_current_object(),
                        to_email=email,
                        subject=subject,
                        html_body=html_body,
                        from_name=current_app.config.get("COMPANY_NAME", ""),
                        category="noreply",
                    )
                sent += 1
                update_job(owner_uid, job_id, {
                    "progress": idx + 1,
                    "message": f"Enviado {idx+1}/{total}: {emp.get('fullName','')}",
                }, sandbox=sandbox)
            except Exception as e:
                errors += 1
                print(f"⚠️ Error enviando volante a {email}: {e}")
                update_job(owner_uid, job_id, {
                    "progress": idx + 1,
                    "message": f"Error {idx+1}/{total}: {emp.get('fullName','')} — {e}",
                }, sandbox=sandbox)

        msg = f"Completado: {sent} enviado(s), {skipped} omitido(s), {errors} error(es)"
        update_job(owner_uid, job_id, {
            "status": "completed",
            "progress": total,
            "message": msg,
            "result": {"sent": sent, "skipped": skipped, "errors": errors},
        }, sandbox=sandbox)

        period["payslipsSentAt"] = datetime.now(timezone.utc).isoformat()
        period["payslipsSentBy"] = session.get("user", {}).get("email", "")
        hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)

    import threading
    t = threading.Thread(target=_send_worker, daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "status": "created"})


@web_rrhh_bp.route("/rrhh/payroll/jobs/<job_id>/status")
def payroll_job_status(job_id):
    if _login_required():
        return jsonify({"error": "unauthorized"}), 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_async_service import get_job
    job = get_job(owner_uid, job_id, sandbox=sandbox)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "total": job.get("total", 0),
        "message": job.get("message", ""),
        "result": job.get("result"),
        "error": job.get("error"),
    })


@web_rrhh_bp.route("/rrhh/payroll/progress/<job_id>")
def payroll_progress(job_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/payroll_progress.html", active_page="rrhh_payroll", job_id=job_id)


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/recalculate", methods=["POST"])
def payroll_recalculate(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    status = period.get("status", "")
    if status == "cerrada":
        flash("No se puede modificar una nómina cerrada.", "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    # Confirmación requerida para estados avanzados
    confirm = request.form.get("confirm", "")
    target = "borrador"
    comment = "Recálculo solicitado"

    if status in ("contabilizada", "pagada"):
        # Revertir paso a paso con confirmación explícita
        if confirm != "RECALCULAR":
            flash("Para revertir una nómina contabilizada o pagada, debes escribir RECALCULAR en el campo de confirmación.", "warning")
            return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))
        comment = "Reversión forzada con confirmación explícita"
        # Primero revertir al estado anterior
        if status == "pagada":
            prev_ok, prev_msg = _transition(period, "contabilizada", "Reversión desde pagada",
                                            owner_uid=owner_uid, sandbox=sandbox)
            if not prev_ok:
                flash(prev_msg, "error")
                return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))
            status = "contabilizada"
        if status == "contabilizada":
            prev_ok, prev_msg = _transition(period, "aprobada", "Reversión desde contabilizada",
                                            owner_uid=owner_uid, sandbox=sandbox)
            if not prev_ok:
                flash(prev_msg, "error")
                return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))
        # Ahora a borrador
        ok, msg = _transition(period, "borrador", comment,
                              owner_uid=owner_uid, sandbox=sandbox)
    else:
        ok, msg = _transition(period, target, comment,
                              owner_uid=owner_uid, sandbox=sandbox)

    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)
        flash("Nómina revertida a borrador. Puede recalcularla desde «Calcular nómina».", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/delete", methods=["POST"])
def payroll_delete(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_audit_service import log_action

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    status = period.get("status", "")
    if status != "borrador":
        flash("Solo se pueden eliminar nóminas en estado borrador. Revierta la nómina primero.", "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    confirm = request.form.get("confirm", "")
    if confirm != "ELIMINAR":
        flash("Debes escribir ELIMINAR en el campo de confirmación para borrar definitivamente.", "warning")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    period_key = period.get("periodKey", "")
    period_range = period.get("periodRange", "")
    user_email = session.get("user", {}).get("email", "")

    log_action(owner_uid, "delete", "payroll_period", period_id, user_email,
               changes={"period": period_key, "status": status, "range": period_range},
               comment="Eliminación de período de nómina", sandbox=sandbox)

    hr.delete_payroll_period(owner_uid, period_id, sandbox=sandbox)
    flash(f"Período de nómina «{period_range or period_key}» eliminado permanentemente.", "success")
    return redirect(url_for("web_rrhh.payroll_list"))


# ═══════════════════════════════════════════════════════════════════════════
# EVALUACIONES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/evaluations")
def evaluation_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    evals = hr.get_evaluations(owner_uid, sandbox=sandbox)
    evals.sort(key=lambda e: e.get("date", ""), reverse=True)
    employees = {e["id"]: e for e in hr.get_employees(owner_uid, sandbox=sandbox)}
    return render_template("rrhh/evaluation_list.html", active_page="rrhh_development",
                           evaluations=evals, employees=employees)


@web_rrhh_bp.route("/rrhh/evaluations/new", methods=["GET", "POST"])
def evaluation_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
        eval_id = str(uuid.uuid4())
        hr.save_evaluation(owner_uid, eval_id, {
            "id": eval_id,
            "employeeId": emp_id,
            "employeeName": employee.get("fullName", "") if employee else "",
            "date": request.form.get("date", date.today().isoformat()),
            "evalType": request.form.get("evalType", "periodica"),
            "score": float(request.form.get("score", 3)),
            "strengths": request.form.get("strengths", "").strip(),
            "improvements": request.form.get("improvements", "").strip(),
            "evaluatorName": request.form.get("evaluatorName", "").strip(),
            "notes": request.form.get("notes", "").strip(),
        }, sandbox=sandbox)
        flash("Evaluación registrada.", "success")
        return redirect(url_for("web_rrhh.evaluation_list"))

    return render_template("rrhh/evaluation_form.html", active_page="rrhh_development", employees=employees, now=datetime.now)


@web_rrhh_bp.route("/rrhh/trainings")
def training_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    trainings = hr.get_trainings(owner_uid, sandbox=sandbox)
    trainings.sort(key=lambda t: t.get("date", ""), reverse=True)
    return render_template("rrhh/training_list.html", active_page="rrhh_development", trainings=trainings)


@web_rrhh_bp.route("/rrhh/trainings/new", methods=["GET", "POST"])
def training_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
        train_id = str(uuid.uuid4())
        hr.save_training(owner_uid, train_id, {
            "id": train_id,
            "employeeId": emp_id,
            "employeeName": employee.get("fullName", "") if employee else "",
            "trainingName": request.form.get("trainingName", "").strip(),
            "institution": request.form.get("institution", "").strip(),
            "date": request.form.get("date", date.today().isoformat()),
            "hours": int(request.form.get("hours", 0) or 0),
            "hasCertificate": request.form.get("hasCertificate") == "on",
            "notes": request.form.get("notes", "").strip(),
        }, sandbox=sandbox)
        flash("Capacitación registrada.", "success")
        return redirect(url_for("web_rrhh.training_list"))

    return render_template("rrhh/training_form.html", active_page="rrhh_development", employees=employees, now=datetime.now)


# ═══════════════════════════════════════════════════════════════════════════
# ACCIONES DE PERSONAL MASIVAS
# ═══════════════════════════════════════════════════════════════════════════

MASS_ACTION_TYPES = {
    "salary_change": {
        "label": "Cambio de Salario",
        "icon": "fa-solid fa-money-bill-trend-up",
        "desc": "Ajuste salarial masivo por monto fijo o porcentaje.",
    },
    "position_change": {
        "label": "Cambio de Puesto",
        "icon": "fa-solid fa-briefcase",
        "desc": "Reasignación de cargo, área o departamento.",
    },
    "supervisor_change": {
        "label": "Cambio de Supervisor",
        "icon": "fa-solid fa-user-tie",
        "desc": "Reasignación masiva de reporting jerárquico.",
    },
    "promotion": {
        "label": "Promoción",
        "icon": "fa-solid fa-arrow-up",
        "desc": "Combinación de cambio de puesto y ajuste salarial.",
    },
    "mass_absence": {
        "label": "Ausencia Masiva",
        "icon": "fa-solid fa-calendar-xmark",
        "desc": "Vacaciones colectivas, permisos o licencias.",
    },
}


@web_rrhh_bp.route("/rrhh/employees/mass-action", methods=["GET"])
def mass_action_wizard():
    """Paso 1 y 2: wizard de acción masiva."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    ids_param = request.args.get("ids", "")
    employee_ids = [i for i in ids_param.split(",") if i] if ids_param else []

    employees = []
    if employee_ids:
        for eid in employee_ids:
            emp = hr.get_employee(owner_uid, eid, sandbox=sandbox)
            if emp:
                employees.append(emp)

    action_type = request.args.get("action_type", "")

    employees_data = []
    for emp in employees:
        from app.services.payroll_service import PayrollService
        vac_days = PayrollService.calculate_vacation_days(emp.get("hireDate", ""))
        employees_data.append({
            "id": emp.get("id", ""),
            "fullName": emp.get("fullName", ""),
            "cedula": emp.get("cedula", ""),
            "position": emp.get("position", ""),
            "department": emp.get("department", ""),
            "area": emp.get("area", ""),
            "baseSalary": emp.get("baseSalary", 0),
            "status": emp.get("status", ""),
            "reportsTo": emp.get("reportsTo", ""),
            "vacationDays": vac_days,
        })

    all_employees_for_sup = hr.get_employees(owner_uid, sandbox=sandbox)
    supervisors = [e for e in all_employees_for_sup
                   if e.get("status") == "activo" and e.get("id") not in employee_ids]
    positions = hr.get_catalog(owner_uid, "positions", sandbox=sandbox)
    departments = hr.get_catalog(owner_uid, "departments", sandbox=sandbox)
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    frequency = config.get("payroll", {}).get("frequency", "mensual")

    try:
        now = date.today()
        payroll_periods = _generate_periods(frequency, now.year)
        if now.month < 12:
            payroll_periods += _generate_periods(frequency, now.year + 1)
    except Exception:
        payroll_periods = []

    return render_template(
        "rrhh/mass_action_wizard.html",
        active_page="rrhh_employees",
        action_type=action_type,
        action_types=MASS_ACTION_TYPES,
        employees=employees_data,
        employee_ids=employee_ids,
        supervisors=supervisors,
        positions=positions,
        departments=departments,
        payroll_periods=payroll_periods,
        now=datetime.now(),
    )


@web_rrhh_bp.route("/rrhh/employees/mass-action/preview", methods=["POST"])
def mass_action_preview():
    """Paso 4: previsualización (AJAX)."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    action_type = data.get("actionType", "")
    employee_ids = data.get("employeeIds", [])
    payload = data.get("payload", {})

    from app.services.mass_action_service import validate_action
    errors = validate_action(owner_uid, action_type, employee_ids, payload, sandbox=sandbox)

    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    employees = []
    for eid in employee_ids:
        emp = hr.get_employee(owner_uid, eid, sandbox=sandbox)
        if emp:
            vac_days = PayrollService.calculate_vacation_days(emp.get("hireDate", ""))
            employees.append({
                "id": emp.get("id", ""),
                "fullName": emp.get("fullName", ""),
                "cedula": emp.get("cedula", ""),
                "position": emp.get("position", ""),
                "department": emp.get("department", ""),
                "area": emp.get("area", ""),
                "baseSalary": emp.get("baseSalary", 0),
                "status": emp.get("status", ""),
                "vacationDays": vac_days,
            })

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "employees": employees,
        "affectedCount": len(employee_ids),
        "actionTypeLabel": MASS_ACTION_TYPES.get(action_type, {}).get("label", action_type),
        "payload": payload,
    }


@web_rrhh_bp.route("/rrhh/employees/mass-action/execute", methods=["POST"])
def mass_action_execute():
    """Paso 5: ejecutar la acción masiva."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    action_type = data.get("actionType", "")
    employee_ids = data.get("employeeIds", [])
    payload = data.get("payload", {})

    if not action_type or not employee_ids:
        return {"error": "Faltan datos requeridos."}, 400

    from app.services.mass_action_service import create_mass_action, execute_action, validate_action

    validation_errors = validate_action(owner_uid, action_type, employee_ids, payload, sandbox=sandbox)
    if validation_errors:
        return {"error": "Validación fallida.", "errors": validation_errors}, 400

    action = create_mass_action(owner_uid, action_type, employee_ids, payload, user_email, sandbox=sandbox)
    result = execute_action(owner_uid, action["id"], user_email, sandbox=sandbox)

    return {
        "actionId": result["id"],
        "status": result["status"],
        "successCount": result["successCount"],
        "errorCount": result["errorCount"],
        "totalEmployees": result["totalEmployees"],
    }


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>", methods=["GET"])
def mass_action_detail(action_id):
    """Detalle de una acción masiva específica."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    action = hr.get_mass_action(owner_uid, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    return render_template(
        "rrhh/mass_action_detail.html",
        active_page="rrhh_mass_actions",
        action=action,
        action_type_label=MASS_ACTION_TYPES.get(action.get("actionType", ""), {}).get("label", action.get("actionType", "")),
    )


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/errors.csv", methods=["GET"])
def mass_action_errors_csv(action_id):
    """Exportar los errores de una acción masiva a CSV."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    action = hr.get_mass_action(owner_uid, action_id, sandbox=sandbox)
    if not action:
        return {"error": "No encontrada"}, 404

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Empleado", "Cédula", "Campo", "Error"])
    for err in action.get("errorLog", []):
        writer.writerow([
            err.get("employeeName", ""),
            err.get("employeeId", ""),
            err.get("field", ""),
            err.get("message", ""),
        ])

    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"errores_accion_{action_id[:8]}.csv",
    )
