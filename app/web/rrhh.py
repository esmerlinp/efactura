"""Blueprint de RRHH: empleados, asistencia, vacaciones, permisos, nómina, evaluaciones, capacitaciones."""

import uuid
import calendar
from datetime import datetime, timezone, date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file

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


def _generate_periods(frequency: str, year: int = None):
    """Genera lista de períodos disponibles para el año."""
    if year is None:
        year = date.today().year
    periods = []
    if frequency == "quincenal":
        for m in range(1, 13):
            last_day = calendar.monthrange(year, m)[1]
            mid = 15
            label_m = MONTHS_ES[m - 1]
            # Primera quincena: 1 al 15
            periods.append({
                "key": f"{year}-{m:02d}-1",
                "label": f"1 {label_m} - 15 {label_m}",
                "start": f"{year}-{m:02d}-01",
                "end": f"{year}-{m:02d}-{mid}",
            })
            # Segunda quincena: 16 al último día
            periods.append({
                "key": f"{year}-{m:02d}-2",
                "label": f"16 {label_m} - {last_day} {label_m}",
                "start": f"{year}-{m:02d}-16",
                "end": f"{year}-{m:02d}-{last_day}",
            })
    else:
        for m in range(1, 13):
            label_m = MONTHS_ES[m - 1]
            last_day = calendar.monthrange(year, m)[1]
            periods.append({
                "key": f"{year}-{m:02d}",
                "label": f"{label_m} {year}",
                "start": f"{year}-{m:02d}-01",
                "end": f"{year}-{m:02d}-{last_day}",
            })
    return periods


# ═══════════════════════════════════════════════════════════════════════════
# ONBOARDING — Frecuencia de pago
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/setup", methods=["GET", "POST"])
def payroll_setup():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    if request.method == "POST":
        frequency = request.form.get("frequency", "")
        if frequency in ("quincenal", "mensual"):
            config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
            config["payrollFrequency"] = frequency
            config["onboardingCompleted"] = True
            hr.save_payroll_config(owner_uid, config, sandbox=sandbox)
            flash("¡Frecuencia de nómina configurada exitosamente!", "success")
        return redirect(url_for("web_rrhh.payroll_dashboard"))

    return render_template("rrhh/payroll_onboarding.html", active_page="rrhh_payroll")


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
        return redirect(url_for("web_rrhh.payroll_setup"))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    user_name = session.get("user", {}).get("displayName", "")

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

    # Periodo actual
    frequency = config.get("payrollFrequency", "mensual")
    now = date.today()
    current_period = ""
    if frequency == "quincenal":
        day = now.day
        label_m = MONTHS_ES[now.month - 1]
        last_day = calendar.monthrange(now.year, now.month)[1]
        if day <= 15:
            current_period = f"1 {label_m} - 15 {label_m}"
        else:
            current_period = f"16 {label_m} - {last_day} {label_m}"
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

    return render_template("rrhh/payroll_dashboard.html", active_page="rrhh_payroll",
                           user_name=user_name, greeting=greeting, employee_count=len(active_emps),
                           current_period=current_period,
                           total_pago=total_pago, total_costo=total_costo,
                           steps_completed=steps, progress_percent=progress_percent,
                           chart_labels=chart_labels, costo_data=costo_data, pago_data=pago_data,
                           hiring_labels=hiring_labels, hiring_data=hiring_data,
                           recent_periods=recent, indicators=indicators)


# ═══════════════════════════════════════════════════════════════════════════
# REDIRECT: /rrhh/payroll → dashboard (o onboarding)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll")
def payroll_redirect():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return redirect(url_for("web_rrhh.payroll_dashboard"))


# ═══════════════════════════════════════════════════════════════════════════
# EMPLEADOS — CRUD + Organigrama
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
            "idNumber": request.form.get("idNumber", "").strip(),
            "cedula": request.form.get("idNumber", "").strip(),
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
            "phone": request.form.get("phone", "").strip(),
            "address": request.form.get("address", "").strip(),
            "municipality": request.form.get("municipality", "").strip(),
            "contractType": request.form.get("contractType", "").strip(),
            "paymentFrequency": request.form.get("paymentFrequency", "").strip(),
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

    return render_template("rrhh/employee_form.html", active_page="rrhh_employees", employee=None,
                           id_types=ID_TYPES, municipios=MUNICIPIOS_RD,
                           contract_types=contract_types, areas=areas,
                           workdays=WORKDAYS, payment_methods=PAYMENT_METHODS,
                           bancos=BANCOS_RD, account_types=ACCOUNT_TYPES,
                           frequencies=PAYROLL_FREQUENCIES,
                           supervisors=supervisors,
                           positions=positions, departments=departments)


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
            "idNumber": request.form.get("idNumber", "").strip(),
            "cedula": request.form.get("idNumber", "").strip(),
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
            "salary": float(request.form.get("salary", 0) or 0),
            "baseSalary": float(request.form.get("salary", 0) or 0),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "address": request.form.get("address", "").strip(),
            "municipality": request.form.get("municipality", "").strip(),
            "contractType": request.form.get("contractType", "").strip(),
            "paymentFrequency": request.form.get("paymentFrequency", "").strip(),
            "workday": request.form.get("workday", "completa").strip(),
            "isVigilante": request.form.get("isVigilante") == "si",
            "tssKey": request.form.get("tssKey", "").strip(),
            "paymentMethod": request.form.get("paymentMethod", "").strip(),
            "accountNumber": request.form.get("accountNumber", "").strip(),
            "bank": request.form.get("bank", "").strip(),
            "accountType": request.form.get("accountType", "").strip(),
            "emergencyContact": request.form.get("emergencyContact", "").strip(),
            "emergencyPhone": request.form.get("emergencyPhone", "").strip(),
            "afpProvider": request.form.get("afpProvider", "").strip(),
            "notes": request.form.get("notes", "").strip(),
            "gender": request.form.get("gender", "").strip(),
            "birthDate": request.form.get("birthDate", "").strip(),
            "probationEndDate": request.form.get("probationEndDate", "").strip(),
            "reportsTo": request.form.get("reportsTo", "").strip(),
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

        # ── Historial de salarios: si cambió, registrar ──
        new_salary = float(request.form.get("salary", 0) or 0)
        old_salary = float(employee.get("baseSalary", 0))
        if new_salary > 0 and new_salary != old_salary:
            hr.close_previous_salary(owner_uid, employee_id, date.today().isoformat(), sandbox=sandbox)
            history_id = str(uuid.uuid4())
            hr.save_salary_history_entry(owner_uid, {
                "id": history_id,
                "employeeId": employee_id,
                "amount": new_salary,
                "previousAmount": old_salary,
                "effectiveDate": date.today().isoformat(),
                "endDate": "",
                "reason": "Actualización de salario",
                "approvedBy": session.get("user", {}).get("email", ""),
                "createdAt": date.today().isoformat(),
            }, sandbox=sandbox)

        from app.services.payroll_audit_service import log_action
        log_action(owner_uid, "update", "employee", employee_id,
                   session.get("user", {}).get("email", ""),
                   changes={"salary_old": old_salary, "salary_new": new_salary}, sandbox=sandbox)

        flash("Empleado actualizado exitosamente.", "success")
        return redirect(url_for("web_rrhh.employee_list"))

    ref_data = hr.get_reference_data(owner_uid, sandbox=sandbox)
    contract_types = ref_data.get("contractTypes", CONTRACT_TYPES)
    areas = ref_data.get("areas", AREAS)
    supervisors = [e for e in hr.get_employees(owner_uid, sandbox=sandbox)
                   if e.get("status") == "activo" and e.get("id") != employee_id]
    positions = hr.get_catalog(owner_uid, "positions", sandbox=sandbox)
    departments = hr.get_catalog(owner_uid, "departments", sandbox=sandbox)

    return render_template("rrhh/employee_form.html", active_page="rrhh_employees", employee=employee,
                           id_types=ID_TYPES, municipios=MUNICIPIOS_RD,
                           contract_types=contract_types, areas=areas,
                           workdays=WORKDAYS, payment_methods=PAYMENT_METHODS,
                           bancos=BANCOS_RD, account_types=ACCOUNT_TYPES,
                           frequencies=PAYROLL_FREQUENCIES,
                           supervisors=supervisors,
                           positions=positions, departments=departments)


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

    return render_template("rrhh/employee_view.html", active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee), vacation_days=vacation_days,
                           severance=severance, evaluations=evals, trainings=trainings,
                           documents=docs)


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
    return render_template("rrhh/employee_salary_history.html", active_page="rrhh_employees",
                           employee=employee, history=history, frequencies=PAYROLL_FREQUENCIES)


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

    return render_template("rrhh/org_chart.html", active_page="rrhh_orgchart",
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
                          "start": v.get("startDate", ""), "end": v.get("endDate", ""),
                          "days": v.get("days", 0)})
    for l in leaves:
        if l.get("status") == "aprobada":
            events.append({"type": "leave", "employeeName": l.get("employeeName", ""),
                          "start": l.get("startDate", ""), "end": l.get("endDate", ""),
                          "days": l.get("days", 0), "leaveType": l.get("leaveType", "")})

    return render_template("rrhh/team_calendar.html", active_page="rrhh_calendar",
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
    return render_template("rrhh/vacation_list.html", active_page="rrhh_vacations", requests=requests)


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

    return render_template("rrhh/vacation_form.html", active_page="rrhh_vacations", employees=employees)


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
    return render_template("rrhh/leave_list.html", active_page="rrhh_leaves", requests=requests)


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

    return render_template("rrhh/leave_form.html", active_page="rrhh_leaves", employees=employees)


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
        return redirect(url_for("web_rrhh.payroll_setup"))

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]
    frequency = config.get("payrollFrequency", "mensual")
    now = date.today()
    available_periods = _generate_periods(frequency, now.year)

    if request.method == "POST":
        period_key = request.form.get("period_key", "")
        if not period_key:
            flash("Debes seleccionar un período.", "error")
            return redirect(url_for("web_rrhh.payroll_new"))

        # ── Anti-duplicados: verificar si ya existe nómina para este período ──
        existing = hr.get_payroll_period_by_key(owner_uid, period_key, sandbox=sandbox)
        if existing:
            flash(f"Ya existe una nómina procesada para el período «{period_key}». "
                  "Si necesitas corregirla, contacta al administrador.", "error")
            return redirect(url_for("web_rrhh.payroll_new"))

        # Parse period key
        parts = period_key.split("-")
        year = int(parts[0])
        month = int(parts[1])
        is_quincenal = len(parts) == 3

        # Get period metadata
        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        period_range = period_info["label"] if period_info else ""
        start_date = period_info["start"] if period_info else ""
        end_date = period_info["end"] if period_info else ""

        period_type = "quincenal" if is_quincenal else "mensual"
        period_id = str(uuid.uuid4())
        lines = []

        total_gross = 0.0
        total_net = 0.0
        total_employer = 0.0

        for emp in employees:
            emp_id = emp["id"]
            base = float(emp.get("baseSalary", 0))
            overtime = float(request.form.get(f"overtime_{emp_id}", 0) or 0)
            commission = float(request.form.get(f"commission_{emp_id}", 0) or 0)
            bonus = float(request.form.get(f"bonus_{emp_id}", 0) or 0)
            other_income = float(request.form.get(f"other_income_{emp_id}", 0) or 0)
            other_ded = float(request.form.get(f"other_ded_{emp_id}", 0) or 0)

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
                period_type=period_type,
                prorated_salary=prorated,
            )
            line = {
                **calc,
                "employeeId": emp_id,
                "employeeName": emp.get("fullName", ""),
                "cedula": emp.get("cedula", ""),
                "position": emp.get("position", ""),
                "department": emp.get("department", ""),
            }
            lines.append(line)
            total_gross += line["totalIncome"]
            total_net += line["netSalary"]
            total_employer += line["totalEmployerContrib"]

            # ── YTD: acumulación anual por empleado ──
            try:
                ytd = get_ytd(owner_uid, emp_id, year, sandbox=sandbox)
                ytd = accumulate_ytd(ytd, line, period_factor=24 if is_quincenal else 12)
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

    return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll_new",
                           employees=employees, now=datetime.now,
                           available_periods=available_periods, frequency=frequency,
                           show_christmas_bonus=(now.month >= 11))  # Nov-Dic


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

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]
    frequency = config.get("payrollFrequency", "mensual")
    now = date.today()
    available_periods = _generate_periods(frequency, now.year)

    simulation = None

    if request.method == "POST":
        period_key = request.form.get("period_key", "")
        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        start_date = period_info["start"] if period_info else ""
        end_date = period_info["end"] if period_info else ""
        is_quincenal = len(period_key.split("-")) == 3
        period_type = "quincenal" if is_quincenal else "mensual"

        lines = []
        total_gross = 0.0
        total_net = 0.0
        total_employer = 0.0
        total_costo = 0.0

        for emp in employees:
            emp_id = emp["id"]
            base = float(emp.get("baseSalary", 0))
            overtime = float(request.form.get(f"overtime_{emp_id}", 0) or 0)
            commission = float(request.form.get(f"commission_{emp_id}", 0) or 0)
            bonus = float(request.form.get(f"bonus_{emp_id}", 0) or 0)
            other_income = float(request.form.get(f"other_income_{emp_id}", 0) or 0)
            other_ded = float(request.form.get(f"other_ded_{emp_id}", 0) or 0)

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
                period_type=period_type, prorated_salary=prorated,
            )
            calc["employeeName"] = emp.get("fullName", "")
            calc["employeeId"] = emp_id
            calc["position"] = emp.get("position", "")
            lines.append(calc)
            total_gross += calc["totalIncome"]
            total_net += calc["netSalary"]
            total_employer += calc["totalEmployerContrib"]
            total_costo += calc["totalIncome"] + calc["totalEmployerContrib"]

        simulation = {
            "period_range": period_info["label"] if period_info else period_key,
            "period_type": period_type,
            "employee_count": len(employees),
            "total_gross": round(total_gross, 2),
            "total_net": round(total_net, 2),
            "total_employer": round(total_employer, 2),
            "total_costo": round(total_costo, 2),
            "lines": lines,
        }

    return render_template("rrhh/payroll_simulate.html", active_page="rrhh_payroll_simulate",
                           employees=employees, available_periods=available_periods,
                           frequency=frequency, simulation=simulation)


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
    return render_template("rrhh/payroll_list.html", active_page="rrhh_payroll_history", periods=periods)


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
    return render_template("rrhh/catalog_list.html", active_page="rrhh_catalogs",
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
    return render_template("rrhh/concepts/list.html", active_page="rrhh_concepts", concepts=concepts)


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
    return render_template("rrhh/concepts/form.html", active_page="rrhh_payroll", concept=None)


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
    return render_template("rrhh/concepts/form.html", active_page="rrhh_payroll", concept=concept)


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
    return render_template("rrhh/audit_log.html", active_page="rrhh_audit",
                           logs=logs, entity=entity, limit=limit)


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
# WORKFLOW DE APROBACIÓN Y CONTABILIZACIÓN
# ═══════════════════════════════════════════════════════════════════════════

_VALID_TRANSITIONS = {
    "borrador":     ["calculada"],
    "calculada":    ["validada", "borrador"],
    "validada":     ["aprobada", "calculada"],
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
        now_str = date.today().isoformat()
        employees_list = hr.get_employees(owner_uid, sandbox=sandbox)
        emp_map = {e["id"]: e for e in employees_list}
        acct_lines = PayrollService.build_payroll_accounting_lines(period, employees=emp_map)
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

    if period.get("status") in ("contabilizada", "pagada", "cerrada"):
        flash("No se puede recalcular una nómina ya contabilizada o cerrada. Debe revertirla primero.", "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    ok, msg = _transition(period, "borrador", "Recálculo solicitado",
                          owner_uid=owner_uid, sandbox=sandbox)
    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(owner_uid, period_id, period, sandbox=sandbox)
        flash("Nómina revertida a borrador. Puede recalcularla desde «Calcular nómina».", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


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
    return render_template("rrhh/evaluation_list.html", active_page="rrhh_evaluations",
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

    return render_template("rrhh/evaluation_form.html", active_page="rrhh_evaluations", employees=employees, now=datetime.now)


@web_rrhh_bp.route("/rrhh/trainings")
def training_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    trainings = hr.get_trainings(owner_uid, sandbox=sandbox)
    trainings.sort(key=lambda t: t.get("date", ""), reverse=True)
    return render_template("rrhh/training_list.html", active_page="rrhh_trainings", trainings=trainings)


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

    return render_template("rrhh/training_form.html", active_page="rrhh_trainings", employees=employees, now=datetime.now)
