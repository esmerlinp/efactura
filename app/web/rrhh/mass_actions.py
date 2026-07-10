"""RRHH module — auto-extracted."""

from datetime import date, datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService


# ═══════════════════════════════════════════════════════════════════════════
# ACCIONES DE PERSONAL MASIVAS
# ═══════════════════════════════════════════════════════════════════════════

MASS_ACTION_TYPES = {
    "salary_change": {
        "label": "Cambio de Salario",
        "icon": "fa-solid fa-money-bill-trend-up",
        "desc": "Ajuste salarial masivo por monto fijo o porcentaje.",
    },
    "position_change": {
        "label": "Cambio de Puesto",
        "icon": "fa-solid fa-briefcase",
        "desc": "Reasignación de cargo, área o departamento.",
    },
    "supervisor_change": {
        "label": "Cambio de Supervisor",
        "icon": "fa-solid fa-user-tie",
        "desc": "Reasignación masiva de reporting jerárquico.",
    },
    "promotion": {
        "label": "Promoción",
        "icon": "fa-solid fa-arrow-up",
        "desc": "Combinación de cambio de puesto y ajuste salarial.",
    },
    "mass_absence": {
        "label": "Ausencia Masiva",
        "icon": "fa-solid fa-calendar-xmark",
        "desc": "Vacaciones colectivas, permisos o licencias.",
    },
}


@web_rrhh_bp.route("/rrhh/employees/mass-action", methods=["GET"])
def mass_action_wizard():
    """Paso 1 y 2: wizard de acción masiva."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    ids_param = request.args.get("ids", "")
    employee_ids = [i for i in ids_param.split(",") if i] if ids_param else []

    employees = []
    if employee_ids:
        for eid in employee_ids:
            emp = hr.get_employee(owner_uid, eid, sandbox=sandbox)
            if emp:
                employees.append(emp)

    action_type = request.args.get("action_type", "")

    employees_data = []
    for emp in employees:
        from app.services.payroll_service import PayrollService
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
            "reportsTo": emp.get("reportsTo", ""),
            "vacationDays": vac_days,
        })

    all_employees_for_sup = hr.get_employees(owner_uid, sandbox=sandbox)
    supervisors = [e for e in all_employees_for_sup
                   if e.get("status") == "activo" and e.get("id") not in employee_ids]
    positions = hr.get_catalog(owner_uid, "positions", sandbox=sandbox)
    departments = hr.get_catalog(owner_uid, "departments", sandbox=sandbox)
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    frequency = config.get("payroll", {}).get("frequency", "mensual")

    try:
        now = date.today()
        payroll_periods = _generate_periods(frequency, now.year)
        if now.month < 12:
            payroll_periods += _generate_periods(frequency, now.year + 1)
    except Exception:
        payroll_periods = []

    return render_template(
        "rrhh/mass_action_wizard.html",
        active_page="rrhh_employees",
        action_type=action_type,
        action_types=MASS_ACTION_TYPES,
        employees=employees_data,
        employee_ids=employee_ids,
        supervisors=supervisors,
        positions=positions,
        departments=departments,
        payroll_periods=payroll_periods,
        now=datetime.now(),
    )


@web_rrhh_bp.route("/rrhh/employees/mass-action/preview", methods=["POST"])
def mass_action_preview():
    """Paso 4: previsualización (AJAX)."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    action_type = data.get("actionType", "")
    employee_ids = data.get("employeeIds", [])
    payload = data.get("payload", {})

    from app.services.mass_action_service import validate_action
    errors = validate_action(owner_uid, action_type, employee_ids, payload, sandbox=sandbox)

    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    employees = []
    for eid in employee_ids:
        emp = hr.get_employee(owner_uid, eid, sandbox=sandbox)
        if emp:
            vac_days = PayrollService.calculate_vacation_days(emp.get("hireDate", ""))
            employees.append({
                "id": emp.get("id", ""),
                "fullName": emp.get("fullName", ""),
                "cedula": emp.get("cedula", ""),
                "position": emp.get("position", ""),
                "department": emp.get("department", ""),
                "area": emp.get("area", ""),
                "baseSalary": emp.get("baseSalary", 0),
                "status": emp.get("status", ""),
                "vacationDays": vac_days,
            })

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "employees": employees,
        "affectedCount": len(employee_ids),
        "actionTypeLabel": MASS_ACTION_TYPES.get(action_type, {}).get("label", action_type),
        "payload": payload,
    }


@web_rrhh_bp.route("/rrhh/employees/mass-action/execute", methods=["POST"])
def mass_action_execute():
    """Paso 5: ejecutar la acción masiva."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    action_type = data.get("actionType", "")
    employee_ids = data.get("employeeIds", [])
    payload = data.get("payload", {})

    if not action_type or not employee_ids:
        return {"error": "Faltan datos requeridos."}, 400

    from app.services.mass_action_service import create_mass_action, execute_action, validate_action

    validation_errors = validate_action(owner_uid, action_type, employee_ids, payload, sandbox=sandbox)
    if validation_errors:
        return {"error": "Validación fallida.", "errors": validation_errors}, 400

    action = create_mass_action(owner_uid, action_type, employee_ids, payload, user_email, sandbox=sandbox)
    result = execute_action(owner_uid, action["id"], user_email, sandbox=sandbox)

    return {
        "actionId": result["id"],
        "status": result["status"],
        "successCount": result["successCount"],
        "errorCount": result["errorCount"],
        "totalEmployees": result["totalEmployees"],
    }


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>", methods=["GET"])
def mass_action_detail(action_id):
    """Detalle de una acción masiva específica."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    action = hr.get_mass_action(owner_uid, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    return render_template(
        "rrhh/mass_action_detail.html",
        active_page="rrhh_mass_actions",
        action=action,
        action_type_label=MASS_ACTION_TYPES.get(action.get("actionType", ""), {}).get("label", action.get("actionType", "")),
    )


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/errors.csv", methods=["GET"])
def mass_action_errors_csv(action_id):
    """Exportar los errores de una acción masiva a CSV."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    action = hr.get_mass_action(owner_uid, action_id, sandbox=sandbox)
    if not action:
        return {"error": "No encontrada"}, 404

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Empleado", "Cédula", "Campo", "Error"])
    for err in action.get("errorLog", []):
        writer.writerow([
            err.get("employeeName", ""),
            err.get("employeeId", ""),
            err.get("field", ""),
            err.get("message", ""),
        ])

    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"errores_accion_{action_id[:8]}.csv",
    )


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW DE APROBACIÓN DE ACCIONES MASIVAS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/submit", methods=["POST"])
def mass_action_submit(action_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from datetime import datetime, timezone

    action = hr.get_mass_action(owner_uid, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.mass_action_wizard"))

    if action.get("status") != "draft":
        flash("Solo se pueden enviar a aprobación acciones en estado borrador.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    now_iso = datetime.now(timezone.utc).isoformat()
    action["status"] = "pending_approval"
    action["submittedAt"] = now_iso
    history = action.get("statusHistory", [])
    history.append({"from": "draft", "to": "pending_approval", "by": session.get("user", {}).get("email", ""),
                     "at": now_iso, "comment": "Enviado a aprobación"})
    action["statusHistory"] = history
    hr.save_mass_action(owner_uid, action_id, action, sandbox=sandbox)
    flash("Acción masiva enviada a aprobación.", "success")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/approve", methods=["POST"])
def mass_action_approve(action_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from datetime import datetime, timezone

    action = hr.get_mass_action(owner_uid, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.mass_action_wizard"))

    if action.get("status") != "pending_approval":
        flash("Solo se pueden aprobar acciones en estado pendiente de aprobación.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    approver = session.get("user", {}).get("email", "")
    creator = action.get("createdBy", "")

    if approver == creator:
        flash("No puedes aprobar una acción que tú mismo creaste (Segregación de Funciones).", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    now_iso = datetime.now(timezone.utc).isoformat()
    action["status"] = "approved"
    action["approvedBy"] = approver
    action["approvedAt"] = now_iso
    history = action.get("statusHistory", [])
    history.append({"from": "pending_approval", "to": "approved", "by": approver,
                     "at": now_iso, "comment": request.form.get("comment", "Aprobado")})
    action["statusHistory"] = history
    hr.save_mass_action(owner_uid, action_id, action, sandbox=sandbox)
    flash("Acción masiva aprobada. Ya puede ejecutarse.", "success")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/reject", methods=["POST"])
def mass_action_reject(action_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from datetime import datetime, timezone

    action = hr.get_mass_action(owner_uid, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.mass_action_wizard"))

    if action.get("status") != "pending_approval":
        flash("Solo se pueden rechazar acciones en estado pendiente de aprobación.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Debes proporcionar un motivo para el rechazo.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    now_iso = datetime.now(timezone.utc).isoformat()
    action["status"] = "rejected"
    action["rejectedBy"] = session.get("user", {}).get("email", "")
    action["rejectedAt"] = now_iso
    action["rejectionReason"] = reason
    history = action.get("statusHistory", [])
    history.append({"from": "pending_approval", "to": "rejected", "by": session.get("user", {}).get("email", ""),
                     "at": now_iso, "comment": reason})
    action["statusHistory"] = history
    hr.save_mass_action(owner_uid, action_id, action, sandbox=sandbox)
    flash("Acción masiva rechazada.", "success")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/pending")
def mass_action_pending_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    all_actions = hr.get_mass_actions(owner_uid, sandbox=sandbox)
    pending = [a for a in all_actions if a.get("status") == "pending_approval"]
    recent = sorted(all_actions, key=lambda a: a.get("createdAt", ""), reverse=True)[:20]

    return render_template("rrhh/mass_action_pending.html", active_page="rrhh_employees",
                           pending=pending, recent=recent)
