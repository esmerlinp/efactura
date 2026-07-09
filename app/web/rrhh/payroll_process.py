"""RRHH module — auto-extracted."""

from datetime import date, datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService
from app.services.payroll_ytd_service import get_ytd, save_ytd, accumulate_ytd
from app.services.payroll_static_data import DEFAULT_PAYROLL_CONFIG
from app.services.payroll_audit_service import log_action


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
               employees=employees, now=now,
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
                                       employees=employees, now=now,
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

        # ── Cargar reglas de cálculo configurables ──
        active_rules = hr.get_active_rules_for_scope(owner_uid, "global", sandbox=sandbox)
        if selected_group_id:
            group_rules = hr.get_active_rules_for_scope(owner_uid, "group", selected_group_id, sandbox=sandbox)
            active_rules.extend(group_rules)
            active_rules.sort(key=lambda r: r.get("priority", 999))

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

            # ── Evaluar reglas configurables para este empleado ──
            rule_result = None
            if active_rules:
                from app.services.payroll_rule_engine import PayrollRuleEngine
                emp_rules = list(active_rules)
                emp_specific = hr.get_active_rules_for_scope(owner_uid, "employee", emp_id, sandbox=sandbox)
                if emp_specific:
                    emp_rules.extend(emp_specific)
                    emp_rules.sort(key=lambda r: r.get("priority", 999))
                rule_result = PayrollRuleEngine.evaluate_rules(emp_rules, emp)
                if rule_result:
                    bonus += rule_result.get("bonus", 0)
                    commission += rule_result.get("commission", 0)
                    other_ded += rule_result.get("deduction", 0)
                    other_income += rule_result.get("other_income", 0)
                    if rule_result.get("overtime_rate") and not overtime:
                        overtime_rate_override = rule_result["overtime_rate"]

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

            # ── Procesar embargos salariales ──
            garnishments = hr.get_garnishments(owner_uid, employee_id=emp_id, sandbox=sandbox)
            if garnishments:
                from app.services.garnishment_service import GarnishmentService
                net_salary = line["netSalary"]
                g_result = GarnishmentService.process_all_garnishments(net_salary, garnishments)
                if g_result["totalDeduction"] > 0:
                    line["netSalary"] = g_result["remainingSalary"]
                    line["otherDeductions"] = round(line.get("otherDeductions", 0) + g_result["totalDeduction"], 2)
                    line["totalDeductions"] = round(line.get("totalDeductions", 0) + g_result["totalDeduction"], 2)
                    line["garnishmentDetails"] = g_result["details"]
                    for det in g_result["details"]:
                        hr.save_garnishment(owner_uid, det["garnishmentId"], {
                            "remainingBalance": det["remainingBalance"],
                            "status": "completed" if det["isCompleted"] else "active",
                        }, sandbox=sandbox)
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
            "totalGross": round(total_gross, 2),
            "totalNet": round(total_net, 2),
            "totalEmployerContrib": round(total_employer, 2),
            "processedDate": now.isoformat(),
            "notes": request.form.get("notes", "").strip(),
            "calculatedBy": session.get("user", {}).get("email", ""),
            "calculatedAt": now.isoformat(),
            "taxRatesSnapshot": tax_rates_data,
            "appliedRatesDate": now.isoformat(),
            "lineCount": len(lines),
            "statusHistory": [{
                "from": "borrador",
                "to": "calculada",
                "by": session.get("user", {}).get("email", ""),
                "at": now.isoformat(),
                "comment": "Nómina calculada",
            }],
        }
        hr.save_payroll_period(owner_uid, period_id, period_data, sandbox=sandbox)
        hr.save_payroll_lines_batch(owner_uid, period_id, lines, sandbox=sandbox)

        # ── Detección de anomalías ──
        emp_map = {e["id"]: e for e in period_employees}
        anomalies = PayrollService.detect_anomalies(lines, emp_map, owner_uid=owner_uid, sandbox=sandbox)

        from app.services.payroll_audit_service import log_action
        log_action(owner_uid, "calculate", "payroll_period", period_id,
                   session.get("user", {}).get("email", ""),
                   changes={"period": period_key, "employees": len(lines), "total_net": round(total_net, 2)}, sandbox=sandbox)

        for err in anomalies.get("errors", []):
            flash(f"[Error] {err}", "error")
        for warn in anomalies.get("warnings", []):
            flash(f"[Advertencia] {warn}", "warning")
        flash(f"Nómina {period_range or period_key} calculada: {len(lines)} empleados, neto RD$ {total_net:,.2f}.", "success")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                           employees=employees, now=now,
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


