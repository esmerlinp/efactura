"""RRHH module — auto-extracted."""

from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.hr_notifications import notify_vacation_approved, notify_leave_approved


# ═══════════════════════════════════════════════════════════════════════════
# VACACIONES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/vacations")
def vacation_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    requests = hr.get_vacation_requests(company_id, sandbox=sandbox)
    requests.sort(key=lambda r: r.get("createdDate", ""), reverse=True)
    return render_template("rrhh/vacation_list.html", active_page="rrhh_attendance", requests=requests)


@web_rrhh_bp.route("/rrhh/vacations/new", methods=["GET", "POST"])
def vacation_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employees = [e for e in hr.get_employees(company_id, sandbox=sandbox) if e.get("status") == "activo"]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(company_id, emp_id, sandbox=sandbox)
        if not employee:
            flash("Empleado no encontrado.", "error")
            return redirect(url_for("web_rrhh.vacation_list"))

        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        business_days = PayrollService.calculate_business_days(start_date, end_date)
        taken_days = sum(
            r.get("days", 0) for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
            if r.get("employeeId") == emp_id and r.get("status") == "aprobada"
        )
        remaining = PayrollService.calculate_vacation_days(employee.get("hireDate", ""), taken_days=taken_days)

        req_id = str(uuid.uuid4())
        hr.save_vacation_request(company_id, req_id, {
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
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    req = hr.get_vacation_request(company_id, request_id, sandbox=sandbox)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.vacation_list"))

    if action in ("approve", "rechazar"):
        req["status"] = "aprobada" if action == "approve" else "rechazada"
        req["approvedDate"] = date.today().isoformat()
        req["approvedBy"] = session["user"].get("email", "")
        hr.save_vacation_request(company_id, request_id, req, sandbox=sandbox)

        # Notificar al empleado si se aprobó
        if action == "approve":
            try:
                employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
                if employee:
                    from app.services.hr_notifications import notify_vacation_approved
                    notify_vacation_approved(employee, req)
            except Exception:
                pass

        flash(f"Solicitud {'aprobada' if action == 'approve' else 'rechazada'}.", "success")

    return redirect(url_for("web_rrhh.vacation_list"))


