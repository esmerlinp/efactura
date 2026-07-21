"""RRHH module — employee dependents."""

import io
import uuid
from datetime import datetime, timezone
from flask import request, redirect, url_for, session, flash, send_file
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
    doc_type = request.form.get("docType", "C").strip()
    id_number = "".join(c for c in (request.form.get("idNumber", "") or "").strip() if c.isdigit())
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
        "docType": doc_type,
        "isStudent": request.form.get("isStudent") == "on",
        "isFinancialDependent": request.form.get("isFinancialDependent", "on") == "on",
        "active": True,
        "endDate": "",
        "idNumber": id_number,
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


@web_rrhh_bp.route("/rrhh/dependents/export/tss-rd")
def dependents_export_tss_rd():
    """Descarga archivo RD (Registro de Dependientes Adicionales) formato SUIRPLUS v5.0."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    from app.services.dependents_tss_service import generate_tss_rd, validate_rd_export
    from app.services.db_service import DatabaseService

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    employees = [e for e in employees if e.get("status", "") == "activo"]

    emp_ids = [e.get("id", "") for e in employees if e.get("id")]
    dependents_by_employee = hr.get_dependents_for_employees(owner_uid, emp_ids, sandbox=sandbox)

    company = DatabaseService.get_company_profile(owner_uid) or {}
    employer_rnc = (company.get("companyRNC", "") or "").replace("-", "").strip()

    errors = validate_rd_export(employees, dependents_by_employee)
    if errors:
        error_list = "\n".join(f"  - {e}" for e in errors)
        flash(f"Errores de validación antes de exportar RD:\n{error_list}", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    resultado = generate_tss_rd(
        employees,
        employer_rnc=employer_rnc,
        dependents_by_employee=dependents_by_employee,
        owner_uid=owner_uid,
        sandbox=sandbox,
    )

    content = resultado["content"]
    if isinstance(content, str):
        content = content.encode("utf-8")
    buffer = io.BytesIO(content)
    return send_file(buffer, mimetype="text/plain", as_attachment=True,
                     download_name=resultado["filename"])
