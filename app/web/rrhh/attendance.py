"""RRHH module — auto-extracted."""

import calendar
import uuid
from datetime import date, datetime, timezone
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
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    now = datetime.now(timezone.utc)
    try:
        sel_month = int(request.args.get("month", now.month))
        sel_year = int(request.args.get("year", now.year))
    except ValueError:
        sel_month, sel_year = now.month, now.year

    all_employees = [e for e in hr.get_employees(company_id, sandbox=sandbox) if e.get("status") == "activo"]
    records = hr.get_attendance_records(company_id, sandbox=sandbox)

    # ── Filtros ──
    search = request.args.get("search", "").strip().lower()
    filter_area = request.args.get("area", "").strip()
    filter_position = request.args.get("position", "").strip()
    if search:
        all_employees = [e for e in all_employees if
                         search in (e.get("fullName", "") + " " +
                                   e.get("cedula", "") + " " +
                                   e.get("idNumber", "") + " " +
                                   e.get("position", "")).lower()]
    if filter_area:
        all_employees = [e for e in all_employees if e.get("area", "") == filter_area or e.get("department", "") == filter_area]
    if filter_position:
        all_employees = [e for e in all_employees if e.get("position", "") == filter_position]

    areas_set = sorted(set(e.get("area", "") or e.get("department", "") for e in all_employees if e.get("area") or e.get("department")))
    positions_set = sorted(set(e.get("position", "") for e in all_employees if e.get("position")))

    # ── Paginación ──
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(10, min(100, int(request.args.get("per_page", 25))))
    except (ValueError, TypeError):
        page, per_page = 1, 25
    total = len(all_employees)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    employees = all_employees[start:start + per_page]

    if request.method == "POST":
        for emp in all_employees:
            emp_id = emp["id"]
            status = request.form.get(f"att_{emp_id}", "")
            check_in = request.form.get(f"checkin_{emp_id}", "")
            check_out = request.form.get(f"checkout_{emp_id}", "")
            att_date = request.form.get("att_date", now.strftime("%Y-%m-%d"))
            if status:
                rec_id = str(uuid.uuid4())
                hr.save_attendance_record(company_id, rec_id, {
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
                           sel_month=sel_month, sel_year=sel_year, page=page,
                           total_pages=total_pages, total=total, per_page=per_page,
                           search=request.args.get("search", ""),
                           filter_area=filter_area, filter_position=filter_position,
                           areas_set=areas_set, positions_set=positions_set)


