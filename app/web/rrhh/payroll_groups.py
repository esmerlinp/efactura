"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
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

    return render_template("rrhh/payroll_groups_view.html", active_page="rrhh_payroll",
                           group=group, assigned=assigned, unassigned=unassigned,
                           periods=periods)


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


