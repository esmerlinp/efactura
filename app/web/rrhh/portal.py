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
# PORTAL DEL EMPLEADO (Self-Service)
# ═══════════════════════════════════════════════════════════════════════════

def _get_my_employee(company_id, sandbox):
    from app.services import hr_data_service as hr
    email = session.get("user", {}).get("email", "")
    employees = hr.get_employees(company_id, sandbox=sandbox)
    for emp in employees:
        if emp.get("email", "").strip().lower() == email.strip().lower():
            return emp
    return None


@web_rrhh_bp.route("/mi-perfil")
def employee_portal_dashboard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.payroll_service import PayrollService
    from app.services import hr_data_service as hr
    from app.services.employee_status_service import EmployeeStatusService
    employee = _get_my_employee(company_id, sandbox)
    if not employee:
        flash("No se encontró tu perfil de empleado. Contacta a RRHH.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))

    taken = EmployeeStatusService.taken_vacation_days([
        r for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
        if r.get("employeeId") == employee.get("id")
    ])
    vacation_days = PayrollService.calculate_vacation_days(
        employee.get("hireDate", ""), taken_days=taken)

    my_vacations = sorted(
        [r for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
         if r.get("employeeId") == employee.get("id")],
        key=lambda r: r.get("createdDate", ""), reverse=True)
    my_leaves = sorted(
        [r for r in hr.get_leave_requests(company_id, sandbox=sandbox)
         if r.get("employeeId") == employee.get("id")],
        key=lambda r: r.get("startDate", ""), reverse=True)

    import json as _json
    attachments_by_request = {}
    for a in hr.get_request_attachments(company_id, sandbox=sandbox):
        rid = a.get("requestId")
        rtype = a.get("requestType")
        if rid not in {r.get("id") for r in my_vacations + my_leaves}:
            continue
        endpoint = "vacation_attachment_download" if rtype == "vacation" else "leave_attachment_download"
        del_endpoint = "vacation_attachment_delete" if rtype == "vacation" else "leave_attachment_delete"
        attachments_by_request.setdefault(rid, []).append({
            "id": a.get("id"),
            "name": a.get("name"),
            "size": a.get("size", 0),
            "uploadedAt": a.get("uploadedAt", ""),
            "download": url_for("web_rrhh." + endpoint, request_id=rid, doc_id=a.get("id")),
            "delete": url_for("web_rrhh." + del_endpoint, request_id=rid, doc_id=a.get("id")),
        })

    return render_template("rrhh/portal/dashboard.html", employee=employee,
                           vacation_days=vacation_days,
                           my_vacations=my_vacations, my_leaves=my_leaves,
                           attachments_json=_json.dumps(attachments_by_request))


@web_rrhh_bp.route("/mi-perfil/payslips")
def employee_portal_payslips():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(company_id, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))

    periods = hr.get_payroll_periods(company_id, sandbox=sandbox)
    my_payslips = []
    for p in sorted(periods, key=lambda x: x.get("periodKey", ""), reverse=True)[:24]:
        for l in p.get("lines", []):
            if l.get("employeeId") == employee["id"]:
                my_payslips.append({"period": p, "line": l})
                break

    return render_template("rrhh/portal/payslips.html", employee=employee, payslips=my_payslips)


@web_rrhh_bp.route("/mi-perfil/payslips/<period_id>")
def employee_portal_payslip_detail(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(company_id, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_portal_payslips"))
    line = None
    for l in period.get("lines", []):
        if l.get("employeeId") == employee["id"]:
            line = l
            break
    if not line:
        flash("No tienes datos en este período.", "error")
        return redirect(url_for("web_rrhh.employee_portal_payslips"))
    return render_template("rrhh/portal/payslip_detail.html", employee=employee, period=period, line=line)


@web_rrhh_bp.route("/mi-perfil/vacations/new", methods=["GET", "POST"])
def employee_portal_vacation_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    employee = _get_my_employee(company_id, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    if request.method == "POST":
        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        from app.services.holiday_service import HolidayService
        holidays = HolidayService.get_holiday_dates(company_id, start_date, end_date, sandbox=sandbox)
        work_days = PayrollService.resolve_employee_work_days(company_id, employee, sandbox=sandbox)
        business_days = PayrollService.calculate_business_days(start_date, end_date, holidays=holidays, work_days=work_days)
        from app.services.employee_status_service import EmployeeStatusService
        taken = EmployeeStatusService.taken_vacation_days([
            r for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
            if r.get("employeeId") == employee["id"]
        ])
        remaining = PayrollService.calculate_vacation_days(
            employee.get("hireDate", ""), taken_days=taken)
        req_id = str(uuid.uuid4())
        hr.save_vacation_request(company_id, req_id, {
            "id": req_id, "employeeId": employee["id"],
            "employeeName": employee.get("fullName", ""),
            "startDate": start_date, "endDate": end_date,
            "days": business_days, "status": "pendiente",
            "remainingDaysBefore": remaining,
            "notes": request.form.get("notes", "").strip(),
            "createdDate": date.today().isoformat(),
        }, sandbox=sandbox)
        from app.web.rrhh.request_attachments import save_uploaded_files
        save_uploaded_files(company_id, req_id, "vacation", sandbox)
        flash(f"Solicitud de vacaciones por {business_days} días enviada.", "success")
        return redirect(url_for("web_rrhh.employee_portal_dashboard"))
    from app.services.employee_status_service import EmployeeStatusService
    taken = EmployeeStatusService.taken_vacation_days([
        r for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
        if r.get("employeeId") == employee["id"]
    ])
    remaining = PayrollService.calculate_vacation_days(
        employee.get("hireDate", ""), taken_days=taken)
    return render_template("rrhh/portal/vacation_form.html", employee=employee, remaining=remaining)


@web_rrhh_bp.route("/mi-perfil/evaluations")
def employee_portal_evaluations():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(company_id, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    evals = [e for e in hr.get_evaluations(company_id, sandbox=sandbox) if e.get("employeeId") == employee["id"]]
    return render_template("rrhh/portal/evaluations.html", employee=employee, evaluations=evals)


@web_rrhh_bp.route("/mi-perfil/trainings")
def employee_portal_trainings():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(company_id, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    trainings = [t for t in hr.get_trainings(company_id, sandbox=sandbox) if t.get("employeeId") == employee["id"]]
    return render_template("rrhh/portal/trainings.html", employee=employee, trainings=trainings)


@web_rrhh_bp.route("/mi-perfil/leave/new", methods=["GET", "POST"])
def employee_portal_leave_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employee = _get_my_employee(company_id, sandbox)
    if not employee:
        flash("Perfil no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_dashboard"))
    if request.method == "POST":
        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days + 1
        req_id = str(uuid.uuid4())
        hr.save_leave_request(company_id, req_id, {
            "id": req_id, "employeeId": employee["id"],
            "employeeName": employee.get("fullName", ""),
            "leaveType": request.form.get("leaveType", "otro"),
            "startDate": start_date, "endDate": end_date, "days": days,
            "status": "pendiente", "notes": request.form.get("notes", "").strip(),
            "paidByPayroll": True,
        }, sandbox=sandbox)
        from app.web.rrhh.request_attachments import save_uploaded_files
        save_uploaded_files(company_id, req_id, "leave", sandbox)
        flash("Permiso registrado.", "success")
        return redirect(url_for("web_rrhh.employee_portal_dashboard"))
    return render_template("rrhh/portal/leave_form.html", employee=employee)


