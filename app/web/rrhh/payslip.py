"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService
import os



# ═══════════════════════════════════════════════════════════════════════════
# VOLANTE DE PAGO — Ver, Descargar PDF, Enviar por Email
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/payslip/<period_id>")
def employee_payslip(employee_id, period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    period["lines"] = PayrollService.get_period_lines(period, owner_uid=owner_uid, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    line = next((l for l in period.get("lines", []) if l.get("employeeId") == employee_id), None)
    if not line:
        flash("El empleado no tiene línea de nómina en este período.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    return render_template("rrhh/employee_payslip.html", active_page="rrhh_employees",
                           employee=employee, period=period, line=line)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/payslip/<period_id>/pdf")
def employee_payslip_pdf(employee_id, period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    period["lines"] = PayrollService.get_period_lines(period, owner_uid=owner_uid, sandbox=sandbox)
    if not employee or not period:
        return "Empleado o período no encontrado.", 404

    line = next((l for l in period.get("lines", []) if l.get("employeeId") == employee_id), None)
    if not line:
        return "Línea de nómina no encontrada.", 404

    try:
        from weasyprint import HTML as WeasyprintHTML
        rendered = render_template("rrhh/employee_payslip.html",
                                   employee=employee, period=period, line=line)
        pdf_bytes = WeasyprintHTML(string=rendered, base_url=request.host_url).write_pdf()
        filename = f"volante_{period.get('periodKey','')}_{employee.get('fullName','empleado')}.pdf"
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"⚠️ Error generando PDF de volante: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.employee_payslip", employee_id=employee_id, period_id=period_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/payslip/<period_id>/email", methods=["POST"])
def employee_payslip_email(employee_id, period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    period = hr.get_payroll_period(owner_uid, period_id, sandbox=sandbox)
    period["lines"] = PayrollService.get_period_lines(period, owner_uid=owner_uid, sandbox=sandbox)
    if not employee or not period:
        flash("Empleado o período no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    employee_email = (employee.get("email") or "").strip()
    if not employee_email:
        flash("El empleado no tiene un correo electrónico registrado.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    line = next((l for l in period.get("lines", []) if l.get("employeeId") == employee_id), None)
    if not line:
        flash("Línea de nómina no encontrada.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    try:
        from app.services.mailer import Mailer
        html_body = render_template("rrhh/employee_payslip_email.html",
                                    employee=employee, period=period, line=line)
        period_label = period.get("periodRange") or period.get("periodKey", "")
        subject = f"Volante de pago — {period_label}"
        Mailer.send(
            app=current_app._get_current_object(),
            to_email=employee_email,
            subject=subject,
            html_body=html_body,
            from_name=current_app.config.get("COMPANY_NAME", ""),
            category="noreply",
        )
        flash(f"Volante enviado a {employee_email}.", "success")
    except Exception as e:
        print(f"⚠️ Error enviando volante por email: {e}")
        flash("Error al enviar el volante por correo.", "error")

    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/calculate-payroll", methods=["POST"])
def employee_calculate_payroll(employee_id):
    if _login_required():
        return jsonify({"error": "No autorizado"}), 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        return jsonify({"error": "Empleado no encontrado"}), 404

    base_salary = float(employee.get("baseSalary", 0))
    period_type = request.form.get("period_type", "mensual")
    overtime_hours = float(request.form.get("overtime_hours", 0) or 0)
    commission = float(request.form.get("commission", 0) or 0)
    bonus = float(request.form.get("bonus", 0) or 0)
    other_income = float(request.form.get("other_income", 0) or 0)
    other_deductions = float(request.form.get("other_deductions", 0) or 0)

    tax_rates_data = hr.get_tax_rates(owner_uid, sandbox=sandbox)
    rates = PayrollService.get_rates(tax_rates_data)

    calc = PayrollService.calculate_payroll_line(
        base_salary=base_salary,
        tax_rates=tax_rates_data,
        overtime_hours=overtime_hours,
        commission=commission,
        bonus=bonus,
        other_income=other_income,
        other_deductions=other_deductions,
        period_type=period_type,
    )

    total_employer = calc.get("totalEmployerContrib", 0)
    costo_empresa = round(calc.get("totalIncome", 0) + total_employer, 2)

    return jsonify({
        "period_type": period_type,
        "baseSalary": calc.get("baseSalary"),
        "grossSalary": calc.get("grossSalary"),
        "overtimeHours": overtime_hours,
        "overtimePay": calc.get("overtimePay"),
        "overtimeRate": rates.get("overtime_rate", 1.35),
        "commission": commission,
        "bonus": bonus,
        "otherIncome": other_income,
        "totalIncome": calc.get("totalIncome"),
        "afpEmployee": calc.get("afpEmployee"),
        "afpEmployeeRate": rates.get("afp_employee_rate", 0),
        "sfsEmployee": calc.get("sfsEmployee"),
        "sfsEmployeeRate": rates.get("sfs_employee_rate", 0),
        "infotepEmployee": calc.get("infotepEmployee", 0),
        "isrRetention": calc.get("isrRetention"),
        "otherDeductions": other_deductions,
        "totalDeductions": calc.get("totalDeductions"),
        "netSalary": calc.get("netSalary"),
        "afpEmployer": calc.get("afpEmployer"),
        "sfsEmployer": calc.get("sfsEmployer"),
        "srlEmployer": calc.get("srlEmployer"),
        "infotepEmployer": calc.get("infotepEmployer"),
        "totalEmployerContrib": total_employer,
        "costoEmpresa": costo_empresa,
        "minSalary": rates.get("min_salary", 23223),
        "afpSalaryCap": rates.get("afp_salary_cap", 196750),
        "sfsSalaryCap": rates.get("sfs_salary_cap", 98375),
        "infotepThreshold": rates.get("infotep_threshold_multiplier", 5),
        "workingDaysPerMonth": rates.get("working_days_per_month", 23.83),
        "workingHoursPerDay": rates.get("working_hours_per_day", 8),
    })

