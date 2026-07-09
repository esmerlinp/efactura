"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/checklist/<checklist_type>")
def employee_checklist(employee_id, checklist_type):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))
    items = hr.get_checklist(owner_uid, employee_id, checklist_type, sandbox=sandbox)
    done = sum(1 for i in items if i.get("completed"))
    total = len(items)
    pct = int(done / total * 100) if total else 0
    titles = {"onboarding": "Onboarding", "offboarding": "Offboarding"}
    return render_template("rrhh/checklist.html", active_page="rrhh_employees",
                           employee=employee, items=items, checklist_type=checklist_type,
                           title=titles.get(checklist_type, checklist_type),
                           done=done, total=total, pct=pct)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/checklist/<checklist_type>/toggle/<item_id>", methods=["POST"])
def employee_checklist_toggle(employee_id, checklist_type, item_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    completed = request.form.get("completed") == "1"
    hr.toggle_checklist_item(owner_uid, employee_id, checklist_type, item_id, completed,
                             session.get("user", {}).get("email", ""), sandbox=sandbox)
    return redirect(url_for("web_rrhh.employee_checklist", employee_id=employee_id, checklist_type=checklist_type))


