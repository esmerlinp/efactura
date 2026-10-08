"""Blueprint web del módulo CRM."""

from flask import Blueprint, jsonify, redirect, render_template, request, session, flash, url_for, g

from app.models.crm import CRM_ACTIVITY_PRIORITIES, CRM_ACTIVITY_TYPES, CRM_OPPORTUNITY_STAGES, CRM_STAGE_PROBABILITY
from app.services.audit_service import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, MODULE_CRM, AuditService
from app.services.contact_service import ContactService
from app.services.crm_service import CRMService
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission
from app.utils.module_gate import module_enabled, require_module


web_crm_bp = Blueprint("web_crm", __name__)


@web_crm_bp.before_request
def _check_crm_module():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not module_enabled("crm"):
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "error": {
                    "code": "MODULE_DISABLED",
                    "message": "El módulo 'CRM' no está contratado en tu plan actual."
                }
            }), 403
        return render_template(
            "auth/restricted.html",
            feature_name="CRM & Agenda",
            required_permission="module_crm",
            custom_message="El módulo <strong>CRM & Agenda</strong> no está incluido en tu plan actual. "
                           "Contacta a soporte para información sobre mejoras de plan."
        ), 403


def _sandbox():
    return session.get("is_sandbox_mode", True)


def _current_user_label():
    user = session.get("user", {})
    return user.get("name") or user.get("email") or "Usuario"


def _get_active_company_context():
    user = session.get("user")
    if not user or not user.get("uid"):
        return None
    selected_cid = session.get("selected_company_id")
    if not selected_cid:
        return None
    return DatabaseService.get_company_context(user["uid"], selected_cid)


def _check(feature="CRM", required_permission="canCRM"):
    if "user" not in session:
        return redirect(url_for("web_auth.login")), None
    if not module_enabled("crm"):
        return (render_template("auth/restricted.html", feature_name=feature, required_permission="module_crm", custom_message=f"El módulo <strong>{feature}</strong> no está incluido en tu plan actual."), 403), None
    if not check_permission(required_permission):
        return (render_template("auth/restricted.html", feature_name=feature, required_permission=required_permission), 403), None
    ctx = _get_active_company_context()
    if not ctx:
        flash("Debe seleccionar una empresa activa para acceder al CRM.", "warning")
        return redirect(url_for("web_auth.select_company")), None
    return None, ctx


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _crm_context(owner_uid, sandbox=True, company_id=None, branch_id=None, project_id=None):
    contacts = [c for c in ContactService.get_contacts(owner_uid, sandbox=sandbox, company_id=company_id) if "cliente" in c.get("types", [])]
    if branch_id:
        contacts = [c for c in contacts if c.get("branchId") == branch_id]
    if project_id == '__no_project__':
        contacts = [c for c in contacts if not c.get("projectId")]
    elif project_id:
        contacts = [c for c in contacts if c.get("projectId") == project_id]

    collaborators = DatabaseService.get_team_members(owner_uid, company_id=company_id) or []
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id) or []
    projects = DatabaseService.get_projects(owner_uid, sandbox=sandbox, company_id=company_id) or []
    opportunities = CRMService.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, include_closed=False, branch_id=branch_id, project_id=project_id)
    quotations = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=True, company_id=company_id, branch_id=branch_id, project_id=project_id)
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False, company_id=company_id, branch_id=branch_id, project_id=project_id)
    real_invoices = [inv for inv in invoices if not inv.get("isQuotation") and inv.get("status") not in ("Anulada", "Borrador")]
    return {
        "contacts": contacts,
        "collaborators": collaborators,
        "branches": branches,
        "projects": projects,
        "selected_branch": branch_id or "",
        "selected_project": project_id or "",
        "opportunities": opportunities,
        "quotations": quotations,
        "invoices": real_invoices,
        "stages": CRM_OPPORTUNITY_STAGES,
        "stage_probabilities": CRM_STAGE_PROBABILITY,
        "activity_types": CRM_ACTIVITY_TYPES,
        "activity_priorities": CRM_ACTIVITY_PRIORITIES,
    }


def _opportunity_from_form(company_id=""):
    stage = request.form.get("stage", "Prospecto")
    probability_raw = request.form.get("probability", "")
    probability = _safe_int(probability_raw, CRM_STAGE_PROBABILITY.get(stage, 10))
    return {
        "companyId": company_id,
        "contactId": request.form.get("contactId", "").strip(),
        "title": request.form.get("title", "").strip(),
        "stage": stage,
        "amount": _safe_float(request.form.get("amount")),
        "probability": probability,
        "expectedCloseDate": request.form.get("expectedCloseDate", "").strip(),
        "source": request.form.get("source", "Manual").strip() or "Manual",
        "assignedTo": request.form.get("assignedTo", "").strip(),
        "quotationId": request.form.get("quotationId", "").strip(),
        "invoiceId": request.form.get("invoiceId", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "createdBy": session.get("user", {}).get("email", ""),
        "branchId": request.form.get("branchId") or g.get("branch_id", "default-sucursal-principal"),
        "projectId": request.form.get("projectId") or g.get("project_id"),
    }


def _activity_from_form(company_id=""):
    return {
        "companyId": company_id,
        "contactId": request.form.get("contactId", "").strip(),
        "opportunityId": request.form.get("opportunityId", "").strip(),
        "type": request.form.get("type", "Tarea").strip(),
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "dueDate": request.form.get("dueDate", "").strip(),
        "priority": request.form.get("priority", "media").strip(),
        "assignedTo": request.form.get("assignedTo", "").strip(),
        "status": request.form.get("status", "pendiente").strip(),
        "createdBy": session.get("user", {}).get("email", ""),
        "branchId": request.form.get("branchId") or g.get("branch_id", "default-sucursal-principal"),
        "projectId": request.form.get("projectId") or g.get("project_id"),
    }


@web_crm_bp.route("/crm")
def dashboard():
    r, ctx = _check("Dashboard CRM", required_permission="canCRMReports")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    branch_id = request.args.get("branch_id") or g.get("branch_id")
    project_id = request.args.get("project_id") or g.get("project_id")
    date_range = request.args.get("date_range") or "all"
    data = CRMService.get_dashboard(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id, date_range=date_range)
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id) or []
    projects = DatabaseService.get_projects(owner_uid, sandbox=sandbox, company_id=company_id) or []
    return render_template(
        "crm/dashboard.html",
        active_page="crm_dashboard",
        crm=data,
        branches=branches,
        projects=projects,
        selected_branch=branch_id or "",
        selected_project=project_id or "",
        selected_date_range=date_range or "all",
    )


@web_crm_bp.route("/crm/pipeline")
def pipeline():
    r, ctx = _check("Pipeline CRM", required_permission="canCRMOpportunities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    branch_id = request.args.get("branch_id") or g.get("branch_id")
    project_id = request.args.get("project_id") or g.get("project_id")
    context = _crm_context(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
    context["pipeline"] = CRMService.get_pipeline(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
    return render_template("crm/pipeline.html", active_page="crm_pipeline", **context)


@web_crm_bp.route("/crm/opportunities/new", methods=["GET", "POST"])
def opportunity_new():
    r, ctx = _check("Nueva Oportunidad", required_permission="canCRMOpportunities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    branch_id, project_id = g.get("branch_id"), g.get("project_id")

    if request.method == "POST":
        opportunity = _opportunity_from_form(company_id=company_id)
        if not opportunity["contactId"]:
            flash("Debe seleccionar un contacto.", "error")
        else:
            saved = CRMService.save_opportunity(owner_uid, "", opportunity, sandbox=sandbox, company_id=company_id)
            AuditService.log_from_request(
                owner_uid=owner_uid,
                action=ACTION_CREATE,
                module=MODULE_CRM,
                entity_id=saved["id"],
                entity_label=f"Oportunidad CRM creada: {saved.get('title', '')}",
                user_session=session.get("user", {}),
                after=saved,
                sandbox=sandbox,
            )
            followup_date = request.form.get("nextActivityDate", "").strip()
            if followup_date:
                CRMService.save_activity(owner_uid, "", {
                    "companyId": company_id,
                    "contactId": saved.get("contactId", ""),
                    "opportunityId": saved["id"],
                    "type": "Seguimiento",
                    "title": request.form.get("nextActivityTitle", "").strip() or f"Seguimiento: {saved.get('title', '')}",
                    "description": f"Actividad generada desde la oportunidad {saved.get('title', '')}.",
                    "dueDate": followup_date,
                    "priority": "media",
                    "createdBy": session.get("user", {}).get("email", ""),
                    "branchId": g.get("branch_id", "default-sucursal-principal"),
                    "projectId": g.get("project_id"),
                }, sandbox=sandbox, company_id=company_id)
            flash("Oportunidad creada correctamente.", "success")
            return redirect(url_for("web_crm.pipeline"))

    context = _crm_context(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
    context["opportunity"] = None
    context["selected_contact_id"] = request.args.get("contact_id", "")
    return render_template("crm/opportunity_form.html", active_page="crm_pipeline", **context)


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/edit", methods=["GET", "POST"])
def opportunity_edit(opportunity_id):
    r, ctx = _check("Editar Oportunidad", required_permission="canCRMOpportunities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    branch_id, project_id = g.get("branch_id"), g.get("project_id")
    opportunity = CRMService.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
    if not opportunity:
        flash("Oportunidad no encontrada.", "error")
        return redirect(url_for("web_crm.pipeline"))

    if request.method == "POST":
        before = opportunity.copy()
        updates = _opportunity_from_form(company_id=company_id)
        saved = CRMService.save_opportunity(owner_uid, opportunity_id, updates, sandbox=sandbox, company_id=company_id)
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_CRM,
            entity_id=opportunity_id,
            entity_label=f"Oportunidad CRM actualizada: {saved.get('title', '')}",
            user_session=session.get("user", {}),
            before=before,
            after=saved,
            sandbox=sandbox,
        )
        flash("Oportunidad actualizada.", "success")
        return redirect(url_for("web_crm.pipeline"))

    context = _crm_context(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
    context["opportunity"] = opportunity
    context["selected_contact_id"] = opportunity.get("contactId", "")
    return render_template("crm/opportunity_form.html", active_page="crm_pipeline", **context)


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/stage", methods=["POST"])
def opportunity_stage(opportunity_id):
    r, ctx = _check("Actualizar Pipeline", required_permission="canCRMOpportunities")
    if r:
        if request.is_json:
            return jsonify({"success": False, "error": "No autorizado"}), 403
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()

    data = request.json or request.form
    target_stage = data.get("stage", "Prospecto")
    lost_reason = data.get("lostReason", "")
    notes = data.get("notes", "")

    existing = CRMService.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
    current_stage = (existing or {}).get("stage", "")

    ok, msg, saved = CRMService.transition_opportunity(
        owner_uid=owner_uid,
        opportunity_id=opportunity_id,
        target_stage=target_stage,
        sandbox=sandbox,
        company_id=company_id,
        user_name=_current_user_label(),
        lost_reason=lost_reason,
        notes=notes,
    )
    if not ok:
        return jsonify({"success": False, "error": msg}), 400

    # Auditoría de transición (CRM-17)
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_UPDATE,
        module=MODULE_CRM,
        entity_id=opportunity_id,
        entity_label=f"Oportunidad '{saved.get('title', '')}' transicionada: {current_stage} ➔ {target_stage}",
        user_session=session.get("user", {}),
        before=existing,
        after=saved,
        sandbox=sandbox,
    )
    return jsonify({"success": True, "message": msg, "opportunity": saved})


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/close", methods=["POST"])
def opportunity_close(opportunity_id):
    r, ctx = _check("Cerrar Oportunidad", required_permission="canCRMOpportunities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    outcome = request.form.get("outcome", "ganada")
    target_stage = "Ganada" if outcome == "ganada" else "Perdida"
    existing = CRMService.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
    current_stage = (existing or {}).get("stage", "")
    lost_reason = request.form.get("lostReason", "")

    ok, msg, saved = CRMService.transition_opportunity(
        owner_uid=owner_uid,
        opportunity_id=opportunity_id,
        target_stage=target_stage,
        lost_reason=lost_reason,
        invoice_id=request.form.get("invoiceId", ""),
        sandbox=sandbox,
        company_id=company_id,
        user_name=_current_user_label(),
        notes=request.form.get("notes", ""),
    )
    if ok and saved:
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_CRM,
            entity_id=opportunity_id,
            entity_label=f"Oportunidad '{saved.get('title', '')}' cerrada como {target_stage}",
            user_session=session.get("user", {}),
            before=existing,
            after=saved,
            sandbox=sandbox,
        )
    flash(msg, "success" if ok else "error")
    return redirect(url_for("web_crm.pipeline"))


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/quick-note", methods=["POST"])
def opportunity_quick_note(opportunity_id):
    """Registra una nota rápida o interacción comercial en la oportunidad (CRM-19)."""
    r, ctx = _check("Nota Rápida CRM", required_permission="canCRMOpportunities")
    if r:
        if request.is_json:
            return jsonify({"success": False, "error": "No autorizado"}), 403
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    data = request.json or request.form
    note_content = (data.get("content") or data.get("note") or "").strip()
    if not note_content:
        return jsonify({"success": False, "error": "El contenido de la nota es requerido."}), 400

    opp = CRMService.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
    if not opp:
        return jsonify({"success": False, "error": "Oportunidad no encontrada."}), 404

    author = _current_user_label()
    now_stamp = _now_iso()[:10]
    updated_notes = f"{opp.get('notes', '')}\n[{now_stamp} - {author}]: {note_content}".strip()
    opp["notes"] = updated_notes
    saved = CRMService.save_opportunity(owner_uid, opportunity_id, opp, sandbox=sandbox, company_id=company_id)

    # Registrar en bitácora de interacciones del cliente si está asociado
    if opp.get("contactId"):
        try:
            DatabaseService.save_client_interaction(owner_uid, opp["contactId"], str(uuid.uuid4()), {
                "type": "Nota",
                "title": f"Nota en oportunidad: {opp.get('title')}",
                "content": note_content,
                "date": _now_iso(),
                "completed": True,
                "createdBy": author,
            }, sandbox=sandbox, company_id=company_id)
        except Exception:
            pass

    return jsonify({"success": True, "message": "Nota agregada correctamente.", "opportunity": saved})


@web_crm_bp.route("/crm/contacts/<contact_id>/quick-note", methods=["POST"])
def contact_quick_note(contact_id):
    """Registra una interacción rápida en la ficha del contacto (CRM-19)."""
    r, ctx = _check("Nota Rápida Contacto", required_permission="canCRMContacts")
    if r:
        if request.is_json:
            return jsonify({"success": False, "error": "No autorizado"}), 403
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    data = request.json or request.form
    note_type = data.get("type", "Nota")
    note_title = (data.get("title") or f"Interacción rápida ({note_type})").strip()
    note_content = (data.get("content") or data.get("note") or "").strip()

    if not note_content:
        return jsonify({"success": False, "error": "El contenido de la interacción es requerido."}), 400

    interaction_id = str(uuid.uuid4())
    interaction_data = {
        "id": interaction_id,
        "type": note_type,
        "title": note_title,
        "content": note_content,
        "date": _now_iso(),
        "completed": True,
        "createdBy": _current_user_label(),
    }
    try:
        DatabaseService.save_client_interaction(owner_uid, contact_id, interaction_id, interaction_data, sandbox=sandbox, company_id=company_id)
        return jsonify({"success": True, "message": "Interacción registrada.", "interaction": interaction_data})
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al registrar nota: {e}"}), 500


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/delete", methods=["POST"])
def opportunity_delete(opportunity_id):
    r, ctx = _check("Eliminar Oportunidad", required_permission="canCRMOpportunities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    opportunity = CRMService.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
    CRMService.delete_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id, deleted_by=_current_user_label())
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_DELETE,
        module=MODULE_CRM,
        entity_id=opportunity_id,
        entity_label=f"Oportunidad CRM eliminada: {(opportunity or {}).get('title', '')}",
        user_session=session.get("user", {}),
        before=opportunity,
        sandbox=sandbox,
    )
    flash("Oportunidad eliminada.", "success")
    return redirect(url_for("web_crm.pipeline"))


@web_crm_bp.route("/crm/activities")
def activities():
    r, ctx = _check("Agenda CRM", required_permission="canCRMActivities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    branch_id, project_id = g.get("branch_id"), g.get("project_id")
    status = request.args.get("status", "pendientes")
    include_completed = status in ("todas", "completadas")
    activity_list = CRMService.get_activities(owner_uid, sandbox=sandbox, include_completed=include_completed, branch_id=branch_id, project_id=project_id, company_id=company_id)
    if status == "vencidas":
        activity_list = [a for a in activity_list if a.get("isOverdue")]
    elif status == "hoy":
        activity_list = [a for a in activity_list if a.get("isDueToday")]
    elif status == "completadas":
        activity_list = [a for a in activity_list if a.get("status") == "completada"]
    elif status == "pendientes":
        activity_list = [a for a in activity_list if a.get("status") == "pendiente"]

    return render_template(
        "crm/activities.html",
        active_page="crm_activities",
        activities=activity_list,
        status=status,
    )


@web_crm_bp.route("/crm/activities/new", methods=["GET", "POST"])
def activity_new():
    r, ctx = _check("Nueva Actividad", required_permission="canCRMActivities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    branch_id, project_id = g.get("branch_id"), g.get("project_id")

    if request.method == "POST":
        activity = _activity_from_form(company_id=company_id)
        if not activity["title"]:
            activity["title"] = activity["type"]
        saved = CRMService.save_activity(owner_uid, "", activity, sandbox=sandbox, company_id=company_id)
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_CRM,
            entity_id=saved["id"],
            entity_label=f"Actividad CRM creada: {saved.get('title', '')}",
            user_session=session.get("user", {}),
            after=saved,
            sandbox=sandbox,
        )
        flash("Actividad creada correctamente.", "success")
        return redirect(url_for("web_crm.activities"))

    context = _crm_context(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
    context["activity"] = None
    context["selected_contact_id"] = request.args.get("contact_id", "")
    context["selected_opportunity_id"] = request.args.get("opportunity_id", "")
    return render_template("crm/activity_form.html", active_page="crm_activities", **context)


@web_crm_bp.route("/crm/activities/<activity_id>/edit", methods=["GET", "POST"])
def activity_edit(activity_id):
    r, ctx = _check("Editar Actividad", required_permission="canCRMActivities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    branch_id, project_id = g.get("branch_id"), g.get("project_id")
    activity = CRMService.get_activity(owner_uid, activity_id, sandbox=sandbox, company_id=company_id)
    if not activity:
        flash("Actividad no encontrada.", "error")
        return redirect(url_for("web_crm.activities"))

    if request.method == "POST":
        before = activity.copy()
        saved = CRMService.save_activity(owner_uid, activity_id, _activity_from_form(company_id=company_id), sandbox=sandbox, company_id=company_id)
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_CRM,
            entity_id=activity_id,
            entity_label=f"Actividad CRM actualizada: {saved.get('title', '')}",
            user_session=session.get("user", {}),
            before=before,
            after=saved,
            sandbox=sandbox,
        )
        flash("Actividad actualizada.", "success")
        return redirect(url_for("web_crm.activities"))

    context = _crm_context(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
    context["activity"] = activity
    context["selected_contact_id"] = activity.get("contactId", "")
    context["selected_opportunity_id"] = activity.get("opportunityId", "")
    return render_template("crm/activity_form.html", active_page="crm_activities", **context)


@web_crm_bp.route("/crm/activities/<activity_id>/complete", methods=["POST"])
def activity_complete(activity_id):
    r, ctx = _check("Completar Actividad", required_permission="canCRMActivities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    ok, msg = CRMService.complete_activity(owner_uid, activity_id, sandbox=sandbox, company_id=company_id)
    flash(msg, "success" if ok else "error")
    return redirect(request.referrer or url_for("web_crm.activities"))


@web_crm_bp.route("/crm/activities/<activity_id>/delete", methods=["POST"])
def activity_delete(activity_id):
    r, ctx = _check("Eliminar Actividad", required_permission="canCRMActivities")
    if r:
        return r
    owner_uid, company_id, sandbox = ctx["owner_uid"], ctx["company_id"], _sandbox()
    activity = CRMService.get_activity(owner_uid, activity_id, sandbox=sandbox, company_id=company_id)
    CRMService.delete_activity(owner_uid, activity_id, sandbox=sandbox, company_id=company_id, deleted_by=_current_user_label())
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_DELETE,
        module=MODULE_CRM,
        entity_id=activity_id,
        entity_label=f"Actividad CRM eliminada: {(activity or {}).get('title', '')}",
        user_session=session.get("user", {}),
        before=activity,
        sandbox=sandbox,
    )
    flash("Actividad eliminada.", "success")
    return redirect(request.referrer or url_for("web_crm.activities"))
