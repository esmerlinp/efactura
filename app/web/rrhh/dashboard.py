"""RRHH module — auto-extracted."""

import calendar
from datetime import datetime, date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
    get_locked_periods,
)
from app.services import hr_data_service as hr
from app.utils.hr_utils import is_active_equivalent
from app.services.payroll_service import PayrollService


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/dashboard")
def payroll_dashboard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    # Verificar onboarding
    config = hr.get_payroll_config(company_id, sandbox=sandbox)
    if not config.get("onboardingCompleted"):
        return redirect(url_for("web_rrhh.onboarding_guide"))

    employees = hr.get_employees(company_id, sandbox=sandbox)
    periods = hr.get_payroll_periods(company_id, sandbox=sandbox)
    user_name = session.get("user", {}).get("displayName", "")

    now = datetime.now()

    # ── Onboarding steps ──
    positions = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    departments = hr.get_catalog(company_id, "departments", sandbox=sandbox)
    onboard_steps = {
        "frequency": bool(config.get("payrollFrequency")),
        "catalogs": len(positions) > 0 and len(departments) > 0,
        "employees": len([e for e in employees if is_active_equivalent(e.get("status", ""))]) > 0,
        "concepts": True,
        "payroll": len(periods) > 0,
    }
    onboard_done_count = sum(1 for v in onboard_steps.values() if v)
    onboard_all_done = all(onboard_steps.values())

    # ── Greeting dinámico según hora del día ──
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
    payroll_groups = hr.get_payroll_groups(company_id, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))
    for g in payroll_groups:
        g["_employee_count"] = len([e for e in employees if g["id"] in e.get("payrollGroupIds", [])])
        g["_period_count"] = len([p for p in periods if p.get("payrollGroupId") == g["id"]])

    frequency = config.get("payrollFrequency", "mensual")

    # ═══════════════════════════════════════════════════════════════════════
    # FILTROS (año / grupo / período)
    # ═══════════════════════════════════════════════════════════════════════
    years_available = sorted({int(p.get("year", 0) or 0) for p in periods if p.get("year")} | {now.year}, reverse=True)
    selected_year = request.args.get("year", "")
    try:
        selected_year = int(selected_year) if selected_year else now.year
    except (TypeError, ValueError):
        selected_year = now.year

    selected_group_id = request.args.get("group_id", "all")
    selected_period_key = request.args.get("period_key", "")

    def _is_payroll_period(p):
        return p.get("status") not in ("borrador", "cancelada", "rechazada")

    filtered_periods = []
    for p in periods:
        if not _is_payroll_period(p):
            continue
        if selected_year and int(p.get("year", 0) or 0) != selected_year:
            continue
        if selected_group_id not in ("all", "", None) and p.get("payrollGroupId") != selected_group_id:
            continue
        if selected_period_key and p.get("periodKey") != selected_period_key:
            continue
        filtered_periods.append(p)
    filtered_periods.sort(key=lambda p: (p.get("year", 0) or 0, p.get("month", 0) or 0, p.get("processedDate", "")))

    def _cost(p):
        return float(p.get("totalGross", 0) or 0) + float(p.get("totalEmployerContrib", 0) or 0)

    # ── Totales acumulados del año (scope filtrado) ──
    year_cost = round(sum(_cost(p) for p in filtered_periods), 2)
    year_net = round(sum(p.get("totalNet", 0) for p in filtered_periods), 2)
    year_isr = round(sum(p.get("totalIsr", 0) for p in filtered_periods), 2)
    year_tss_employer = round(sum(p.get("totalTssEmployer", 0) for p in filtered_periods), 2)

    # ── Último período procesado + delta vs anterior ──
    latest_period = filtered_periods[-1] if filtered_periods else None
    prev_period = filtered_periods[-2] if len(filtered_periods) > 1 else None
    latest_cost = _cost(latest_period) if latest_period else 0.0
    latest_net = latest_period.get("totalNet", 0) if latest_period else 0.0
    cost_delta_pct = None
    if latest_period and prev_period:
        prev_cost = _cost(prev_period)
        if prev_cost:
            cost_delta_pct = round((latest_cost - prev_cost) / prev_cost * 100, 1)

    active_emps = [e for e in employees if is_active_equivalent(e.get("status", ""))]
    employee_count = len(active_emps)
    headcount_for_avg = latest_period.get("lineCount", 0) if latest_period else 0
    if not headcount_for_avg:
        headcount_for_avg = employee_count
    avg_cost_per_employee = round(latest_cost / headcount_for_avg, 2) if headcount_for_avg else 0.0

    # ── Período actual (label) ──
    today = date.today()
    current_period = ""
    if frequency in ("quincenal",):
        label_m = MONTHS_ES[today.month - 1]
        last_day = calendar.monthrange(today.year, today.month)[1]
        current_period = f"Q1: 1 {label_m} - 15 {label_m}" if today.day <= 15 else f"Q2: 16 {label_m} - {last_day} {label_m}"
    else:
        current_period = f"{MONTHS_ES[today.month - 1]} {today.year}"

    # ── Gráfica: Costo vs Pago (últimos 6 períodos del scope) ──
    chart_labels, costo_data, pago_data = [], [], []
    for p in filtered_periods[-6:]:
        label = p.get("periodRange") or p.get("periodKey", "")
        if len(label) > 14:
            parts = label.split(" - ")
            label = parts[0] if len(label) > 14 else label
        chart_labels.append(label)
        costo_data.append(round(_cost(p), 2))
        pago_data.append(round(p.get("totalNet", 0), 2))

    # ── Composición del costo (último período) ──
    cost_composition = {"labels": [], "values": [], "colors": []}
    has_composition = False
    if latest_period and ("totalIsr" in latest_period or "totalTssEmployee" in latest_period):
        isr = float(latest_period.get("totalIsr", 0) or 0)
        tss_emp = float(latest_period.get("totalTssEmployee", 0) or 0)
        employer = float(latest_period.get("totalEmployerContrib", 0) or 0)
        neto = float(latest_period.get("totalNet", 0) or 0)
        otras = max(0.0, float(latest_period.get("totalDeducciones", 0) or 0) - isr - tss_emp)
        comp = [
            ("Neto a pagar", neto, "rgba(16,185,129,0.85)"),
            ("ISR retenido", isr, "rgba(139,92,246,0.85)"),
            ("TSS empleado", tss_emp, "rgba(59,130,246,0.85)"),
            ("Otras deducciones", otras, "rgba(148,163,184,0.85)"),
            ("Aporte empleador", employer, "rgba(249,115,22,0.85)"),
        ]
        cost_composition["labels"] = [c[0] for c in comp]
        cost_composition["values"] = [round(c[1], 2) for c in comp]
        cost_composition["colors"] = [c[2] for c in comp]
        has_composition = sum(cost_composition["values"]) > 0

    # ── Desglose por departamento (último período) ──
    dept_labels, dept_cost, dept_net = [], [], []
    if latest_period and latest_period.get("departmentBreakdown"):
        top = latest_period["departmentBreakdown"][:8]
        dept_labels = [d.get("department", "") for d in top]
        dept_cost = [d.get("cost", 0) for d in top]
        dept_net = [d.get("net", 0) for d in top]

    # ── Altas y bajas por mes (año seleccionado, eje continuo) ──
    hiring_by_month = {}
    termination_by_month = {}
    for emp in employees:
        try:
            hd = emp.get("hireDate", "")
            if hd:
                dt = datetime.strptime(hd[:10], "%Y-%m-%d")
                if dt.year == selected_year:
                    hiring_by_month[dt.month] = hiring_by_month.get(dt.month, 0) + 1
        except (ValueError, TypeError):
            pass
        try:
            td = emp.get("terminationDate", "")
            if td and emp.get("status") == "inactivo":
                dt = datetime.strptime(td[:10], "%Y-%m-%d")
                if dt.year == selected_year:
                    termination_by_month[dt.month] = termination_by_month.get(dt.month, 0) + 1
        except (ValueError, TypeError):
            pass

    rotation_labels, rotation_hires, rotation_terms = [], [], []
    for m in range(1, 13):
        if m in hiring_by_month or m in termination_by_month:
            rotation_labels.append(MONTHS_ES[m - 1])
            rotation_hires.append(hiring_by_month.get(m, 0))
            rotation_terms.append(termination_by_month.get(m, 0))

    # ── Períodos recientes ──
    recent_periods = list(reversed(filtered_periods[-5:]))

    # ── Topes legales (estáticos) ──
    indicators = {
        "year": selected_year,
        "minSalary": config.get("minSalary", 23223.00),
        "afpTotal": config.get("afpTotal", 464460.00),
        "sfsTotal": config.get("sfsTotal", 232230.00),
        "srlTotal": config.get("srlTotal", 92892.40),
    }

    # ── Quick actions: grupos pendientes de calcular este mes ──
    current_year = today.year
    current_month = today.month
    pending_groups = []
    for g in payroll_groups:
        if not g.get("isActive", True):
            continue
        freq = g.get("frequency", "mensual")
        gid = g["id"]
        has_current = False
        if freq == "mensual":
            expected_key = f"{current_year}-{current_month:02d}-M"
            has_current = any(
                p.get("periodKey") == expected_key and p.get("payrollGroupId") == gid
                for p in periods
            )
        else:
            expected_key1 = f"{current_year}-{current_month:02d}-1"
            expected_key2 = f"{current_year}-{current_month:02d}-2"
            has_current = any(
                p.get("periodKey") in (expected_key1, expected_key2)
                and p.get("payrollGroupId") == gid
                for p in periods
            )
        if not has_current and g["_employee_count"] > 0:
            suggested = f"{current_year}-{current_month:02d}-M" if freq == "mensual" else f"{current_year}-{current_month:02d}-1"
            pending_groups.append({"group": g, "suggestedPeriod": suggested})

    # ── Marcar grupos cuyo período sugerido está bloqueado secuencialmente ──
    for entry in pending_groups:
        gid = entry["group"]["id"]
        freq = entry["group"].get("frequency", "mensual")
        try:
            locked, open_label, _closed = get_locked_periods(
                company_id, gid, _generate_periods(freq, current_year), sandbox=sandbox)
        except Exception:
            locked, open_label = set(), None
        if entry["suggestedPeriod"] in locked:
            entry["blocked"] = True
            entry["blocked_by"] = open_label
        else:
            entry["blocked"] = False

    # ── Opciones de período para el filtro ──
    period_options = []
    _seen_keys = set()
    for p in sorted(periods, key=lambda x: (x.get("year", 0) or 0, x.get("month", 0) or 0, x.get("processedDate", ""))):
        key = p.get("periodKey", "")
        if not key or key in _seen_keys:
            continue
        if selected_year and int(p.get("year", 0) or 0) != selected_year:
            continue
        if selected_group_id not in ("all", "", None) and p.get("payrollGroupId") != selected_group_id:
            continue
        _seen_keys.add(key)
        period_options.append({"key": key, "label": p.get("periodRange") or key})
    period_options.reverse()

    # ── Nómina por grupo (scope año seleccionado) ──
    group_summary = []
    for g in payroll_groups:
        gps = [p for p in periods if p.get("payrollGroupId") == g["id"] and _is_payroll_period(p) and int(p.get("year", 0) or 0) == selected_year]
        if not gps:
            continue
        gps.sort(key=lambda p: (p.get("month", 0) or 0, p.get("processedDate", "")))
        group_summary.append({
            "name": g.get("name", "Sin nombre"),
            "frequency": g.get("frequency", "mensual"),
            "employees": g["_employee_count"],
            "period_count": len(gps),
            "cost": round(sum(_cost(p) for p in gps), 2),
            "net": round(sum(p.get("totalNet", 0) for p in gps), 2),
            "latest_status": gps[-1].get("status", ""),
        })
    group_summary.sort(key=lambda x: -x["cost"])

    # ── Offboarding pipeline ──
    offboarding_pipeline = []
    offboarding_pipeline_total = 0
    try:
        from app.services.offboarding_service import OffboardingService
        from app.models.offboarding import OFFBOARDING_STATES
        osvc = OffboardingService(company_id, sandbox)
        all_offboard = osvc.list_requests(limit=200)
        non_terminal = [r for r in all_offboard if r.get("status") not in ("completed", "cancelled", "rejected")]
        pipeline_statuses = [
            ("draft", "secondary"),
            ("pending_supervisor_approval", "info"),
            ("pending_hr_approval", "warning"),
            ("approved", "primary"),
            ("pending_settlement", "info"),
            ("pending_assets", "warning"),
            ("pending_payment", "warning"),
            ("pending_documents", "info"),
            ("pending_tss", "info"),
        ]
        for s_key, s_color in pipeline_statuses:
            count = len([r for r in non_terminal if r.get("status") == s_key])
            if count > 0:
                st_cfg = OFFBOARDING_STATES.get(s_key, {})
                offboarding_pipeline.append({
                    "label": st_cfg.get("label", s_key),
                    "count": count,
                    "color": s_color,
                    "key": s_key,
                })
        offboarding_pipeline_total = len(non_terminal)
    except Exception:
        offboarding_pipeline = []

    return render_template("rrhh/payroll_dashboard.html", active_page="rrhh_dashboard",
                           user_name=user_name, greeting=greeting, employee_count=employee_count,
                           current_period=current_period,
                           year_cost=year_cost, year_net=year_net, year_isr=year_isr,
                           year_tss_employer=year_tss_employer,
                           latest_cost=latest_cost, latest_net=latest_net,
                           latest_period=latest_period, cost_delta_pct=cost_delta_pct,
                           avg_cost_per_employee=avg_cost_per_employee,
                           steps_completed=steps, progress_percent=progress_percent,
                           chart_labels=chart_labels, costo_data=costo_data, pago_data=pago_data,
                           cost_composition=cost_composition, has_composition=has_composition,
                           dept_labels=dept_labels, dept_cost=dept_cost, dept_net=dept_net,
                           rotation_labels=rotation_labels, rotation_hires=rotation_hires,
                           rotation_terms=rotation_terms,
                           recent_periods=recent_periods, indicators=indicators,
                           onboard_steps=onboard_steps, onboard_done_count=onboard_done_count,
                           onboard_all_done=onboard_all_done,
                           payroll_groups=payroll_groups, payroll_frequency=frequency,
                           pending_groups=pending_groups, group_summary=group_summary,
                           years_available=years_available, selected_year=selected_year,
                           selected_group_id=selected_group_id, selected_period_key=selected_period_key,
                           period_options=period_options,
                           offboarding_pipeline=offboarding_pipeline,
                           offboarding_pipeline_total=offboarding_pipeline_total)


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


