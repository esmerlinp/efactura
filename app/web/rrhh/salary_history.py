"""RRHH module — auto-extracted."""

from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/salary-history")
def employee_salary_history(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    history = hr.get_salary_history(company_id, employee_id, sandbox=sandbox)
    from app.services.payroll_static_data import PAYROLL_FREQUENCIES
    config = hr.get_payroll_config(company_id, sandbox=sandbox)
    frequency = config.get("payroll", {}).get("frequency", "mensual")
    try:
        now = date.today()
        payroll_periods = _generate_periods(frequency, now.year)
        if now.month < 12:
            payroll_periods += _generate_periods(frequency, now.year + 1)
    except Exception:
        payroll_periods = []
    return render_template("rrhh/employee_salary_history.html", active_page="rrhh_employees",
                           employee=employee, history=history, frequencies=PAYROLL_FREQUENCIES,
                           today=date.today().isoformat(),
                           payroll_periods=payroll_periods, effective_date=employee.get("effectiveDate", ""))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/salary/add", methods=["POST"])
def employee_salary_add(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    new_amount = float(request.form.get("amount", 0) or 0)
    eff_date = request.form.get("effective_date", date.today().isoformat()).strip()
    reason = request.form.get("reason", "Ajuste salarial").strip()
    payroll_period_key = request.form.get("payrollPeriodKey", "").strip()

    if new_amount <= 0:
        flash("El salario debe ser mayor a 0.", "error")
        return redirect(url_for("web_rrhh.employee_salary_history", employee_id=employee_id))

    # Auto-detectar período si no se especificó
    if not payroll_period_key and eff_date:
        config = hr.get_payroll_config(company_id, sandbox=sandbox)
        frequency = config.get("payroll", {}).get("frequency", "mensual")
        try:
            import calendar
            year = eff_date[:4]
            for p in _generate_periods(frequency, int(year)):
                if p["start"] <= eff_date <= p["end"]:
                    payroll_period_key = p["key"]
                    break
        except Exception:
            pass

    old_amount = float(employee.get("baseSalary", 0))
    # Cerrar salario anterior
    hr.close_previous_salary(company_id, employee_id, eff_date, sandbox=sandbox)
    # Crear nueva entrada
    history_id = str(uuid.uuid4())
    hr.save_salary_history_entry(company_id, {
        "id": history_id, "employeeId": employee_id,
        "amount": new_amount, "previousAmount": old_amount,
        "effectiveDate": eff_date, "endDate": "",
        "reason": reason,
        "approvedBy": session.get("user", {}).get("email", ""),
        "createdAt": date.today().isoformat(),
        "payrollPeriodKey": payroll_period_key,
    }, sandbox=sandbox)
    # Actualizar el salario del empleado
    employee["baseSalary"] = new_amount
    employee["salary"] = new_amount
    hr.save_employee(company_id, employee_id, employee, sandbox=sandbox)

    flash(f"Salario actualizado a RD$ {new_amount:,.2f} con vigencia {eff_date}.", "success")
    return redirect(url_for("web_rrhh.employee_salary_history", employee_id=employee_id))


