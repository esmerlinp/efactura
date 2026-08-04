"""RRHH module — auto-extracted."""

import uuid
from datetime import date, datetime, timezone

from flask import render_template, request, redirect, url_for, session, flash, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required, _is_hr_role,
    _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.state_machine import MASS_ACTION_STATES


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
    """Wizard de acción masiva: renderiza la página que embebe la modal."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    ids_param = request.args.get("ids", "")
    employee_ids = [i for i in ids_param.split(",") if i] if ids_param else []

    employees_data = []
    if employee_ids:
        from app.services.payroll_service import PayrollService
        for eid in employee_ids:
            emp = hr.get_employee(company_id, eid, sandbox=sandbox)
            if emp:
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

    all_employees = hr.get_employees(company_id, sandbox=sandbox)
    supervisors = [e for e in all_employees
                   if e.get("status") == "activo" and e.get("id") not in employee_ids]
    positions = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    departments = hr.get_catalog(company_id, "departments", sandbox=sandbox)
    config = hr.get_payroll_config(company_id, sandbox=sandbox)
    frequency = config.get("payrollFrequency") or config.get("payroll", {}).get("frequency", "mensual")

    try:
        now = date.today()
        payroll_periods = _generate_periods(frequency, now.year)
        if now.month < 12:
            payroll_periods += _generate_periods(frequency, now.year + 1)
    except Exception:
        payroll_periods = []

    action_type = request.args.get("action_type", "")

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
    )


@web_rrhh_bp.route("/rrhh/employees/mass-action/preview", methods=["POST"])
def mass_action_preview():
    """Paso 4: previsualización (AJAX)."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    action_type = data.get("actionType", "")
    employee_ids = data.get("employeeIds", [])
    payload = data.get("payload", {})

    from app.services.mass_action_service import validate_action
    errors = validate_action(owner_uid, action_type, employee_ids, payload, sandbox=sandbox, company_id=company_id)

    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    employees = []
    for eid in employee_ids:
        emp = hr.get_employee(company_id, eid, sandbox=sandbox)
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
    """Paso 5: ejecutar la acción masiva (o enviar a aprobación)."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    action_type = data.get("actionType", "")
    employee_ids = data.get("employeeIds", [])
    payload = data.get("payload", {})
    submit_for_approval = bool(data.get("submitForApproval", False))
    existing_action_id = data.get("actionId") or None

    if not action_type or not employee_ids:
        return {"error": "Faltan datos requeridos."}, 400

    reason = (payload.get("reason") or "").strip()
    if submit_for_approval and not reason:
        return {"error": "Debes proporcionar una justificación para enviar la acción a aprobación."}, 400

    from app.services.mass_action_service import (
        create_mass_action, execute_action, submit_mass_action, validate_action, update_mass_action,
    )

    if existing_action_id:
        action = hr.get_mass_action(company_id, existing_action_id, sandbox=sandbox)
        if not action or action.get("status") != "draft":
            return {"error": "La acción no existe o no está en borrador."}, 400
        action = update_mass_action(company_id, existing_action_id, action_type, employee_ids, payload,
                                    user_email, sandbox=sandbox)

        if submit_for_approval:
            action = submit_mass_action(company_id, existing_action_id, user_email, sandbox=sandbox,
                                        created_by_uid=session.get("user", {}).get("uid", ""),
                                        created_by_name=session.get("user", {}).get("name", ""))
            return {"actionId": action["id"], "status": action["status"], "totalEmployees": action["totalEmployees"]}

        result = execute_action(owner_uid, existing_action_id, user_email, sandbox=sandbox, company_id=company_id)
        return {"actionId": result["id"], "status": result["status"], "successCount": result["successCount"],
                "errorCount": result["errorCount"], "totalEmployees": result["totalEmployees"]}

    validation_errors = validate_action(owner_uid, action_type, employee_ids, payload, sandbox=sandbox, company_id=company_id)
    if validation_errors:
        return {"error": "Validación fallida.", "errors": validation_errors}, 400

    action = create_mass_action(owner_uid, action_type, employee_ids, payload, user_email, sandbox=sandbox, company_id=company_id)

    if submit_for_approval:
        action = submit_mass_action(company_id, action["id"], user_email, sandbox=sandbox,
                                    created_by_uid=session.get("user", {}).get("uid", ""),
                                    created_by_name=session.get("user", {}).get("name", ""))
        return {
            "actionId": action["id"],
            "status": action["status"],
            "totalEmployees": action["totalEmployees"],
        }

    result = execute_action(owner_uid, action["id"], user_email, sandbox=sandbox, company_id=company_id)

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
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    action = hr.get_mass_action(company_id, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    auth_id = action.get("authorizationRequestId")
    if auth_id and action.get("status") != "draft":
        return redirect(url_for("web_rrhh.authorization_detail", request_id=auth_id))

    selected_employees = []
    employee_ids = (action.get("selectionCriteria") or {}).get("employeeIds", [])
    if employee_ids:
        all_emps = hr.get_employees(company_id, sandbox=sandbox)
        emp_map = {e.get("id"): e for e in all_emps}
        atype = action.get("actionType", "")
        payload = action.get("payload") or {}

        for eid in employee_ids:
            emp = emp_map.get(eid)
            if emp:
                cur_salary = emp.get("baseSalary") or 0
                cur_position = emp.get("position", "")
                cur_dept = emp.get("department") or emp.get("area", "")
                cur_sup = emp.get("reportsTo", "")

                propsed = {}

                if atype in ("salary_change", "promotion"):
                    if payload.get("changeType") == "percentage":
                        pct = float(payload.get("percentage", 0) or 0)
                        new_sal = round(cur_salary * (1 + pct / 100), 2)
                    else:
                        new_sal = float(payload.get("amount", 0) or 0)
                    if new_sal and new_sal != cur_salary:
                        propsed["salary"] = new_sal

                if atype in ("position_change", "promotion"):
                    if payload.get("newPosition") and payload["newPosition"] != cur_position:
                        propsed["position"] = payload["newPosition"]
                    if payload.get("newDepartment") and payload["newDepartment"] != cur_dept:
                        propsed["department"] = payload["newDepartment"]
                    elif payload.get("newArea") and payload["newArea"] != cur_dept:
                        propsed["department"] = payload["newArea"]

                if atype == "supervisor_change":
                    new_sup_id = payload.get("newSupervisorId", "")
                    if new_sup_id and new_sup_id != cur_sup:
                        sup_emp = emp_map.get(new_sup_id, {})
                        sup_name = sup_emp.get("fullName") or sup_emp.get("firstName", "") + " " + sup_emp.get("lastName", "")
                        propsed["reportsTo"] = sup_name.strip() or new_sup_id

                selected_employees.append({
                    "id": eid,
                    "fullName": emp.get("fullName") or emp.get("firstName", "") + " " + (emp.get("lastName", "")),
                    "baseSalary": cur_salary,
                    "position": cur_position,
                    "department": cur_dept,
                    "reportsTo": cur_sup,
                    "status": emp.get("status"),
                    "proposed": propsed,
                })

    assigned_to = {}
    auth_req = None
    auth_id = action.get("authorizationRequestId")
    if auth_id:
        try:
            from app.services.hr_authorization_service import get_authorization_request
            auth_req = get_authorization_request(company_id, auth_id, sandbox=sandbox)
            if auth_req:
                assigned_to = auth_req.get("assignedTo") or {}
        except Exception:
            pass

    comments = []
    taggable_users = []
    format_mentions = lambda content, users: content
    try:
        from app.services.db_service import DatabaseService
        from app.web.invoices import format_mentions, _get_taggable_users
        comments = DatabaseService.get_resource_comments(owner_uid, "mass_actions", action_id,
                                                         company_id=company_id, sandbox=sandbox)
        taggable_users = _get_taggable_users(owner_uid, company_id)
    except Exception:
        pass

    return render_template(
        "rrhh/mass_action_detail.html",
        active_page="rrhh_mass_actions",
        action=action,
        action_type_label=MASS_ACTION_TYPES.get(action.get("actionType", ""), {}).get("label", action.get("actionType", "")),
        selected_employees=selected_employees,
        assigned_to=assigned_to,
        auth_req=auth_req,
        comments=comments,
        taggable_users=taggable_users,
        format_mentions=format_mentions,
    )


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/comments/new", methods=["POST"])
def mass_action_comment_new(action_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    content = request.form.get("content", "").strip()
    if not content:
        flash("El comentario no puede estar vacío.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))
    attachment_url, attachment_name = "", ""
    file = request.files.get("attachment")
    if file and file.filename:
        try:
            from app.services.db_service import DatabaseService
            file_data = file.read()
            fname = f"comment_ma_{action_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, f"users/{owner_uid}/comments/{fname}", file.mimetype or "application/octet-stream")
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo: {e}", "warning")
    from app.services.db_service import DatabaseService
    cid = str(uuid.uuid4())
    user = session.get("user", {})
    DatabaseService.save_resource_comment(owner_uid, "mass_actions", action_id, cid, {
        "content": content, "createdBy": user.get("email",""), "createdByName": user.get("name",""),
        "createdByUid": user.get("uid",""), "createdAt": datetime.now(timezone.utc).isoformat(),
        "attachmentUrl": attachment_url, "attachmentName": attachment_name, "edited": False,
    }, company_id=company_id, sandbox=sandbox)
    try:
        action = hr.get_mass_action(company_id, action_id, sandbox=sandbox) or {}
        label = MASS_ACTION_TYPES.get(action.get("actionType",""),{}).get("label","Acción Masiva")
        from app.web.invoices import process_resource_comment_mentions
        process_resource_comment_mentions(owner_uid, content, "mass_actions", action_id, label, sandbox)
    except Exception as e:
        print(f"⚠️ mention mass_action: {e}")
    flash("Comentario agregado.", "success")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/comments/<comment_id>/edit", methods=["POST"])
def mass_action_comment_edit(action_id, comment_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.db_service import DatabaseService
    comments = DatabaseService.get_resource_comments(owner_uid, "mass_actions", action_id,
                                                     company_id=company_id, sandbox=sandbox)
    comment = next((c for c in comments if c["id"] == comment_id), None)
    if not comment:
        flash("Comentario no encontrado.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))
    user = session.get("user", {})
    if user.get("role") != "owner" and user.get("uid") != comment.get("createdByUid"):
        flash("No tienes permiso para editar este comentario.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))
    content = request.form.get("content", "").strip()
    if not content:
        flash("El comentario no puede estar vacío.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))
    comment["content"] = content
    comment["edited"] = True
    comment["editedAt"] = datetime.now(timezone.utc).isoformat()
    DatabaseService.save_resource_comment(owner_uid, "mass_actions", action_id, comment_id,
                                          comment, company_id=company_id, sandbox=sandbox)
    flash("Comentario modificado.", "success")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/comments/<comment_id>/delete", methods=["POST"])
def mass_action_comment_delete(action_id, comment_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.db_service import DatabaseService
    comments = DatabaseService.get_resource_comments(owner_uid, "mass_actions", action_id,
                                                     company_id=company_id, sandbox=sandbox)
    comment = next((c for c in comments if c["id"] == comment_id), None)
    if comment:
        user = session.get("user", {})
        if user.get("role") != "owner" and user.get("uid") != comment.get("createdByUid"):
            flash("No tienes permiso para eliminar este comentario.", "error")
            return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))
    DatabaseService.delete_resource_comment(owner_uid, "mass_actions", action_id, comment_id,
                                            company_id=company_id, sandbox=sandbox)
    flash("Comentario eliminado.", "success")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/cancel-submit", methods=["POST"])
def mass_action_cancel_submit(action_id):
    """Cancela el envío a aprobación y vuelve a borrador."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    action = hr.get_mass_action(company_id, action_id, sandbox=sandbox)
    if not action:
        flash("Acción no encontrada.", "error")
        return redirect(url_for("web_rrhh.mass_action_pending_list"))
    if action.get("status") != "pending_approval":
        flash("Solo se puede cancelar acciones pendientes de aprobación.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    auth_id = action.get("authorizationRequestId")
    if auth_id:
        try:
            from app.services.hr_authorization_service import cancel_authorization
            cancel_authorization(company_id, auth_id, cancelled_by=user_email, sandbox=sandbox)
        except Exception as e:
            flash(f"Error al cancelar la autorización: {e}", "error")
            return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    flash("Envío cancelado. Puedes editar la acción y reenviarla.", "success")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/edit-from-pending", methods=["POST"])
def mass_action_edit_from_pending(action_id):
    """Cancela la solicitud y abre el wizard de edición."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    action = hr.get_mass_action(company_id, action_id, sandbox=sandbox)
    if not action:
        flash("Acción no encontrada.", "error")
        return redirect(url_for("web_rrhh.mass_action_pending_list"))
    if action.get("status") != "pending_approval":
        flash("Solo se pueden editar acciones pendientes de aprobación.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    auth_id = action.get("authorizationRequestId")
    if auth_id:
        try:
            from app.services.hr_authorization_service import cancel_authorization
            cancel_authorization(company_id, auth_id, cancelled_by=user_email, sandbox=sandbox)
        except Exception as e:
            flash(f"Error al cancelar la autorización: {e}", "error")
            return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    return redirect(url_for("web_rrhh.mass_action_edit", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/back-to-draft", methods=["POST"])
def mass_action_back_to_draft(action_id):
    """Devuelve una acción devuelta a borrador para poder editarla."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    action = hr.get_mass_action(company_id, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.mass_action_pending_list"))
    if action.get("status") != "returned":
        flash("Solo se pueden volver a borrador las acciones devueltas.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    action["status"] = "draft"
    action["authorizationStatus"] = ""
    action.pop("returnedBy", None)
    action.pop("returnedAt", None)
    action.pop("returnComment", None)
    action.setdefault("statusHistory", []).append({
        "from": "returned", "to": "draft", "by": user_email, "at": now,
        "comment": "Devuelta a borrador para edición",
    })
    hr.save_mass_action(company_id, action_id, action, sandbox=sandbox)
    flash("Acción devuelta a borrador. Puedes editarla y reenviarla.", "success")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/edit", methods=["GET"])
def mass_action_edit(action_id):
    """Muestra el wizard de edición con los datos de una acción existente."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    action = hr.get_mass_action(company_id, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.mass_action_pending_list"))
    if action.get("status") != "draft":
        flash("Solo se pueden editar acciones en borrador.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    employee_ids = (action.get("selectionCriteria") or {}).get("employeeIds", [])
    employees = [e for e in hr.get_employees(company_id, sandbox=sandbox) if e.get("id") in employee_ids]

    return render_template(
        "rrhh/mass_action_wizard.html",
        active_page="rrhh_mass_actions",
        employees=employees,
        action_types=MASS_ACTION_TYPES,
        positions=hr.get_catalog(company_id, "positions", sandbox=sandbox),
        supervisors=[e for e in employees if e.get("status") != "inactivo"],
        payroll_periods=[],
        action_type=action.get("actionType", ""),
        edit_action=action,
    )


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/errors.csv", methods=["GET"])
def mass_action_errors_csv(action_id):
    """Exportar los errores de una acción masiva a CSV."""
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    action = hr.get_mass_action(company_id, action_id, sandbox=sandbox)
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
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.mass_action_service import submit_mass_action

    try:
        submit_mass_action(company_id, action_id, session.get("user", {}).get("email", ""),
                           sandbox=sandbox,
                           created_by_uid=session.get("user", {}).get("uid", ""),
                           created_by_name=session.get("user", {}).get("name", ""))
        flash("Acción masiva enviada a aprobación.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/<action_id>/execute", methods=["POST"])
def mass_action_approved_execute(action_id):
    """Ejecutar una acción masiva aprobada."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _is_hr_role():
        flash("No tienes permisos para ejecutar acciones masivas.", "error")
        return redirect(url_for("web_rrhh.mass_action_pending_list"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.mass_action_service import execute_action

    action = hr.get_mass_action(company_id, action_id, sandbox=sandbox)
    if not action:
        flash("Acción masiva no encontrada.", "error")
        return redirect(url_for("web_rrhh.mass_action_wizard"))

    if action.get("status") != "approved":
        flash("Solo se pueden ejecutar acciones aprobadas.", "error")
        return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))

    try:
        result = execute_action(owner_uid, action_id, session.get("user", {}).get("email", ""), sandbox=sandbox, company_id=company_id)
        status = result.get("status", "completed")
        flash(f"Acción masiva {status} con {result.get('errorCount', 0)} error(es).", "success")
    except Exception as e:
        flash(f"Error al ejecutar la acción: {e}", "error")
    return redirect(url_for("web_rrhh.mass_action_detail", action_id=action_id))


@web_rrhh_bp.route("/rrhh/mass-actions/pending")
def mass_action_pending_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user = session.get("user", {})
    user_email = user.get("email", "")
    is_owner = user.get("role") == "owner" or user.get("uid") == session.get("selected_owner_uid")

    all_actions = hr.get_mass_actions(company_id, sandbox=sandbox)
    if not is_owner:
        all_actions = [a for a in all_actions if a.get("createdBy") == user_email]

    all_actions.sort(key=lambda a: (
        0 if a.get("status") in ("pending_approval", "returned") else 1,
        0 if a.get("status") == "draft" else 1,
        -(len(a.get("createdAt") or "")),
    ))

    return render_template("rrhh/mass_action_pending.html",
                           active_page="rrhh_mass_actions",
                           actions=all_actions,
                           states=MASS_ACTION_STATES,
                           type_labels={k: {"label": v.get("label", k), "icon": v.get("icon", "fa-solid fa-file-lines")}
                                        for k, v in MASS_ACTION_TYPES.items()})
