"""RRHH module — auto-extracted."""

import uuid
from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.hr_notifications import notify_vacation_approved, notify_leave_approved


# ═══════════════════════════════════════════════════════════════════════════
# VACACIONES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/vacations")
def vacation_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    # Auto-sanación: sincronizar estados antes de mostrar (idempotente)
    try:
        from app.services.employee_status_service import EmployeeStatusService
        EmployeeStatusService.sync_employee_statuses(company_id, sandbox=sandbox,
                                                     actor="Sistema (auto-sync)")
    except Exception:
        pass

    requests = hr.get_vacation_requests(company_id, sandbox=sandbox)
    requests.sort(key=lambda r: r.get("createdDate", ""), reverse=True)
    return render_template("rrhh/vacation_list.html", active_page="rrhh_attendance",
                           requests=requests, today=date.today().isoformat())


@web_rrhh_bp.route("/rrhh/vacations/new", methods=["GET", "POST"])
def vacation_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    from app.utils.hr_utils import is_active_equivalent
    employees = [e for e in hr.get_employees(company_id, sandbox=sandbox)
                 if is_active_equivalent(e.get("status", ""))]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(company_id, emp_id, sandbox=sandbox)
        if not employee:
            flash("Empleado no encontrado.", "error")
            return redirect(url_for("web_rrhh.vacation_list"))

        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        from app.services.holiday_service import HolidayService
        holidays = HolidayService.get_holiday_dates(company_id, start_date, end_date, sandbox=sandbox)
        work_days = PayrollService.resolve_employee_work_days(company_id, employee, sandbox=sandbox)
        business_days = PayrollService.calculate_business_days(start_date, end_date, holidays=holidays, work_days=work_days)
        from app.services.employee_status_service import EmployeeStatusService
        emp_vac_requests = [
            r for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
            if r.get("employeeId") == emp_id
        ]
        taken_days = EmployeeStatusService.taken_vacation_days(emp_vac_requests)
        remaining = PayrollService.calculate_vacation_days(employee.get("hireDate", ""), taken_days=taken_days)

        req_id = str(uuid.uuid4())
        hr.save_vacation_request(company_id, req_id, {
            "id": req_id,
            "employeeId": emp_id,
            "employeeName": employee.get("fullName", ""),
            "startDate": start_date,
            "endDate": end_date,
            "days": business_days,
            "status": "pendiente",
            "remainingDaysBefore": remaining,
            "notes": request.form.get("notes", "").strip(),
            "createdDate": date.today().isoformat(),
        }, sandbox=sandbox)
        flash(f"Solicitud de vacaciones por {business_days} días creada.", "success")
        return redirect(url_for("web_rrhh.vacation_list"))

    return render_template("rrhh/vacation_form.html", active_page="rrhh_attendance", employees=employees)


@web_rrhh_bp.route("/rrhh/vacations/<request_id>/<action>", methods=["POST"])
def vacation_action(request_id, action):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    req = hr.get_vacation_request(company_id, request_id, sandbox=sandbox)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.vacation_list"))

    if action in ("approve", "rechazar"):
        req["status"] = "aprobada" if action == "approve" else "rechazada"
        req["approvedDate"] = date.today().isoformat()
        req["approvedBy"] = session["user"].get("email", "")
        hr.save_vacation_request(company_id, request_id, req, sandbox=sandbox)

        # Notificar al empleado si se aprobó
        if action == "approve":
            try:
                employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
                if employee:
                    from app.services.hr_notifications import notify_vacation_approved
                    notify_vacation_approved(employee, req)
                    # Si la solicitud ya está en rango, el empleado pasa a "vacaciones"
                    from app.services.employee_status_service import EmployeeStatusService
                    EmployeeStatusService.sync_employee(
                        company_id, employee.get("id", ""), sandbox=sandbox,
                        actor=session["user"].get("email", ""))
            except Exception:
                pass

        flash(f"Solicitud {'aprobada' if action == 'approve' else 'rechazada'}.", "success")

    return redirect(url_for("web_rrhh.vacation_list"))


@web_rrhh_bp.route("/rrhh/vacations/<request_id>/anular", methods=["POST"])
def vacation_cancel(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    cancel_date = request.form.get("cancelDate", "").strip()
    reason = request.form.get("cancelReason", "").strip()
    from app.services.employee_status_service import EmployeeStatusService
    res = EmployeeStatusService.cancel_vacation_request(
        company_id, request_id, cancel_date=cancel_date,
        actor=session["user"].get("email", ""),
        reason=reason or "Anulada por RRHH",
        sandbox=sandbox)

    if res.get("success"):
        flash(f"Vacaciones anuladas: {res.get('consumedDays', 0)} día(s) consumido(s), "
              f"{res.get('refundedDays', 0)} devuelto(s) al balance.", "success")
    else:
        flash(res.get("error", "No se pudo anular la solicitud."), "error")

    return redirect(url_for("web_rrhh.vacation_list"))


