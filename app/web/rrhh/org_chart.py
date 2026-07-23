"""RRHH module — auto-extracted."""

import calendar
from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


@web_rrhh_bp.route("/rrhh/org-chart")
def org_chart():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employees = [e for e in hr.get_employees(company_id, sandbox=sandbox) if e.get("status") == "activo"]
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
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    try:
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))
    except (ValueError, TypeError):
        year, month = date.today().year, date.today().month

    vacations = hr.get_vacation_requests(company_id, sandbox=sandbox)
    leaves = hr.get_leave_requests(company_id, sandbox=sandbox)
    employees = {e["id"]: e for e in hr.get_employees(company_id, sandbox=sandbox)}

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


