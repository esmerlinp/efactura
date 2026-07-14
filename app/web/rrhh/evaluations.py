"""RRHH module — auto-extracted."""

from datetime import date, datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


# ═══════════════════════════════════════════════════════════════════════════
# EVALUACIONES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/evaluations")
def evaluation_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    evals = hr.get_evaluations(owner_uid, sandbox=sandbox)
    evals.sort(key=lambda e: e.get("date", ""), reverse=True)
    employees = {e["id"]: e for e in hr.get_employees(owner_uid, sandbox=sandbox)}
    return render_template("rrhh/evaluation_list.html", active_page="rrhh_development",
                           evaluations=evals, employees=employees)


@web_rrhh_bp.route("/rrhh/evaluations/new", methods=["GET", "POST"])
def evaluation_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employees = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
        eval_id = str(uuid.uuid4())
        hr.save_evaluation(owner_uid, eval_id, {
            "id": eval_id,
            "employeeId": emp_id,
            "employeeName": employee.get("fullName", "") if employee else "",
            "date": request.form.get("date", date.today().isoformat()),
            "evalType": request.form.get("evalType", "periodica"),
            "score": float(request.form.get("score", 3)),
            "strengths": request.form.get("strengths", "").strip(),
            "improvements": request.form.get("improvements", "").strip(),
            "evaluatorName": request.form.get("evaluatorName", "").strip(),
            "notes": request.form.get("notes", "").strip(),
        }, sandbox=sandbox)
        flash("Evaluación registrada.", "success")
        return redirect(url_for("web_rrhh.evaluation_list"))

    return render_template("rrhh/evaluation_form.html", active_page="rrhh_development", employees=employees, now=datetime.now)


