"""RRHH module — auto-extracted."""

from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_ytd_service import get_ytd
from app.services.payroll_service import PayrollService
import csv, io


def _enrich_periods(periods, owner_uid, sandbox):
    """Inyecta líneas desde subcolección a cada período para compatibilidad con templates."""
    for p in periods:
        p["lines"] = PayrollService.get_period_lines(p, owner_uid=owner_uid, sandbox=sandbox)
    return periods


def _enrich_period(period, owner_uid, sandbox):
    """Inyecta líneas desde subcolección a un período."""
    if period:
        period["lines"] = PayrollService.get_period_lines(period, owner_uid=owner_uid, sandbox=sandbox)
    return period


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
    periods = _enrich_periods(periods, owner_uid, sandbox)
    periods = _enrich_periods(periods, owner_uid, sandbox)
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
    periods = _enrich_periods(periods, owner_uid, sandbox)
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
    periods = _enrich_periods(periods, owner_uid, sandbox)
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
    periods = _enrich_periods(periods, owner_uid, sandbox)
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
    period = _enrich_period(period, owner_uid, sandbox)
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
    period = _enrich_period(period, owner_uid, sandbox)
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
    periods = _enrich_periods(periods, owner_uid, sandbox)
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
    periods = _enrich_periods(periods, owner_uid, sandbox)
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
# WHAT-IF ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/reports/what-if")
def report_what_if():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    scenario_type = request.args.get("type", "")
    value = float(request.args.get("value", 0) or 0)
    filter_dept = request.args.get("department", "")
    filter_area = request.args.get("area", "")

    all_employees = hr.get_employees(owner_uid, sandbox=sandbox)
    tax_rates = hr.get_tax_rates(owner_uid, sandbox=sandbox)
    result = None
    departments = sorted(set(e.get("department", e.get("area", "General")) for e in all_employees if e.get("department") or e.get("area")))

    if scenario_type and value:
        scenario = {
            "type": scenario_type,
            "value": value,
            "filter_department": filter_dept,
            "filter_area": filter_area,
        }
        result = PayrollService.what_if_analysis(all_employees, scenario, tax_rates=tax_rates)

    return render_template("rrhh/reports/what_if.html", active_page="rrhh_reports",
                           result=result, departments=departments,
                           scenario_type=scenario_type, value=value,
                           filter_dept=filter_dept, filter_area=filter_area)


# ═══════════════════════════════════════════════════════════════════════════
# RETROACTIVE PAY CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/retroactive", methods=["GET", "POST"])
def employee_retroactive_pay(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    result = None
    if request.method == "POST":
        new_salary = float(request.form.get("new_salary", 0) or 0)
        effective_date = request.form.get("effective_date", "")
        tax_rates = hr.get_tax_rates(owner_uid, sandbox=sandbox)
        salary_history = hr.get_salary_history(owner_uid, employee_id, sandbox=sandbox)

        result = PayrollService.calculate_retroactive_pay(
            employee, salary_history, new_salary, effective_date, tax_rates=tax_rates
        )

    salary_history = hr.get_salary_history(owner_uid, employee_id, sandbox=sandbox)
    return render_template("rrhh/employee_retroactive.html", active_page="rrhh_employees",
                           employee=employee, result=result, salary_history=salary_history)


# ═══════════════════════════════════════════════════════════════════════════
# VALIDACIÓN IR-18
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/reports/ir18/validation")
def report_ir18_validation():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_service import PayrollService
    from datetime import date

    year = int(request.args.get("year", date.today().year))
    result = PayrollService.validate_ir18_readiness(owner_uid, year=year, sandbox=sandbox)

    return render_template("rrhh/reports/ir18_validation.html", active_page="rrhh_reports",
                           result=result, year=year)


