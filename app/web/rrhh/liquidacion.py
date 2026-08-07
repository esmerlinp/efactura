"""RRHH module — auto-extracted."""

from datetime import date, datetime, timezone
from uuid import uuid4
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
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.liquidacion_service import LiquidacionService

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    hire_date = employee.get("hireDate", "")
    vac_requests = hr.get_vacation_requests(company_id, sandbox=sandbox)
    emp_vacs = [v for v in vac_requests
                if v.get("employeeId") == employee_id and v.get("status") == "aprobada"]

    def _auto_vacation(calc_date_str: str):
        ant_approx = LiquidacionService.calcular_antiguedad(hire_date, calc_date_str)
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

        return {
            "pending_complete": max(0, pending_complete),
            "taken_current": max(0, taken_current),
            "total_taken": sum(v.get("days", 0) for v in emp_vacs),
            "total_accrued": max_expected,
            "dias_pendientes": max(0, max_expected - sum(v.get("days", 0) for v in emp_vacs)),
        }

    if request.method == "POST":
        ref_date = request.form.get("terminationDate", "").strip()
    else:
        ref_date = ""
    calc_date = ref_date if ref_date else date.today().isoformat()
    vac = _auto_vacation(calc_date)

    vacation_auto_pending_complete = vac["pending_complete"]
    vacation_auto_taken_current = vac["taken_current"]
    vacation_auto_total_taken = vac["total_taken"]
    vacation_auto_total_accrued = vac["total_accrued"]
    vacation_auto_dias_pendientes = vac["dias_pendientes"]

    resultado = None

    if request.method == "POST":
        termination_type = request.form.get("terminationType", "renuncia").strip()
        termination_date = request.form.get("terminationDate", "").strip()
        preaviso_trabajado = request.form.get("preavisoTrabajado") == "on"
        vacation_pending_complete = int(request.form.get("vacationPendingCompleteYears", "0") or 0)
        vacation_taken_current = int(request.form.get("vacationTakenCurrentPeriod", "0") or 0)
        vacation_dias_pendientes_val = int(request.form.get("vacationDiasPendientes",
            str(vacation_auto_dias_pendientes) if vacation_auto_dias_pendientes else "0") or 0)
        notes = request.form.get("notes", "").strip()

        base_salary = float(employee.get("baseSalary", 0) or 0)
        salary_frequency = employee.get("paymentFrequency", "") or "mensual"
        is_variable = employee.get("isVariableSalary", False)
        dias_adeudados = int(request.form.get("diasAdeudados", "0") or 0)

        # SDP: para salario fijo, usar el salario base actual directamente
        if not is_variable:
            salaries_12 = [base_salary]
        else:
            salaries_12 = [base_salary]
            try:
                salary_history = hr.get_salary_history(company_id, employee_id, sandbox=sandbox)
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

        salaries_ytd = [base_salary]
        try:
            if salary_history:
                current_year = (datetime.strptime(termination_date, "%Y-%m-%d") if termination_date else datetime.now()).year
                ytd_entries = sorted(
                    [s for s in salary_history if s.get("effectiveDate", "").startswith(str(current_year))],
                    key=lambda x: x.get("effectiveDate", "")
                )
                if ytd_entries:
                    salaries_ytd = [s.get("amount", base_salary) for s in ytd_entries]
        except Exception:
            salaries_ytd = [base_salary] * max(1, months_ytd)

        # Excluir el mes actual incompleto (ya se prorratea via dias_extra_navidad)
        if len(salaries_ytd) >= months_ytd and salaries_ytd:
            salaries_ytd = salaries_ytd[:-1]

        # Normalizar tipo de terminación
        nt = LiquidacionService._normalizar_terminacion(termination_type)

        # Días extra del mes de salida (para regalía proporcional)
        dias_extra_navidad = 0
        try:
            td = datetime.strptime(termination_date, "%Y-%m-%d")
            dias_extra_navidad = td.day
        except Exception:
            pass

        resultado = LiquidacionService.calcular_liquidacion(
            employee_id=employee_id,
            employee_name=employee.get("fullName", ""),
            cedula=employee.get("cedula", ""),
            hire_date=employee.get("hireDate", ""),
            termination_date=termination_date,
            termination_type=nt,
            last_base_salary=base_salary,
            salary_frequency=salary_frequency,
            is_variable_salary=employee.get("isVariableSalary", False),
            monthly_salaries_last_12=salaries_12,
            monthly_salaries_ytd=salaries_ytd,
            preaviso_trabajado=preaviso_trabajado,
            vacation_pending_complete_years=vacation_pending_complete,
            vacation_taken_current_period=vacation_taken_current,
            vacation_dias_pendientes=vacation_dias_pendientes_val,
            dias_adeudados=dias_adeudados,
            dias_extra_navidad=dias_extra_navidad,
            notes=notes,
            created_by=session.get("user", {}).get("email", ""),
        )

        # Persistir en Firestore
        save_action = request.form.get("save", "").strip()
        if save_action == "1":
            hr.save_liquidacion(company_id, resultado["id"], resultado, sandbox=sandbox)
            from app.services.payroll_audit_service import log_action
            log_action(company_id, "liquidacion_calculada", "employee", employee_id,
                       session.get("user", {}).get("email", ""),
                       changes={
                           "liquidacionId": resultado["id"],
                           "terminationType": termination_type,
                           "montoTotal": resultado["totales"]["montoTotal"],
                       }, sandbox=sandbox)

            from app.services.offboarding_service import OffboardingService
            off_mode = session.get("company_offboarding_mode", "simple")
            svc = OffboardingService(company_id, sandbox, offboarding_mode=off_mode)
            user_email = session.get("user", {}).get("email", "")

            req_data = {
                "employeeId": employee_id,
                "employeeName": employee.get("fullName", ""),
                "cedula": employee.get("cedula", ""),
                "departmentId": employee.get("departmentId", ""),
                "positionId": employee.get("positionId", ""),
                "supervisorId": employee.get("supervisorId", ""),
                "requestDate": date.today().isoformat(),
                "effectiveDate": termination_date,
                "lastWorkDate": termination_date,
                "terminationType": termination_type,
                "terminationReason": "Liquidación calculada desde ficha del empleado",
                "initiatedBy": user_email,
                "initiatedByRole": session.get("user", {}).get("role", ""),
            }
            req = svc.create_request(req_data, user_email)
            svc.init_checklist(req.id, employee_id)

            result_copy = dict(resultado)
            result_copy["requestId"] = req.id
            result_copy["terminationType"] = termination_type
            result_copy["terminationDate"] = termination_date
            svc.save_settlement(result_copy, user_email)

            if svc.is_simple:
                try:
                    svc.wizard_transition(req.id, "pending_settlement", user_email)
                except Exception:
                    pass

            flash("Liquidación guardada y solicitud de desvinculación creada.", "success")
            return redirect(url_for("web_rrhh.offboarding_wizard", request_id=req.id))

    return render_template("rrhh/employee_liquidacion.html",
                           active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee),
                           resultado=resultado,
                           vacation_auto_pending_complete=vacation_auto_pending_complete,
                           vacation_auto_taken_current=vacation_auto_taken_current,
                           vacation_auto_total_accrued=vacation_auto_total_accrued,
                           vacation_auto_total_taken=vacation_auto_total_taken,
                           vacation_auto_dias_pendientes=vacation_auto_dias_pendientes)


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/liquidaciones")
def employee_liquidaciones_list(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    liquidaciones = hr.get_liquidaciones_by_employee(company_id, employee_id, sandbox=sandbox)
    return render_template("rrhh/employee_liquidaciones_list.html",
                           active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee),
                           liquidaciones=liquidaciones)


@web_rrhh_bp.route("/rrhh/payroll/liquidaciones-pendientes")
def payroll_liquidaciones_pendientes():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.offboarding_service import OffboardingService
    from app.services import hr_data_service as hr

    svc = OffboardingService(company_id, sandbox)
    settlements = svc.get_pending_settlements()
    payroll_groups = hr.get_payroll_groups(company_id, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    employees = {}
    for s in settlements:
        req_id = s.get("requestId", "")
        if req_id:
            req = svc.get_request(req_id)
            if req:
                emp_id = req.get("employeeId", "")
                emp = hr.get_employee(company_id, emp_id, sandbox=sandbox)
                if emp:
                    employees[s["id"]] = _sanitize_for_role(emp)

    return render_template("rrhh/payroll_liquidaciones_pendientes.html",
                           active_page="rrhh_payroll",
                           settlements=settlements,
                           employees=employees,
                           payroll_groups=payroll_groups)


@web_rrhh_bp.route("/rrhh/payroll/liquidaciones-pendientes/assign", methods=["POST"])
def payroll_liquidaciones_assign():
    if _login_required():
        return jsonify({"success": False, "message": "No autenticado."}), 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.offboarding_service import OffboardingService
    from app.services import hr_data_service as hr

    data = request.get_json(silent=True) or {}
    settlement_ids = data.get("settlement_ids", [])
    group_id = data.get("group_id", "").strip()
    new_group_name = data.get("new_group_name", "").strip()

    if not settlement_ids:
        return jsonify({"success": False, "message": "No se seleccionaron liquidaciones."})

    svc = OffboardingService(company_id, sandbox)

    if not group_id and new_group_name:
        new_group = {
            "id": str(uuid4()),
            "name": new_group_name,
            "description": "Grupo generado automáticamente para pago de liquidaciones",
            "frequency": "mensual",
            "isActive": True,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdBy": session.get("user", {}).get("email", ""),
        }
        hr.save_payroll_group(company_id, new_group["id"], new_group, sandbox=sandbox)
        group_id = new_group["id"]
        group_name = new_group_name
    elif group_id:
        group = hr.get_payroll_group(company_id, group_id, sandbox=sandbox)
        group_name = group.get("name", group_id) if group else group_id
    else:
        return jsonify({"success": False, "message": "Debe seleccionar o crear un grupo."})

    assigned = 0
    for s_id in settlement_ids:
        settlement = svc.get_settlement(s_id)
        if not settlement:
            continue
        req_id = settlement.get("requestId", "")
        req = svc.get_request(req_id) if req_id else None
        emp_id = req.get("employeeId", "") if req else ""

        if emp_id:
            emp = hr.get_employee(company_id, emp_id, sandbox=sandbox)
            if emp:
                current_groups = emp.get("payrollGroupIds", [])
                if group_id not in current_groups:
                    current_groups = list(current_groups) + [group_id]
                    emp["payrollGroupIds"] = current_groups
                    hr.save_employee(company_id, emp_id, emp, sandbox=sandbox)

        settlement["assignedGroupId"] = group_id
        settlement["assignedGroupName"] = group_name
        settlement["assignedAt"] = datetime.now(timezone.utc).isoformat()
        from app.services.offboarding_data_service import save as ods_save
        ods_save("offboarding_settlements", s_id, settlement, company_id, sandbox)
        assigned += 1

    log_action(company_id, "settlements_assigned_to_group", "offboarding_settlement",
               group_id, session.get("user", {}).get("email", ""),
               {"count": assigned, "groupName": group_name}, sandbox=sandbox)

    return jsonify({
        "success": True,
        "assigned": assigned,
        "group_id": group_id,
        "group_name": group_name,
        "message": f"{assigned} liquidación(es) asignada(s) al grupo «{group_name}»."
    })

