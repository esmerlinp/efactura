"""RRHH module — auto-extracted."""

from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.liquidacion_service import LiquidacionService
from app.services.payroll_audit_service import log_action



# ═══════════════════════════════════════════════════════════════════════════
# LIQUIDACIÓN LABORAL — Cálculo de Prestaciones y Derechos Adquiridos
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/liquidacion", methods=["GET", "POST"])
def employee_liquidacion(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.liquidacion_service import LiquidacionService

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    # ── Auto-calcular vacaciones desde el historial real ──
    hire_date = employee.get("hireDate", "")
    vac_requests = hr.get_vacation_requests(owner_uid, sandbox=sandbox)
    emp_vacs = [v for v in vac_requests
                if v.get("employeeId") == employee_id and v.get("status") == "aprobada"]

    today_str = date.today().isoformat()
    ant_approx = LiquidacionService.calcular_antiguedad(hire_date, today_str)
    ant_years = ant_approx["years"]

    def _add_years(d: str, years: int) -> str:
        try:
            dt = datetime.strptime(d[:10], "%Y-%m-%d")
            y = dt.year + years
            return dt.replace(year=y).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return d

    fecha_ultimo_aniversario = _add_years(hire_date, ant_years) if ant_years > 0 and hire_date else hire_date

    dias_por_anio = 18 if ant_years >= 5 else 14
    taken_before_anniversary = 0
    taken_current = 0

    for v in emp_vacs:
        v_start = v.get("startDate", "")
        if v_start and v_start >= fecha_ultimo_aniversario:
            taken_current += v.get("days", 0)
        else:
            taken_before_anniversary += v.get("days", 0)

    max_expected = ant_years * dias_por_anio
    pending_complete = 0
    if ant_years > 0 and max_expected > taken_before_anniversary:
        pending_complete = (max_expected - taken_before_anniversary) // dias_por_anio

    vacation_auto_pending_complete = max(0, pending_complete)
    vacation_auto_taken_current = max(0, taken_current)
    vacation_auto_total_taken = sum(v.get("days", 0) for v in emp_vacs)
    vacation_auto_total_accrued = max_expected

    resultado = None

    if request.method == "POST":
        termination_type = request.form.get("terminationType", "renuncia").strip()
        termination_date = request.form.get("terminationDate", "").strip()
        preaviso_trabajado = request.form.get("preavisoTrabajado") == "on"
        vacation_pending_complete = int(request.form.get("vacationPendingCompleteYears", "0") or 0)
        vacation_taken_current = int(request.form.get("vacationTakenCurrentPeriod", "0") or 0)
        notes = request.form.get("notes", "").strip()

        base_salary = float(employee.get("baseSalary", 0) or 0)
        salary_frequency = employee.get("paymentFrequency", "") or "mensual"

        # Usar salarios de los últimos 12 meses desde el historial salarial
        salaries_12 = [base_salary]
        try:
            salary_history = hr.get_salary_history(owner_uid, employee_id, sandbox=sandbox)
            if salary_history:
                recent = sorted(salary_history, key=lambda x: x.get("effectiveDate", ""), reverse=True)[:12]
                salaries_12 = [s.get("amount", base_salary) for s in recent if s.get("amount")]
                if not salaries_12:
                    salaries_12 = [base_salary]
        except Exception:
            salaries_12 = [base_salary]

        # Salarios año corriente (enero a fecha de salida)
        try:
            if termination_date:
                td = datetime.strptime(termination_date, "%Y-%m-%d")
                months_ytd = td.month
            else:
                months_ytd = date.today().month
        except ValueError:
            months_ytd = date.today().month
        salaries_ytd = [base_salary] * max(1, months_ytd)

        resultado = LiquidacionService.calcular_liquidacion(
            employee_id=employee_id,
            employee_name=employee.get("fullName", ""),
            cedula=employee.get("cedula", ""),
            hire_date=employee.get("hireDate", ""),
            termination_date=termination_date,
            termination_type=termination_type,
            last_base_salary=base_salary,
            salary_frequency=salary_frequency,
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            preaviso_trabajado=preaviso_trabajado,
            vacation_pending_complete_years=vacation_pending_complete,
            vacation_taken_current_period=vacation_taken_current,
            notes=notes,
            created_by=session.get("user", {}).get("email", ""),
        )

        # Persistir en Firestore
        save_action = request.form.get("save", "").strip()
        if save_action == "1":
            hr.save_liquidacion(owner_uid, resultado["id"], resultado, sandbox=sandbox)
            from app.services.payroll_audit_service import log_action
            log_action(owner_uid, "liquidacion_calculada", "employee", employee_id,
                       session.get("user", {}).get("email", ""),
                       changes={
                           "liquidacionId": resultado["id"],
                           "terminationType": termination_type,
                           "montoTotal": resultado["totales"]["montoTotal"],
                       }, sandbox=sandbox)

            flash("Liquidación calculada y guardada. Use el módulo Offboarding para completar la desvinculación.", "info")
            return redirect(url_for("web_rrhh.offboarding_new", employee_id=employee_id))

    return render_template("rrhh/employee_liquidacion.html",
                           active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee),
                           resultado=resultado,
                           vacation_auto_pending_complete=vacation_auto_pending_complete,
                           vacation_auto_taken_current=vacation_auto_taken_current,
                           vacation_auto_total_accrued=vacation_auto_total_accrued,
                           vacation_auto_total_taken=vacation_auto_total_taken)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/liquidaciones")
def employee_liquidaciones_list(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    liquidaciones = hr.get_liquidaciones_by_employee(owner_uid, employee_id, sandbox=sandbox)
    return render_template("rrhh/employee_liquidaciones_list.html",
                           active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee),
                           liquidaciones=liquidaciones)

