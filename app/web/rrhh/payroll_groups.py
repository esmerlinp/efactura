"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from datetime import datetime, timezone
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from uuid import uuid4


# ═══════════════════════════════════════════════════════════════════════════
# GRUPOS DE NÓMINA — CRUD
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/groups")
def payroll_groups_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    groups.sort(key=lambda g: g.get("name", ""))
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    group_employee_counts = {}
    for g in groups:
        gid = g["id"]
        group_employee_counts[gid] = len([e for e in employees if gid in e.get("payrollGroupIds", [])])
    return render_template("rrhh/payroll_groups.html", active_page="rrhh_payroll",
                           groups=groups, group_employee_counts=group_employee_counts)


@web_rrhh_bp.route("/rrhh/payroll/groups/new", methods=["GET", "POST"])
def payroll_groups_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        desc = request.form.get("description", "").strip()
        frequency = request.form.get("frequency", "mensual").strip()
        if not name:
            flash("El nombre del grupo es obligatorio.", "error")
            return render_template("rrhh/payroll_groups_form.html", active_page="rrhh_payroll", group=None)
        from uuid import uuid4
        gid = str(uuid4())
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {
            "id": gid, "name": name, "description": desc,
            "frequency": frequency,
            "isActive": True,
            "createdAt": now_iso, "updatedAt": now_iso,
            "createdBy": session.get("user", {}).get("email", ""),
        }
        hr.save_payroll_group(owner_uid, gid, data, sandbox=sandbox)
        flash(f"Grupo de nómina «{name}» creado.", "success")
        return redirect(url_for("web_rrhh.payroll_groups_list"))
    return render_template("rrhh/payroll_groups_form.html", active_page="rrhh_payroll", group=None)


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/edit", methods=["GET", "POST"])
def payroll_groups_edit(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    if request.method == "POST":
        group["name"] = request.form.get("name", "").strip()
        group["description"] = request.form.get("description", "").strip()
        group["frequency"] = request.form.get("frequency", "mensual").strip()
        group["isActive"] = request.form.get("isActive") == "on"
        group["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        hr.save_payroll_group(owner_uid, group_id, group, sandbox=sandbox)
        flash(f"Grupo «{group['name']}» actualizado.", "success")
        return redirect(url_for("web_rrhh.payroll_groups_list"))
    return render_template("rrhh/payroll_groups_form.html", active_page="rrhh_payroll", group=group)


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/delete", methods=["POST"])
def payroll_groups_delete(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    hr.delete_payroll_group(owner_uid, group_id, sandbox=sandbox)
    flash("Grupo eliminado.", "success")
    return redirect(url_for("web_rrhh.payroll_groups_list"))


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>")
def payroll_groups_view(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    assigned = [e for e in employees if group_id in e.get("payrollGroupIds", [])]
    unassigned = [e for e in employees if group_id not in e.get("payrollGroupIds", []) and e.get("status") == "activo"]

    periods = [p for p in hr.get_payroll_periods(owner_uid, sandbox=sandbox)
               if p.get("payrollGroupId") == group_id]
    periods.sort(key=lambda p: p.get("periodKey", ""), reverse=True)

    global_rates = hr.get_tax_rates(owner_uid, sandbox=sandbox) or {}
    from app.services.payroll_service import PayrollService
    from app.services.legal_parameter_resolver import resolve_all
    from datetime import date

    today_str = date.today().isoformat()
    legal_params = resolve_all(owner_uid, today_str, sandbox=sandbox)

    default_rates = PayrollService.get_rates(global_rates)
    # Los parámetros legales vienen de resolve_all(); las cuentas contables de get_tax_rates()
    global_rates = {
        "afpEmployeeRate": legal_params.get("afpEmployeeRate", default_rates["afp_employee_rate"]),
        "afpEmployerRate": legal_params.get("afpEmployerRate", default_rates["afp_employer_rate"]),
        "sfsEmployeeRate": legal_params.get("sfsEmployeeRate", default_rates["sfs_employee_rate"]),
        "sfsEmployerRate": legal_params.get("sfsEmployerRate", default_rates["sfs_employer_rate"]),
        "srlEmployerRate": legal_params.get("srlEmployerRate", default_rates["srl_employer_rate"]),
        "infotepRate": legal_params.get("infotepRate", default_rates["infotep_rate"]),
        "afpSalaryCap": legal_params.get("afpSalaryCap", default_rates["afp_salary_cap"]),
        "sfsSalaryCap": legal_params.get("sfsSalaryCap", default_rates["sfs_salary_cap"]),
        "minSalary": legal_params.get("minSalary", default_rates["min_salary"]),
        "educationDeduction": legal_params.get("educationDeduction", default_rates["education_deduction"]),
        "overtimeRate": legal_params.get("overtimeRate", default_rates["overtime_rate"]),
        "workingDaysPerMonth": legal_params.get("workingDaysPerMonth", default_rates["working_days_per_month"]),
        "workingHoursPerDay": legal_params.get("workingHoursPerDay", default_rates["working_hours_per_day"]),
        "infotepThresholdMultiplier": legal_params.get("infotepThresholdMultiplier", default_rates["infotep_threshold_multiplier"]),
        "accountSalariesPayable": global_rates.get("accountSalariesPayable", default_rates["account_salaries_payable"]),
        "accountAfpEmployee": global_rates.get("accountAfpEmployee", default_rates["account_afp_employee"]),
        "accountSfsEmployee": global_rates.get("accountSfsEmployee", default_rates["account_sfs_employee"]),
        "accountIsrEmployee": global_rates.get("accountIsrEmployee", default_rates["account_isr_employee"]),
        "accountAfpEmployer": global_rates.get("accountAfpEmployer", default_rates["account_afp_employer"]),
        "accountSfsEmployer": global_rates.get("accountSfsEmployer", default_rates["account_sfs_employer"]),
        "accountSrlEmployer": global_rates.get("accountSrlEmployer", default_rates["account_srl_employer"]),
        "accountInfotepEmployer": global_rates.get("accountInfotepEmployer", default_rates["account_infotep_employer"]),
        "costCenterAccounts": global_rates.get("costCenterAccounts", default_rates["cost_center_accounts"]),
    }
    group_overrides = group.get("groupOverrides", {})
    return render_template("rrhh/payroll_groups_view.html", active_page="rrhh_payroll",
                           group=group, assigned=assigned, unassigned=unassigned,
                           periods=periods, global_rates=global_rates,
                           group_overrides=group_overrides)


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/assign", methods=["POST"])
def payroll_groups_assign(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    employee_ids = request.form.getlist("employee_ids")
    count = 0
    for emp_id in employee_ids:
        emp = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
        if not emp:
            continue
        current = emp.get("payrollGroupIds", [])
        if group_id not in current:
            current = list(current) + [group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, emp_id, emp, sandbox=sandbox)
            count += 1

    flash(f"{count} empleado(s) asignado(s) al grupo «{group.get('name', '')}».", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/assign-async", methods=["POST"])
def payroll_groups_assign_async(group_id):
    if _login_required():
        return {"success": False, "message": "No autenticado."}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        return {"success": False, "message": "Grupo no encontrado."}, 404

    data = request.get_json(silent=True) or {}
    employee_ids = data.get("employee_ids", [])
    if isinstance(employee_ids, str):
        employee_ids = [employee_ids]

    count = 0
    for emp_id in employee_ids:
        emp = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
        if not emp:
            continue
        current = emp.get("payrollGroupIds", [])
        if group_id not in current:
            current = list(current) + [group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, emp_id, emp, sandbox=sandbox)
            count += 1

    return {"success": True, "count": count, "message": f"{count} empleado(s) asignado(s)."}


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/unassign-async", methods=["POST"])
def payroll_groups_unassign_async(group_id):
    if _login_required():
        return {"success": False, "message": "No autenticado."}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        return {"success": False, "message": "Grupo no encontrado."}, 404

    data = request.get_json(silent=True) or {}
    employee_ids = data.get("employee_ids", [])
    if isinstance(employee_ids, str):
        employee_ids = [employee_ids]

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    if employee_ids:
        employees = [e for e in employees if e["id"] in employee_ids]

    count = 0
    for emp in employees:
        current = emp.get("payrollGroupIds", [])
        if group_id in current:
            current = [g for g in current if g != group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, emp["id"], emp, sandbox=sandbox)
            count += 1

    return {"success": True, "count": count, "message": f"{count} empleado(s) removido(s)."}


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/unassign/<employee_id>", methods=["POST"])
def payroll_groups_unassign(group_id, employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    emp = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if emp:
        current = emp.get("payrollGroupIds", [])
        if group_id in current:
            current = [g for g in current if g != group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, employee_id, emp, sandbox=sandbox)

    flash("Empleado removido del grupo.", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/assign-all", methods=["POST"])
def payroll_groups_assign_all(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    count = 0
    for emp in employees:
        if emp.get("status") != "activo":
            continue
        current = emp.get("payrollGroupIds", [])
        if group_id not in current:
            current = list(current) + [group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, emp["id"], emp, sandbox=sandbox)
            count += 1

    flash(f"{count} empleado(s) asignado(s) al grupo «{group.get('name', '')}».", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/unassign-all", methods=["POST"])
def payroll_groups_unassign_all(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    specific_ids = request.form.getlist("employee_ids")
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    if specific_ids:
        employees = [e for e in employees if e["id"] in specific_ids]

    count = 0
    for emp in employees:
        current = emp.get("payrollGroupIds", [])
        if group_id in current:
            current = [g for g in current if g != group_id]
            emp["payrollGroupIds"] = current
            hr.save_employee(owner_uid, emp["id"], emp, sandbox=sandbox)
            count += 1

    flash(f"{count} empleado(s) removido(s) del grupo «{group.get('name', '')}».", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN ESPECÍFICA DEL GRUPO (GroupOverrides)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/settings", methods=["POST"])
def payroll_groups_save_settings(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    group_overrides = {}

    # ── Toggles de componentes de ingreso ──
    group_overrides["includeBaseSalary"] = request.form.get("includeBaseSalary") == "on"
    group_overrides["includeCommission"] = request.form.get("includeCommission") == "on"
    group_overrides["includeOvertime"] = request.form.get("includeOvertime") == "on"
    group_overrides["includeBonus"] = request.form.get("includeBonus") == "on"
    group_overrides["includeOtherIncome"] = request.form.get("includeOtherIncome") == "on"

    # ── Override de cuentas contables (solo guardar si NO usa el valor global) ──
    account_fields = [
        "accountSalariesPayable", "accountAfpEmployee",
        "accountSfsEmployee", "accountIsrEmployee",
        "accountAfpEmployer", "accountSfsEmployer",
        "accountSrlEmployer", "accountInfotepEmployer",
    ]
    for field in account_fields:
        use_global = request.form.get(f"{field}_use_global") == "on"
        if use_global:
            group_overrides[field] = None
        else:
            raw = request.form.get(field, "").strip()
            group_overrides[field] = raw if raw else None

    cost_centers_raw = request.form.get("costCenterAccounts", "").strip()
    if cost_centers_raw:
        try:
            import json
            parsed = json.loads(cost_centers_raw)
            if isinstance(parsed, dict) and len(parsed) > 0:
                group_overrides["costCenterAccounts"] = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    group["groupOverrides"] = group_overrides
    group["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hr.save_payroll_group(owner_uid, group_id, group, sandbox=sandbox)

    flash(f"Configuración guardada para el grupo «{group.get('name', '')}».", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


# ═══════════════════════════════════════════════════════════════════════════
# ASIGNACIÓN DE SALARIO POR GRUPO (ContractGroupAssignment)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/groups/<group_id>/assign-salary", methods=["POST"])
def payroll_groups_assign_salary(group_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from datetime import datetime, timezone
    import uuid

    group = hr.get_payroll_group(owner_uid, group_id, sandbox=sandbox)
    if not group:
        flash("Grupo no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_list"))

    contract_id = request.form.get("contract_id", "").strip()
    employee_id = request.form.get("employee_id", "").strip()
    assigned_salary = float(request.form.get("assigned_salary", 0) or 0)
    cost_center = request.form.get("cost_center", "").strip()
    position = request.form.get("position", "").strip()

    if not contract_id and not employee_id:
        flash("Debe especificar un empleado o contrato.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))

    if not assigned_salary or assigned_salary <= 0:
        flash("Debe especificar un salario asignado válido.", "error")
        return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))

    now_iso = datetime.now(timezone.utc).isoformat()
    assignment_id = str(uuid.uuid4())
    data = {
        "id": assignment_id,
        "contractId": contract_id,
        "employeeId": employee_id,
        "groupId": group_id,
        "assignedSalary": assigned_salary,
        "costCenter": cost_center,
        "position": position,
        "effectiveFrom": now_iso,
        "effectiveTo": "",
        "createdBy": session.get("user", {}).get("email", ""),
        "createdAt": now_iso,
    }

    try:
        hr._save(owner_uid, "contract_group_assignments", assignment_id, data, sandbox)
    except Exception as e:
        flash(f"Error al guardar asignación: {e}", "error")
        return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))

    flash(f"Salario de RD$ {assigned_salary:,.2f} asignado al empleado en el grupo «{group.get('name', '')}».", "success")
    return redirect(url_for("web_rrhh.payroll_groups_view", group_id=group_id))


