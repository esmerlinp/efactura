"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr



@web_rrhh_bp.route("/rrhh/employees/<employee_id>/terminate", methods=["POST"])
def employee_terminate(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    employee["status"] = "inactivo"
    employee["terminationDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    employee["terminationReason"] = request.form.get("reason", "").strip()
    employee["terminationType"] = request.form.get("terminationType", "otro").strip()
    hr.save_employee(owner_uid, employee_id, employee, sandbox=sandbox)
    from app.services.payroll_audit_service import log_action
    log_action(owner_uid, "terminate", "employee", employee_id,
               session.get("user", {}).get("email", ""),
               changes={"status": employee["status"], "reason": employee.get("terminationReason", "")}, sandbox=sandbox)
    flash("Empleado desvinculado.", "success")
    return redirect(url_for("web_rrhh.employee_list"))

