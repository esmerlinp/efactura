"""RRHH module — auto-extracted."""

import calendar
from datetime import datetime, date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/dashboard")
def payroll_dashboard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
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

    # ── Quick actions: grupos pendientes de calcular este mes ──
    current_year = now.year
    current_month = now.month
    pending_groups = []
    for g in payroll_groups:
        if not g.get("isActive", True):
            continue
        freq = g.get("frequency", "mensual")
        gid = g["id"]
        has_current = False
        if freq == "mensual":
            expected_key = f"{current_year}-{current_month:02d}-M"
        else:
            expected_key1 = f"{current_year}-{current_month:02d}-1"
            expected_key2 = f"{current_year}-{current_month:02d}-2"
            has_current = any(
                p.get("periodKey") in (expected_key1, expected_key2)
                and p.get("payrollGroupId") == gid
                for p in periods
            )
            if not has_current and g["_employee_count"] > 0:
                pending_groups.append({
                    "group": g,
                    "suggestedPeriod": f"{current_year}-{current_month:02d}-1",
                })
            continue
        has_current = any(
            p.get("periodKey") == expected_key and p.get("payrollGroupId") == gid
            for p in periods
        )
        if not has_current and g["_employee_count"] > 0:
            pending_groups.append({
                "group": g,
                "suggestedPeriod": expected_key,
            })

    # ── Periodos procesados este mes ──
    month_periods = [p for p in periods if p.get("year") == current_year and p.get("month") == current_month]
    month_total_net = sum(p.get("totalNet", 0) for p in month_periods)
    month_total_gross = sum(p.get("totalGross", 0) for p in month_periods)

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
                           payroll_groups=payroll_groups, payroll_frequency=frequency,
                           pending_groups=pending_groups, month_periods=month_periods,
                           month_total_net=month_total_net, month_total_gross=month_total_gross,
                           current_month_name=MONTHS_ES[current_month - 1])


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


