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
from app.services import payroll_concept_engine as concept_engine
from app.services import recurring_service as recurring_svc



# ═══════════════════════════════════════════════════════════════════════════
# LIQUIDACIÓN LABORAL — Cálculo de Prestaciones y Derechos Adquiridos
# ═══════════════════════════════════════════════════════════════════════════

def _concepts_available(company_id: str, sandbox: bool) -> list:
    """Conceptos activos de nómina (ingresos y descuentos) para los dropdowns."""
    try:
        concepts = concept_engine.get_concepts(company_id, sandbox=sandbox)
    except Exception:
        concepts = []
    defaults = {c.get("code", ""): c for c in getattr(concept_engine, "DEFAULT_CONCEPTS", [])}
    result = []
    for c in concepts:
        if not c.get("active"):
            continue
        if c.get("type") not in ("earning", "deduction"):
            continue
        dc = defaults.get(c.get("code", ""), {})
        taxable = c.get("taxable", dc.get("taxable", False))
        affects_afp = c.get("affects_afp", dc.get("affects_afp", False))
        affects_sfs = c.get("affects_sfs", dc.get("affects_sfs", False))
        result.append({
            "code": c.get("code", ""),
            "name": c.get("name", c.get("code", "")),
            "type": c.get("type", "earning"),
            "taxable": bool(taxable),
            "affects_tss": bool(affects_afp or affects_sfs),
        })
    return result


def _parse_additional_concepts(form) -> list:
    """Parse filas dinámicas de conceptos adicionales desde el formulario."""
    codes = form.getlist("ac_concept")
    montos = form.getlist("ac_monto")
    comments = form.getlist("ac_comment")
    names = form.getlist("ac_name")
    types = form.getlist("ac_type")
    taxables = form.getlist("ac_taxable")
    affects_tss = form.getlist("ac_affects_tss")

    rows = []
    for i, code in enumerate(codes):
        code = (code or "").strip()
        if not code:
            continue
        try:
            monto = float(montos[i] if i < len(montos) else 0)
        except (ValueError, TypeError, IndexError):
            monto = 0.0
        if monto == 0.0:
            continue
        rows.append({
            "id": str(uuid4()),
            "conceptCode": code,
            "name": (names[i] if i < len(names) else "") or code,
            "monto": monto,
            "comment": comments[i] if i < len(comments) else "",
            "type": types[i] if i < len(types) else "earning",
            "taxable": (taxables[i] if i < len(taxables) else "0") == "1",
            "affectsTSS": (affects_tss[i] if i < len(affects_tss) else "0") == "1",
        })
    return rows


def _parse_deductions(form) -> list:
    """Parse filas de descuentos recurrentes (auto + editables) desde el formulario."""
    movement_ids = form.getlist("dd_movementId")
    concept_codes = form.getlist("dd_conceptCode")
    names = form.getlist("dd_name")
    montos = form.getlist("dd_monto")
    tipos = form.getlist("dd_tipo")
    aplicas = form.getlist("dd_aplica")

    rows = []
    for i, mid in enumerate(movement_ids):
        try:
            monto = float(montos[i] if i < len(montos) else 0)
        except (ValueError, TypeError, IndexError):
            monto = 0.0
        rows.append({
            "movementId": mid,
            "id": mid,
            "conceptCode": concept_codes[i] if i < len(concept_codes) else "",
            "name": names[i] if i < len(names) else "",
            "monto": monto,
            "tipo": tipos[i] if i < len(tipos) else "otro",
            "aplica": (aplicas[i] if i < len(aplicas) else "1") == "1",
        })
    return rows

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

    # Ver detalle de una liquidación guardada (solo lectura, GET). Permitido
    # también para empleados inactivos: su salida ya quedó registrada.
    _view_id = request.args.get("view", "").strip()
    if _view_id and request.method == "GET":
        saved = hr.get_liquidacion(company_id, _view_id, sandbox=sandbox)
        if not saved:
            flash("Liquidación no encontrada.", "error")
            return redirect(url_for("web_rrhh.employee_liquidaciones_list", employee_id=employee_id))
        return render_template("rrhh/employee_liquidacion.html",
                               active_page="rrhh_employees",
                               employee=_sanitize_for_role(employee),
                               resultado=saved,
                               concepts_available=[],
                               additional_rows=[],
                               deduction_rows=[],
                               salario_promedio=saved.get("salarioPromedioMensual", 0),
                               vacation_auto_pending_complete=0,
                               vacation_auto_taken_current=0,
                               vacation_auto_total_accrued=0,
                               vacation_auto_total_taken=0,
                               vacation_auto_dias_pendientes=0)

    if (employee.get("status") or "") == "inactivo":
        flash("El empleado está inactivo. La única acción permitida es la reincorporación.", "warning")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    # Contexto laboral único: contrato correspondiente a la fecha de referencia
    # (terminación informada o hoy). Ambigüedad → se bloquea; sin contrato → legacy.
    from app.services.employment_context_service import (
        EmploymentContextError, build_context, filter_movements,
        filter_transactions, get_transactions_for_context,
    )
    if request.method == "POST":
        _ref_date = request.form.get("terminationDate", "").strip()
    else:
        _ref_date = request.args.get("terminationDate", "").strip()
    _liq_ctx = None
    try:
        from app.services.employment_context_service import resolve_for_employee
        _liq_ctx = resolve_for_employee(company_id, employee, _ref_date, sandbox=sandbox)
    except EmploymentContextError as e:
        flash(str(e), "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))
    except Exception:
        _liq_ctx = None
    if _liq_ctx is None:
        _liq_ctx = build_context(employee, None)
    # Antigüedad legal: seniorityBaseDate del contrato (reset=startDate, preserve=fecha explícita).
    hire_date = _liq_ctx.get("seniorityBaseDate") or employee.get("hireDate", "")
    _liq_contract_id = _liq_ctx.get("contractId", "")
    _liq_start = _liq_ctx.get("startDate", "")
    _liq_end = _liq_ctx.get("endDate", "")
    vac_requests = hr.get_vacation_requests(company_id, sandbox=sandbox)
    emp_vacs = [v for v in vac_requests
                if v.get("employeeId") == employee_id and v.get("status") == "aprobada"]
    if not _liq_ctx.get("isLegacy"):
        # Solo vacaciones del período (legacy dentro del rango por fecha).
        _scoped_vacs = []
        for _v in emp_vacs:
            _vcid = (_v.get("contractId") or "").strip()
            if _vcid:
                if _vcid == _liq_contract_id:
                    _scoped_vacs.append(_v)
            elif (_v.get("startDate", "") or "") >= (_liq_ctx.get("vacationBaseDate") or ""):
                _scoped_vacs.append(_v)
        emp_vacs = _scoped_vacs

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

    concepts_available = _concepts_available(company_id, sandbox)
    recurring_movements = filter_movements(
        recurring_svc.get_recurring_movements(
            company_id, employee_id=employee_id, sandbox=sandbox
        ), _liq_ctx)
    deduction_rows = LiquidacionService.build_recurring_deductions(recurring_movements)
    additional_rows = []

    # Salario promedio (base + conceptos que cotizan TSS) para la card de datos.
    # Aislado al contrato: no mezcla salarios de otros períodos del empleado.
    salario_promedio = float(employee.get("averageSalary", 0) or 0)
    try:
        txs = get_transactions_for_context(company_id, employee_id, _liq_ctx, sandbox=sandbox)
        prom = LiquidacionService.calcular_salario_promedio_mensual(
            txs, contract_id=_liq_contract_id, start_date=_liq_start, end_date=_liq_end)
        if prom.get("promedio_mensual", 0) > 0:
            salario_promedio = prom["promedio_mensual"]
    except Exception:
        pass
    if salario_promedio <= 0:
        salario_promedio = float(_liq_ctx.get("salary", 0) or employee.get("baseSalary", 0) or 0)

    if request.method == "POST":
        termination_type = request.form.get("terminationType", "renuncia").strip()
        termination_date = request.form.get("terminationDate", "").strip()
        preaviso_trabajado = request.form.get("preavisoTrabajado") == "on"
        vacation_pending_complete = int(request.form.get("vacationPendingCompleteYears", "0") or 0)
        vacation_taken_current = int(request.form.get("vacationTakenCurrentPeriod", "0") or 0)
        vacation_dias_pendientes_val = int(request.form.get("vacationDiasPendientes",
            str(vacation_auto_dias_pendientes) if vacation_auto_dias_pendientes else "0") or 0)
        notes = request.form.get("notes", "").strip()
        keep_in_current_payroll = request.form.get("keepInCurrentPayroll") == "1"

        base_salary = float(_liq_ctx.get("salary", 0) or employee.get("baseSalary", 0) or 0)
        salary_frequency = employee.get("paymentFrequency", "") or "mensual"
        dias_adeudados = int(request.form.get("diasAdeudados", "0") or 0)
        if keep_in_current_payroll:
            dias_adeudados = 0

        # Salario promedio real aislado al contrato que se liquida.
        promedio_mensual = float(employee.get("averageSalary", 0) or 0)
        salaries_12 = [base_salary]
        salaries_ytd = [base_salary]
        scoped_txs = []
        try:
            scoped_txs = get_transactions_for_context(company_id, employee_id, _liq_ctx, sandbox=sandbox)
            prom = LiquidacionService.calcular_salario_promedio_mensual(
                scoped_txs, contract_id=_liq_contract_id, start_date=_liq_start, end_date=_liq_end)
            if prom.get("promedio_mensual", 0) > 0:
                promedio_mensual = prom["promedio_mensual"]
                salaries_12 = prom.get("monthly_totals_last_12") or [promedio_mensual]
                ytd = prom.get("monthly_salaries_ytd") or []
                if ytd:
                    salaries_ytd = ytd
        except Exception:
            pass

        if promedio_mensual <= 0:
            promedio_mensual = base_salary
            salaries_12 = [base_salary]

        # Normalizar tipo de terminación
        nt = LiquidacionService._normalizar_terminacion(termination_type)

        # Días extra del mes de salida (para regalía proporcional)
        dias_extra_navidad = 0
        try:
            td = datetime.strptime(termination_date, "%Y-%m-%d")
            dias_extra_navidad = td.day
        except Exception:
            pass

        # Conceptos adicionales y descuentos recurrentes (filas dinámicas editables)
        additional_rows = _parse_additional_concepts(request.form)
        deduction_rows = _parse_deductions(request.form)

        resultado = LiquidacionService.calcular_liquidacion(
            employee_id=employee_id,
            employee_name=employee.get("fullName", ""),
            cedula=employee.get("cedula", ""),
            hire_date=hire_date,
            termination_date=termination_date,
            termination_type=nt,
            last_base_salary=base_salary,
            contract_id=_liq_contract_id,
            employment_context=_liq_ctx,
            salary_transactions_used=scoped_txs,
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
            recurring_deductions=deduction_rows,
            additional_concepts=additional_rows,
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
            off_mode = "simple"
            svc = OffboardingService(company_id, sandbox, offboarding_mode=off_mode)
            user_email = session.get("user", {}).get("email", "")

            existing = svc.get_active_request_for_employee(employee_id)
            if existing:
                flash("El empleado ya tiene un proceso de desvinculación abierto.", "error")
                return redirect(url_for("web_rrhh.offboarding_wizard", request_id=existing.get("id", "")))

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
                "keepInCurrentPayroll": keep_in_current_payroll,
            }
            req = svc.create_request(req_data, user_email)
            svc.init_checklist(req.id, employee_id)

            result_copy = dict(resultado)
            result_copy["requestId"] = req.id
            result_copy["terminationType"] = termination_type
            result_copy["terminationDate"] = termination_date
            svc.save_settlement(result_copy, user_email)

            # Gate de autorización (modo simple): con regla de desvinculación
            # activa, la solicitud queda en borrador esperando el quórum.
            # Aquí la liquidación YA está calculada, así que viaja como
            # metadata para que el aprobador vea el esquema completo.
            from app.web.rrhh.offboarding import _termination_auth_gate, _prestaciones_metadata
            gate = _termination_auth_gate(
                svc, req.id, company_id, owner_uid, sandbox,
                metadata=_prestaciones_metadata(result_copy, req_data))
            if gate["approved"]:
                svc.deactivate_employee(req.model_dump())
                if svc.is_simple:
                    try:
                        svc.wizard_transition(req.id, "pending_settlement", user_email)
                    except Exception:
                        pass
                flash("Liquidación guardada y solicitud de desvinculación creada.", "success")
            else:
                flash("Liquidación guardada y solicitud enviada a autorización. "
                      "Quedará en espera hasta alcanzar el quórum de firmas.", "success")
            return redirect(url_for("web_rrhh.offboarding_wizard", request_id=req.id))

    return render_template("rrhh/employee_liquidacion.html",
                           active_page="rrhh_employees",
                           employee=_sanitize_for_role(employee),
                           resultado=resultado,
                           concepts_available=concepts_available,
                           additional_rows=additional_rows,
                           deduction_rows=deduction_rows,
                           salario_promedio=salario_promedio,
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
                emp["payrollGroupIds"] = [group_id]
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

