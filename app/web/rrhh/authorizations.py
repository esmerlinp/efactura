"""RRHH module — Cola genérica de autorizaciones y configuración de reglas."""

import uuid
from flask import render_template, request, redirect, url_for, session, flash

from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr
from app.services.hr_authorization_service import (
    AUTHORIZATION_DOC_TYPES,
    REQUEST_STATUS_LABELS,
    get_authorization_request,
    get_authorization_requests,
    decide_authorization,
    return_for_correction,
    resubmit_authorization,
    reassign_authorization,
    _user_has_pending_step,
)


def _current_user() -> dict:
    return session.get("user", {})


def _can_manage_rules() -> bool:
    user = session.get("user", {})
    if user.get("role") == "owner":
        return True
    if user.get("uid") == session.get("selected_owner_uid"):
        return True
    perms = user.get("permissions", {}) or {}
    return bool(perms.get("canAssignApprovers", False))


def _resolve_entity_link(request: dict) -> str:
    entity_type = request.get("entityType", "")
    doc_id = request.get("documentId", "")
    if entity_type == "mass_action":
        return url_for("web_rrhh.mass_action_detail", action_id=doc_id)
    if entity_type == "payroll":
        return url_for("web_rrhh.payroll_view", period_id=doc_id)
    return request.get("link", "")


# ═══════════════════════════════════════════════════════════════════════════
# COLA DE AUTORIZACIONES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/authorizations")
def authorization_queue():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user = _current_user()
    user_uid = user.get("uid", "")
    is_owner = user.get("role") == "owner" or user_uid == session.get("selected_owner_uid")

    all_requests = get_authorization_requests(company_id, sandbox=sandbox)
    for req in all_requests:
        req["_pendingForMe"] = _user_has_pending_step(req, user_uid)
        req["_entityLink"] = _resolve_entity_link(req)

    pending_mine = sum(1 for r in all_requests if r.get("_pendingForMe"))

    all_requests.sort(key=lambda r: (
        0 if r.get("_pendingForMe") else 1,
        0 if r.get("status") == "pending" else 1,
        -(len(r.get("createdAt") or "")),
    ))

    return render_template(
        "rrhh/authorizations.html",
        active_page="rrhh_authorizations",
        requests=all_requests,
        pending_mine=pending_mine,
        status_labels=REQUEST_STATUS_LABELS,
        can_manage_rules=_can_manage_rules(),
        is_owner=is_owner,
        current_user_uid=user_uid,
    )


@web_rrhh_bp.route("/rrhh/authorizations/<request_id>")
def authorization_detail(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_uid = _current_user().get("uid", "")

    request_data = get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request_data:
        flash("Solicitud de autorización no encontrada.", "error")
        return redirect(url_for("web_rrhh.authorization_queue"))

    can_decide = (
        request_data.get("status") == "pending"
        and _user_has_pending_step(request_data, user_uid)
    )
    can_resubmit = (
        request_data.get("status") == "returned"
        and (request_data.get("createdByUid") == user_uid
             or request_data.get("createdByEmail") == _current_user().get("email", ""))
    )
    is_creator = user_uid and (request_data.get("createdByUid") == user_uid
                               or request_data.get("createdByEmail") == _current_user().get("email", ""))
    user_email = _current_user().get("email", "")
    is_pending_approver = _user_has_pending_step(request_data, user_uid) or _user_has_pending_step(request_data, user_email)

    mass_action = None
    selected_employees = []
    if request_data.get("entityType") == "mass_action":
        try:
            mass_action = hr.get_mass_action(company_id, request_data["documentId"], sandbox=sandbox)
            if mass_action:
                emp_ids = (mass_action.get("selectionCriteria") or {}).get("employeeIds", [])
                if emp_ids:
                    all_emps = hr.get_employees(company_id, sandbox=sandbox)
                    emp_map = {e.get("id"): e for e in all_emps}
                    atype = mass_action.get("actionType", "")
                    payload = mass_action.get("payload") or {}
                    for eid in emp_ids:
                        emp = emp_map.get(eid)
                        if emp:
                            cur_sal = emp.get("baseSalary") or 0
                            cur_pos = emp.get("position", "")
                            cur_dept = emp.get("department") or emp.get("area", "")
                            cur_sup = emp.get("reportsTo", "")
                            psed = {}
                            if atype in ("salary_change", "promotion"):
                                if payload.get("changeType") == "percentage":
                                    pct = float(payload.get("percentage", 0) or 0)
                                    ns = round(cur_sal * (1 + pct / 100), 2)
                                else:
                                    ns = float(payload.get("amount", 0) or 0)
                                if ns and ns != cur_sal:
                                    psed["salary"] = ns
                            if atype in ("position_change", "promotion"):
                                if payload.get("newPosition") and payload["newPosition"] != cur_pos:
                                    psed["position"] = payload["newPosition"]
                                nd = payload.get("newDepartment") or payload.get("newArea")
                                if nd and nd != cur_dept:
                                    psed["department"] = nd
                            if atype == "supervisor_change":
                                sid = payload.get("newSupervisorId", "")
                                if sid and sid != cur_sup:
                                    se = emp_map.get(sid, {})
                                    sn = se.get("fullName") or (se.get("firstName","") + " " + se.get("lastName","")).strip()
                                    psed["reportsTo"] = sn or sid
                            selected_employees.append({
                                "id": eid,
                                "fullName": emp.get("fullName") or emp.get("firstName","") + " " + (emp.get("lastName","") or ""),
                                "baseSalary": cur_sal, "position": cur_pos,
                                "department": cur_dept, "reportsTo": cur_sup,
                                "status": emp.get("status"), "proposed": psed,
                            })
        except Exception as e:
            print(f"⚠️ Error cargando empleados para autorización: {e}")

    comments = []
    taggable_users = []
    format_mentions = lambda content, users: content
    try:
        from app.services.db_service import DatabaseService
        from app.web.invoices import _get_taggable_users, format_mentions
        comments = DatabaseService.get_resource_comments(owner_uid, "authorizations", request_id,
                                                        company_id=company_id, sandbox=sandbox)
        taggable_users = _get_taggable_users(owner_uid, company_id)
    except Exception as e:
        print(f"⚠️ Error al cargar comentarios de autorización: {e}")

    return render_template(
        "rrhh/authorization_detail.html",
        active_page="rrhh_authorizations",
        request_data=request_data,
        status_labels=REQUEST_STATUS_LABELS,
        can_decide=can_decide,
        can_resubmit=can_resubmit,
        is_creator=is_creator,
        is_pending_approver=is_pending_approver,
        mass_action=mass_action,
        current_user_uid=user_uid,
        entity_link=_resolve_entity_link(request_data),
        comments=comments,
        taggable_users=taggable_users,
        format_mentions=format_mentions,
        selected_employees=selected_employees,
    )


# ═══════════════════════════════════════════════════════════════════════════
# COMENTARIOS DE SOLICITUDES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/authorizations/<request_id>/comments/new", methods=["POST"])
def authorization_comment_new(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    content = request.form.get("content", "").strip()
    if not content:
        flash("El comentario no puede estar vacío.", "error")
        return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))

    attachment_url = ""
    attachment_name = ""
    file = request.files.get("attachment")
    if file and file.filename:
        try:
            from app.services.db_service import DatabaseService
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_auth_{request_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {e}", "warning")

    from app.services.db_service import DatabaseService
    from datetime import datetime, timezone
    comment_id = str(uuid.uuid4())
    comment_dict = {
        "content": content,
        "createdBy": _current_user().get("email", ""),
        "createdByName": _current_user().get("name", ""),
        "createdByUid": _current_user().get("uid", ""),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "attachmentUrl": attachment_url,
        "attachmentName": attachment_name,
        "edited": False,
    }
    DatabaseService.save_resource_comment(owner_uid, "authorizations", request_id, comment_id,
                                          comment_dict, company_id=company_id, sandbox=sandbox)

    try:
        req = get_authorization_request(company_id, request_id, sandbox=sandbox) or {}
        label = req.get("docTypeLabel", "") or req.get("docType", "") or "Solicitud"
        from app.web.invoices import process_resource_comment_mentions
        process_resource_comment_mentions(owner_uid, content, "authorizations", request_id, label, sandbox)
    except Exception as e:
        print(f"⚠️ Error al procesar menciones en authorization_comment_new: {e}")

    flash("Comentario agregado exitosamente.", "success")
    return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))


@web_rrhh_bp.route("/rrhh/authorizations/<request_id>/comments/<comment_id>/edit", methods=["POST"])
def authorization_comment_edit(request_id, comment_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    from app.services.db_service import DatabaseService
    from datetime import datetime, timezone
    comments = DatabaseService.get_resource_comments(owner_uid, "authorizations", request_id,
                                                     company_id=company_id, sandbox=sandbox)
    comment = next((c for c in comments if c["id"] == comment_id), None)
    if not comment:
        flash("Comentario no encontrado.", "error")
        return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))

    is_owner = _current_user().get("role") == "owner"
    is_author = _current_user().get("uid") == comment.get("createdByUid")
    if not (is_owner or is_author):
        flash("No tienes permiso para editar este comentario.", "error")
        return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))

    content = request.form.get("content", "").strip()
    if not content:
        flash("El comentario no puede estar vacío.", "error")
        return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))

    comment["content"] = content
    comment["edited"] = True
    comment["editedAt"] = datetime.now(timezone.utc).isoformat()

    file = request.files.get("attachment")
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_auth_{request_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            comment["attachmentUrl"] = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            comment["attachmentName"] = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {e}", "warning")

    DatabaseService.save_resource_comment(owner_uid, "authorizations", request_id, comment_id, comment,
                                          company_id=company_id, sandbox=sandbox)

    try:
        req = get_authorization_request(company_id, request_id, sandbox=sandbox) or {}
        label = req.get("docTypeLabel", "") or req.get("docType", "") or "Solicitud"
        from app.web.invoices import process_resource_comment_mentions
        process_resource_comment_mentions(owner_uid, content, "authorizations", request_id, label, sandbox)
    except Exception as e:
        print(f"⚠️ Error al procesar menciones en authorization_comment_edit: {e}")

    flash("Comentario modificado.", "success")
    return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))


@web_rrhh_bp.route("/rrhh/authorizations/<request_id>/comments/<comment_id>/delete", methods=["POST"])
def authorization_comment_delete(request_id, comment_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    from app.services.db_service import DatabaseService
    comments = DatabaseService.get_resource_comments(owner_uid, "authorizations", request_id,
                                                     company_id=company_id, sandbox=sandbox)
    comment = next((c for c in comments if c["id"] == comment_id), None)
    if comment:
        is_owner = _current_user().get("role") == "owner"
        is_author = _current_user().get("uid") == comment.get("createdByUid")
        if not (is_owner or is_author):
            flash("No tienes permiso para eliminar este comentario.", "error")
            return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))
    DatabaseService.delete_resource_comment(owner_uid, "authorizations", request_id, comment_id,
                                            company_id=company_id, sandbox=sandbox)
    flash("Comentario eliminado.", "success")
    return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))


@web_rrhh_bp.route("/rrhh/authorizations/<request_id>/decide", methods=["POST"])
def authorization_decide(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user = _current_user()
    user_uid = user.get("uid", "")
    user_email = user.get("email", "")

    decision = request.form.get("decision", "")
    comment = request.form.get("comment", "").strip()
    return_assignee_id = request.form.get("returnAssigneeId", "").strip()

    request_data = get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request_data:
        flash("Solicitud de autorización no encontrada.", "error")
        return redirect(url_for("web_rrhh.authorization_queue"))

    try:
        if decision == "approve":
            result = decide_authorization(company_id, request_id, user_uid or user_email,
                                          approved=True, comment=comment,
                                          approver_name=user.get("name", ""), sandbox=sandbox,
                                          approver_email=user_email if user_uid else "")
        elif decision == "reject":
            result = decide_authorization(company_id, request_id, user_uid or user_email,
                                          approved=False, comment=comment,
                                          approver_name=user.get("name", ""), sandbox=sandbox,
                                          approver_email=user_email if user_uid else "")
        elif decision == "return":
            result = return_for_correction(company_id, request_id, user_uid or user_email,
                                           comment, approver_name=user.get("name", ""),
                                           sandbox=sandbox)
        else:
            raise ValueError("Decisión inválida.")

        if not result.get("success"):
            raise ValueError(result.get("error", "No se pudo registrar la decisión."))
        status = result.get("status", "")

        if decision == "return" and return_assignee_id:
            reassign_authorization(company_id, request_id, return_assignee_id,
                                   reassigned_by=user.get("name") or user_email, sandbox=sandbox)

        flash(f"Solicitud {REQUEST_STATUS_LABELS.get(status, status).lower()}.",
              "success" if status in ("approved",) else "warning")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("web_rrhh.authorization_queue"))


@web_rrhh_bp.route("/rrhh/authorizations/<request_id>/resubmit", methods=["POST"])
def authorization_resubmit(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user = _current_user()

    request_data = get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request_data:
        flash("Solicitud de autorización no encontrada.", "error")
        return redirect(url_for("web_rrhh.authorization_queue"))

    try:
        entity_type = request_data.get("entityType", "")
        entity_id = request_data.get("documentId", "")
        if entity_type == "mass_action":
            from app.services.mass_action_service import resubmit_mass_action
            resubmit_mass_action(company_id, entity_id, user.get("email", ""), sandbox=sandbox)
        else:
            result = resubmit_authorization(company_id, request_id,
                                            resubmitted_by=user.get("email", ""), sandbox=sandbox)
            if not result.get("success"):
                raise ValueError(result.get("error", "No se pudo reenviar la solicitud."))
        flash("Solicitud reenviada a aprobación.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))


@web_rrhh_bp.route("/rrhh/authorizations/<request_id>/reassign", methods=["POST"])
def authorization_reassign(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user = _current_user()

    new_assignee_id = request.form.get("newAssigneeId", "").strip()
    if not new_assignee_id:
        flash("Debe seleccionar una persona para reasignar.", "error")
        return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))

    try:
        result = reassign_authorization(company_id, request_id, new_assignee_id,
                                        reassigned_by=user.get("name") or user.get("email", ""), sandbox=sandbox)
        if not result.get("success"):
            raise ValueError(result.get("error", "No se pudo reasignar la solicitud."))
        flash("Solicitud reasignada.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("web_rrhh.authorization_detail", request_id=request_id))


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE REGLAS (solo owner o canAssignApprovers)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/authorizations/rules", methods=["GET"])
def authorization_rules_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _can_manage_rules():
        flash("No tienes permisos para configurar autorizaciones.", "error")
        return redirect(url_for("web_rrhh.authorization_queue"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    rules = hr.get_authorization_rules(company_id, sandbox=sandbox)
    rules.sort(key=lambda r: (r.get("docType", ""), r.get("createdAt", "")))
    for r in rules:
        r["_approver_ids"] = [a.get("id", "") for a in r.get("approvers", []) if a.get("id")]

    from app.services.db_service import DatabaseService
    team = DatabaseService.get_team_members(owner_uid, company_id=company_id)

    return render_template(
        "rrhh/authorization_rules.html",
        active_page="rrhh_authorizations",
        rules=rules,
        doc_types=AUTHORIZATION_DOC_TYPES,
        team=team,
    )


@web_rrhh_bp.route("/rrhh/authorizations/rules/save", methods=["POST"])
def authorization_rule_save():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _can_manage_rules():
        return {"error": "No autorizado"}, 403
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    doc_type = request.form.get("docType", "")
    rule_id = request.form.get("ruleId", "") or str(uuid.uuid4())
    min_approvals = request.form.get("minApprovals", "1")
    approver_ids = request.form.getlist("approverIds")
    is_active = request.form.get("isActive", "1") == "1"
    default_assignee_id = request.form.get("defaultAssigneeId", "")

    if doc_type not in AUTHORIZATION_DOC_TYPES:
        flash("Tipo de documento inválido.", "error")
        return redirect(url_for("web_rrhh.authorization_rules_list"))
    if not approver_ids:
        flash("Debe seleccionar al menos un aprobador.", "error")
        return redirect(url_for("web_rrhh.authorization_rules_list"))

    try:
        min_approvals = max(1, int(min_approvals))
    except (TypeError, ValueError):
        min_approvals = 1
    if min_approvals > len(approver_ids):
        min_approvals = len(approver_ids)

    from app.services.db_service import DatabaseService
    team = DatabaseService.get_team_members(owner_uid, company_id=company_id)
    team_map = {m.get("uid"): m for m in team}
    approvers = [
        {"id": uid, "name": team_map[uid].get("name", ""), "email": team_map[uid].get("email", "")}
        for uid in approver_ids if uid in team_map
    ]

    default_assignee = None
    if default_assignee_id and default_assignee_id in approver_ids:
        m = team_map.get(default_assignee_id, {})
        default_assignee = {"id": default_assignee_id, "name": m.get("name", ""), "email": m.get("email", "")}

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    existing = hr.get_authorization_rule(company_id, rule_id, sandbox=sandbox)

    rule = {
        "id": rule_id,
        "docType": doc_type,
        "minApprovals": min_approvals,
        "approvers": approvers,
        "defaultAssignee": default_assignee,
        "isActive": is_active,
        "createdAt": (existing or {}).get("createdAt", now),
        "updatedAt": now,
    }
    hr.save_authorization_rule(company_id, rule_id, rule, sandbox=sandbox)
    flash("Regla de autorización guardada.", "success")
    return redirect(url_for("web_rrhh.authorization_rules_list"))


@web_rrhh_bp.route("/rrhh/authorizations/rules/<rule_id>/delete", methods=["POST"])
def authorization_rule_delete(rule_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _can_manage_rules():
        flash("No tienes permisos para configurar autorizaciones.", "error")
        return redirect(url_for("web_rrhh.authorization_queue"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    hr.delete_authorization_rule(company_id, rule_id, sandbox=sandbox)
    flash("Regla de autorización eliminada.", "success")
    return redirect(url_for("web_rrhh.authorization_rules_list"))
