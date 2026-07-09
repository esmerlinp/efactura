"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


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
    return render_template("rrhh/leave_list.html", active_page="rrhh_attendance", requests=requests)


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

    return render_template("rrhh/leave_form.html", active_page="rrhh_attendance", employees=employees)


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


