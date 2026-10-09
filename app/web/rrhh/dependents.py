"""RRHH module — employee dependents."""

import io
import uuid
from datetime import datetime, timezone
from flask import request, redirect, url_for, session, flash, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr
from app.utils.hr_utils import RELATIONSHIP_CATALOG, is_active_equivalent
from app.models.employee import Dependent


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/dependents/add", methods=["POST"])
def employee_dependent_add(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
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

    if id_number and hr.is_dependent_doc_duplicate(company_id, doc_type, id_number, sandbox=sandbox):
        flash(f"Ya existe un dependiente registrado con el documento {id_number}.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    category_input = request.form.get("category", "").strip()
    is_student = request.form.get("isStudent") == "on"
    is_financial = request.form.get("isFinancialDependent", "on") == "on"
    disability = request.form.get("disability") == "on"
    birth_date = request.form.get("birthDate", "").strip()
    student_cert_expiry = request.form.get("studentCertificationExpiry", "").strip()
    effective_start_date = request.form.get("effectiveStartDate", "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    effective_end_date = request.form.get("effectiveEndDate", "").strip()
    ars_code = request.form.get("arsCode", "").strip()
    doc_verification_status = request.form.get("documentVerificationStatus", "verified").strip()

    dep_id = str(uuid.uuid4())
    dep_obj = Dependent(
        id=dep_id,
        employeeId=employee_id,
        firstName=first_name,
        middleName=middle_name,
        firstLastName=first_last_name,
        secondLastName=second_last_name,
        relationshipCode=relationship_code,
        relationshipName=relationship_name,
        birthDate=birth_date,
        gender=request.form.get("gender", "").strip(),
        docType=doc_type,
        idNumber=id_number,
        isStudent=is_student,
        isFinancialDependent=is_financial,
        disability=disability,
        studentCertificationExpiry=student_cert_expiry,
        effectiveStartDate=effective_start_date,
        effectiveEndDate=effective_end_date,
        documentVerificationStatus=doc_verification_status,
        arsCode=ars_code,
        notes=request.form.get("notes", "").strip(),
        active=True,
        createdAt=now,
        createdBy=user_email,
        updatedAt=now,
        updatedBy=user_email,
    )

    if category_input in ("direct", "additional", "informational"):
        dep_obj.category = category_input
        status_input = request.form.get("eligibilityStatus", "").strip()
        dep_obj.eligibilityStatus = status_input if status_input in ("eligible", "ineligible", "pending_document") else "eligible"
    else:
        dep_obj.resolve_category_and_eligibility()

    hr.save_employee_dependent(company_id, dep_obj.model_dump(), sandbox=sandbox)
    flash("Dependiente agregado exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/dependents/<dep_id>/edit", methods=["POST"])
def employee_dependent_edit(employee_id, dep_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    existing = hr.get_employee_dependent(company_id, dep_id, sandbox=sandbox)
    if not existing:
        flash("Dependiente no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    doc_type = request.form.get("docType", existing.get("docType", "C")).strip()
    id_number = "".join(c for c in (request.form.get("idNumber", "") or "").strip() if c.isdigit())
    if id_number and hr.is_dependent_doc_duplicate(company_id, doc_type, id_number, exclude_dep_id=dep_id, sandbox=sandbox):
        flash(f"Ya existe otro dependiente con el documento {id_number}.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    relationship_code = request.form.get("relationshipCode", existing.get("relationshipCode", "")).strip()
    relationship_name = next(
        (r["name"] for r in RELATIONSHIP_CATALOG if r["code"] == relationship_code),
        relationship_code,
    )
    now = datetime.now(timezone.utc).isoformat()

    updates = {
        "firstName": request.form.get("firstName", existing.get("firstName", "")).strip(),
        "middleName": request.form.get("middleName", existing.get("middleName", "")).strip(),
        "firstLastName": request.form.get("firstLastName", existing.get("firstLastName", "")).strip(),
        "secondLastName": request.form.get("secondLastName", existing.get("secondLastName", "")).strip(),
        "relationshipCode": relationship_code,
        "relationshipName": relationship_name,
        "birthDate": request.form.get("birthDate", existing.get("birthDate", "")).strip(),
        "gender": request.form.get("gender", existing.get("gender", "")).strip(),
        "docType": doc_type,
        "idNumber": id_number,
        "isStudent": request.form.get("isStudent") == "on",
        "isFinancialDependent": request.form.get("isFinancialDependent") == "on",
        "disability": request.form.get("disability") == "on",
        "studentCertificationExpiry": request.form.get("studentCertificationExpiry", existing.get("studentCertificationExpiry", "")).strip(),
        "effectiveStartDate": request.form.get("effectiveStartDate", existing.get("effectiveStartDate", "")).strip(),
        "effectiveEndDate": request.form.get("effectiveEndDate", existing.get("effectiveEndDate", "")).strip(),
        "documentVerificationStatus": request.form.get("documentVerificationStatus", existing.get("documentVerificationStatus", "verified")).strip(),
        "arsCode": request.form.get("arsCode", existing.get("arsCode", "")).strip(),
        "notes": request.form.get("notes", existing.get("notes", "")).strip(),
        "updatedAt": now,
        "updatedBy": user_email,
    }

    category_input = request.form.get("category", "").strip()
    if category_input in ("direct", "additional", "informational"):
        updates["category"] = category_input
        status_input = request.form.get("eligibilityStatus", "").strip()
        updates["eligibilityStatus"] = status_input if status_input in ("eligible", "ineligible", "pending_document") else "eligible"
    else:
        merged = dict(existing)
        merged.update(updates)
        dep_temp = Dependent(**merged)
        cat, el_status = dep_temp.resolve_category_and_eligibility()
        updates["category"] = cat
        updates["eligibilityStatus"] = el_status

    hr.update_employee_dependent(company_id, dep_id, updates, sandbox=sandbox)
    flash("Dependiente actualizado exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/dependents/<dep_id>/deactivate", methods=["POST"])
def employee_dependent_deactivate(employee_id, dep_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")
    reason = request.form.get("deactivationReason", "").strip()
    end_date = request.form.get("endDate", "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Correct company_id passed (fixing previous owner_uid multi-tenancy bug)
    hr.deactivate_employee_dependent(
        company_id, dep_id, sandbox=sandbox,
        updated_by=user_email,
        end_date=end_date,
        reason=reason,
    )
    flash("Dependiente desactivado.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/dependents/<dep_id>/reactivate", methods=["POST"])
def employee_dependent_reactivate(employee_id, dep_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    now = datetime.now(timezone.utc).isoformat()
    hr.update_employee_dependent(company_id, dep_id, {
        "active": True,
        "endDate": "",
        "effectiveEndDate": "",
        "deactivationReason": "",
        "updatedAt": now,
        "updatedBy": user_email,
    }, sandbox=sandbox)
    flash("Dependiente reactivado.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/dependents/export/tss-rd")
def dependents_export_tss_rd():
    """Descarga archivo RD (Registro de Dependientes Adicionales) formato SUIRPLUS v5.0."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    from app.services.dependents_tss_service import generate_tss_rd, validate_rd_export
    from app.services.db_service import DatabaseService

    employees = hr.get_employees(company_id, sandbox=sandbox)
    employees = [e for e in employees if is_active_equivalent(e.get("status", ""))]

    emp_ids = [e.get("id", "") for e in employees if e.get("id")]
    dependents_by_employee = hr.get_dependents_for_employees(company_id, emp_ids, sandbox=sandbox)

    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
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
        company_id=company_id,
        sandbox=sandbox,
    )

    content = resultado["content"]
    if isinstance(content, str):
        content = content.encode("utf-8")
    buffer = io.BytesIO(content)
    return send_file(buffer, mimetype="text/plain", as_attachment=True,
                     download_name=resultado["filename"])
