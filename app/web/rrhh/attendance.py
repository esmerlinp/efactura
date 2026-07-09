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


