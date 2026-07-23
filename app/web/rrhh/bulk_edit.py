"""RRHH module — Edición Masiva de Empleados."""

import re
from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role,
)
from app.services import hr_data_service as hr


@web_rrhh_bp.route("/rrhh/employees/bulk-edit", methods=["GET"])
def bulk_edit_wizard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    ids_param = request.args.get("ids", "")
    employee_ids = [i for i in ids_param.split(",") if i] if ids_param else []

    employees = []
    if employee_ids:
        for eid in employee_ids:
            emp = hr.get_employee(company_id, eid, sandbox=sandbox)
            if emp:
                employees.append(emp)

    from app.services.payroll_service import PayrollService
    employees_data = []
    for emp in employees:
        vac_days = PayrollService.calculate_vacation_days(emp.get("hireDate", ""))
        employees_data.append({
            "id": emp.get("id", ""),
            "fullName": emp.get("fullName", ""),
            "cedula": emp.get("cedula", ""),
            "position": emp.get("position", ""),
            "department": emp.get("department", ""),
            "area": emp.get("area", ""),
            "baseSalary": emp.get("baseSalary", 0),
            "status": emp.get("status", ""),
            "vacationDays": vac_days,
            "afpProvider": emp.get("afpProvider", ""),
            "contractType": emp.get("contractType", ""),
            "branchId": emp.get("branchId", ""),
            "paymentMethod": emp.get("paymentMethod", ""),
        })

    from app.services.bulk_edit_service import get_bulk_editable_fields
    fields = get_bulk_editable_fields()

    from app.services.db_service import DatabaseService
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id)

    payroll_groups = hr.get_payroll_groups(company_id, sandbox=sandbox) if hasattr(hr, 'get_payroll_groups') else []

    from app.data.occupations_catalog import OCCUPATIONS
    occupations = OCCUPATIONS if OCCUPATIONS else []

    return render_template(
        "rrhh/bulk_edit_wizard.html",
        active_page="rrhh_employees",
        employees=employees_data,
        employee_ids=employee_ids,
        fields=fields,
        branches=branches,
        payroll_groups=payroll_groups,
        occupations=occupations,
    )


@web_rrhh_bp.route("/rrhh/employees/bulk-edit/validate", methods=["POST"])
def bulk_edit_validate():
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    employee_ids = data.get("employeeIds", [])
    field_changes = data.get("fields", {})

    if not employee_ids:
        return {"valid": False, "errors": [{"message": "No hay empleados seleccionados."}]}

    if not field_changes:
        return {"valid": False, "errors": [{"message": "No se seleccionó ningún campo para modificar."}]}

    errors = []
    for field_name, value in field_changes.items():
        if field_name in ("afpSalaryCap", "sfsSalaryCap", "hourlyRate", "baseSalary"):
            try:
                float(value) if value != "" else 0
            except (ValueError, TypeError):
                errors.append({"field": field_name, "message": f"El valor de '{field_name}' debe ser numérico."})

        if field_name == "tssKey" and value and not re.match(r'^\d{3}$', str(value)):
            errors.append({"field": field_name, "message": "La clave TSS debe tener exactamente 3 dígitos."})

        if field_name == "occupationCode" and value and not re.match(r'^\d{4}$', str(value)):
            errors.append({"field": field_name, "message": "El código de ocupación debe tener 4 dígitos."})

        if field_name == "weeklyHours" and value:
            try:
                h = int(value)
                if h < 1 or h > 44:
                    errors.append({"field": field_name, "message": "Las horas semanales deben estar entre 1 y 44."})
            except (ValueError, TypeError):
                errors.append({"field": field_name, "message": "Las horas semanales debe ser un número entero."})

    employees = []
    for eid in employee_ids:
        emp = hr.get_employee(company_id, eid, sandbox=sandbox)
        if emp:
            employees.append({
                "id": emp.get("id", ""),
                "fullName": emp.get("fullName", ""),
                "cedula": emp.get("cedula", ""),
                "position": emp.get("position", ""),
                "status": emp.get("status", ""),
                "currentValues": {f: emp.get(f, "") for f in field_changes},
            })

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "affectedCount": len(employee_ids),
        "employees": employees,
        "fields": field_changes,
    }


@web_rrhh_bp.route("/rrhh/employees/bulk-edit/execute", methods=["POST"])
def bulk_edit_execute():
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    employee_ids = data.get("employeeIds", [])
    field_changes = data.get("fields", {})

    if not employee_ids:
        return {"error": "No hay empleados seleccionados."}, 400

    if not field_changes:
        return {"error": "No se seleccionó ningún campo."}, 400

    from app.services.bulk_edit_service import create_bulk_edit_job

    try:
        job_id = create_bulk_edit_job(
            company_id=company_id,
            employee_ids=employee_ids,
            changes=field_changes,
            user_email=user_email,
            sandbox=sandbox,
        )
        return {"jobId": job_id, "total": len(employee_ids)}
    except Exception as e:
        return {"error": f"Error al iniciar la edición masiva: {str(e)}"}, 500


@web_rrhh_bp.route("/rrhh/employees/bulk-edit/progress/<job_id>", methods=["GET"])
def bulk_edit_progress(job_id):
    if _login_required():
        return {"error": "No autorizado"}, 401

    from app.services.bulk_edit_service import get_job_progress

    job = get_job_progress(job_id)
    if not job:
        return {"status": "not_found", "error": "Job no encontrado"}, 404

    return jsonify(job)


@web_rrhh_bp.route("/rrhh/employees/bulk-edit/result/<job_id>", methods=["GET"])
def bulk_edit_result(job_id):
    if _login_required():
        return {"error": "No autorizado"}, 401

    from app.services.bulk_edit_service import get_job_result

    result = get_job_result(job_id)
    if not result:
        return {"error": "Job no encontrado"}, 404

    return jsonify(result)
