"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService


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

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    group_employee_counts = {
        g["id"]: len([e for e in employees if g["id"] in e.get("payrollGroupIds", [])])
        for g in payroll_groups
    }

    return render_template("rrhh/payroll_list.html", active_page="rrhh_payroll",
                           periods=periods, payroll_groups=payroll_groups,
                           filter_group=filter_group, group_map=group_map,
                           group_employee_counts=group_employee_counts)


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

    period["lines"] = PayrollService.get_period_lines(period, owner_uid=owner_uid, sandbox=sandbox)

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
    csv_content = PayrollService.generate_tss_csv(period, employees, owner_uid=owner_uid, sandbox=sandbox)

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
        resultado = PayrollService.generate_tss_autodeterminacion_xls(period, employees, employer_rnc=employer_rnc,
                                                                       owner_uid=owner_uid, sandbox=sandbox)
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        company = DatabaseService.get_company_profile(owner_uid)
        employer_rnc = (company.get("companyRNC", "") or "").replace("-", "").strip() if company else ""
        resultado = PayrollService.generate_tss_autodeterminacion(period, employees, employer_rnc=employer_rnc,
                                                                   owner_uid=owner_uid, sandbox=sandbox)
        mimetype = "text/plain"

    import io
    content = resultado["content"]
    if isinstance(content, str):
        content = content.encode("utf-8-sig")
    buffer = io.BytesIO(content)
    return send_file(buffer, mimetype=mimetype, as_attachment=True,
                     download_name=resultado["filename"])


