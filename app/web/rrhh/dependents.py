"""RRHH module — employee dependents."""

import uuid
from datetime import datetime, timezone
from flask import request, redirect, url_for, session, flash
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr
from app.utils.hr_utils import RELATIONSHIP_CATALOG


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/dependents/add", methods=["POST"])
def employee_dependent_add(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    first_name = request.form.get("firstName", "").strip()
    first_last_name = request.form.get("firstLastName", "").strip()
    middle_name = request.form.get("middleName", "").strip()
    second_last_name = request.form.get("secondLastName", "").strip()
    relationship_code = request.form.get("relationshipCode", "").strip()
    relationship_name = next(
        (r["name"] for r in RELATIONSHIP_CATALOG if r["code"] == relationship_code),
        relationship_code,
    )
    now = datetime.now(timezone.utc).isoformat()
    user_email = session.get("user", {}).get("email", "")

    dep_id = str(uuid.uuid4())
    hr.save_employee_dependent(owner_uid, {
        "id": dep_id,
        "employeeId": employee_id,
        "firstName": first_name,
        "middleName": middle_name,
        "firstLastName": first_last_name,
        "secondLastName": second_last_name,
        "relationshipCode": relationship_code,
        "relationshipName": relationship_name,
        "birthDate": request.form.get("birthDate", "").strip(),
        "gender": request.form.get("gender", "").strip(),
        "isStudent": request.form.get("isStudent") == "on",
        "isFinancialDependent": request.form.get("isFinancialDependent", "on") == "on",
        "active": True,
        "endDate": "",
        "idNumber": request.form.get("idNumber", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "createdAt": now,
        "createdBy": user_email,
        "updatedAt": now,
        "updatedBy": user_email,
    }, sandbox=sandbox)

    flash("Dependiente agregado exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/dependents/<dep_id>/deactivate", methods=["POST"])
def employee_dependent_deactivate(employee_id, dep_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    hr.deactivate_employee_dependent(
        owner_uid, dep_id, sandbox=sandbox,
        updated_by=user_email,
        end_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    flash("Dependiente desactivado.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))
