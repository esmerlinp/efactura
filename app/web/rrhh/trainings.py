"""RRHH module — auto-extracted."""

from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


@web_rrhh_bp.route("/rrhh/trainings")
def training_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    trainings = hr.get_trainings(company_id, sandbox=sandbox)
    trainings.sort(key=lambda t: t.get("date", ""), reverse=True)
    return render_template("rrhh/training_list.html", active_page="rrhh_development", trainings=trainings)


@web_rrhh_bp.route("/rrhh/trainings/new", methods=["GET", "POST"])
def training_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employees = [e for e in hr.get_employees(company_id, sandbox=sandbox) if e.get("status") == "activo"]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(company_id, emp_id, sandbox=sandbox)
        train_id = str(uuid.uuid4())
        hr.save_training(company_id, train_id, {
            "id": train_id,
            "employeeId": emp_id,
            "employeeName": employee.get("fullName", "") if employee else "",
            "trainingName": request.form.get("trainingName", "").strip(),
            "institution": request.form.get("institution", "").strip(),
            "date": request.form.get("date", date.today().isoformat()),
            "hours": int(request.form.get("hours", 0) or 0),
            "hasCertificate": request.form.get("hasCertificate") == "on",
            "notes": request.form.get("notes", "").strip(),
        }, sandbox=sandbox)
        flash("Capacitación registrada.", "success")
        return redirect(url_for("web_rrhh.training_list"))

    return render_template("rrhh/training_form.html", active_page="rrhh_development", employees=employees, now=datetime.now)


