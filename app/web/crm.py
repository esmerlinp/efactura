"""Blueprint web del módulo CRM."""

from flask import Blueprint, jsonify, redirect, render_template, request, session, flash, url_for, g

from app.models.crm import CRM_ACTIVITY_PRIORITIES, CRM_ACTIVITY_TYPES, CRM_OPPORTUNITY_STAGES, CRM_STAGE_PROBABILITY
from app.services.audit_service import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, MODULE_CRM, AuditService
from app.services.contact_service import ContactService
from app.services.crm_service import CRMService
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission


web_crm_bp = Blueprint("web_crm", __name__)


def _owner():
    return session["user"]["ownerUID"]


def _sandbox():
    return session.get("is_sandbox_mode", True)


def _current_user_label():
    user = session.get("user", {})
    return user.get("name") or user.get("email") or "Usuario"


def _check(feature="CRM"):
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not check_permission("canClients"):
        return render_template("auth/restricted.html", feature_name=feature, required_permission="canClients")
    return None


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


def _crm_context(owner_uid, sandbox=True):
    contacts = [c for c in ContactService.get_contacts(owner_uid, sandbox=sandbox) if "cliente" in c.get("types", [])]
    collaborators = DatabaseService.get_team_members(owner_uid) or []
    opportunities = CRMService.get_opportunities(owner_uid, sandbox=sandbox, include_closed=False)
    quotations = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=True)
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
    real_invoices = [inv for inv in invoices if not inv.get("isQuotation") and inv.get("status") not in ("Anulada", "Borrador")]
    return {
        "contacts": contacts,
        "collaborators": collaborators,
        "opportunities": opportunities,
        "quotations": quotations,
        "invoices": real_invoices,
        "stages": CRM_OPPORTUNITY_STAGES,
        "stage_probabilities": CRM_STAGE_PROBABILITY,
        "activity_types": CRM_ACTIVITY_TYPES,
        "activity_priorities": CRM_ACTIVITY_PRIORITIES,
    }


def _opportunity_from_form():
    stage = request.form.get("stage", "Prospecto")
    probability_raw = request.form.get("probability", "")
    probability = _safe_int(probability_raw, CRM_STAGE_PROBABILITY.get(stage, 10))
    return {
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
        "branchId": g.get("branch_id", "default-sucursal-principal"),
        "projectId": g.get("project_id"),
    }


def _activity_from_form():
    return {
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
        "branchId": g.get("branch_id", "default-sucursal-principal"),
        "projectId": g.get("project_id"),
    }


@web_crm_bp.route("/crm")
def dashboard():
    r = _check("Dashboard CRM")
    if r:
        return r
    data = CRMService.get_dashboard(_owner(), sandbox=_sandbox())
    return render_template("crm/dashboard.html", active_page="crm_dashboard", crm=data)


@web_crm_bp.route("/crm/pipeline")
def pipeline():
    r = _check("Pipeline CRM")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()
    context = _crm_context(owner_uid, sandbox=sandbox)
    context["pipeline"] = CRMService.get_pipeline(owner_uid, sandbox=sandbox)
    return render_template("crm/pipeline.html", active_page="crm_pipeline", **context)


@web_crm_bp.route("/crm/opportunities/new", methods=["GET", "POST"])
def opportunity_new():
    r = _check("Nueva Oportunidad")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()

    if request.method == "POST":
        opportunity = _opportunity_from_form()
        if not opportunity["contactId"]:
            flash("Debe seleccionar un contacto.", "error")
        else:
            saved = CRMService.save_opportunity(owner_uid, "", opportunity, sandbox=sandbox)
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
                }, sandbox=sandbox)
            flash("Oportunidad creada correctamente.", "success")
            return redirect(url_for("web_crm.pipeline"))

    context = _crm_context(owner_uid, sandbox=sandbox)
    context["opportunity"] = None
    context["selected_contact_id"] = request.args.get("contact_id", "")
    return render_template("crm/opportunity_form.html", active_page="crm_pipeline", **context)


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/edit", methods=["GET", "POST"])
def opportunity_edit(opportunity_id):
    r = _check("Editar Oportunidad")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()
    opportunity = CRMService.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox)
    if not opportunity:
        flash("Oportunidad no encontrada.", "error")
        return redirect(url_for("web_crm.pipeline"))

    if request.method == "POST":
        before = opportunity.copy()
        updates = _opportunity_from_form()
        saved = CRMService.save_opportunity(owner_uid, opportunity_id, updates, sandbox=sandbox)
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

    context = _crm_context(owner_uid, sandbox=sandbox)
    context["opportunity"] = opportunity
    context["selected_contact_id"] = opportunity.get("contactId", "")
    return render_template("crm/opportunity_form.html", active_page="crm_pipeline", **context)


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/stage", methods=["POST"])
def opportunity_stage(opportunity_id):
    r = _check("Actualizar Pipeline")
    if r:
        if request.is_json:
            return jsonify({"success": False, "error": "No autorizado"}), 403
        return r
    owner_uid, sandbox = _owner(), _sandbox()
    opportunity = CRMService.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox)
    if not opportunity:
        return jsonify({"success": False, "error": "Oportunidad no encontrada"}), 404

    data = request.json or request.form
    stage = data.get("stage", opportunity.get("stage", "Prospecto"))
    probability = data.get("probability", CRM_STAGE_PROBABILITY.get(stage, opportunity.get("probability", 10)))
    saved = CRMService.save_opportunity(owner_uid, opportunity_id, {**opportunity, "stage": stage, "probability": probability}, sandbox=sandbox)
    return jsonify({"success": True, "opportunity": saved})


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/close", methods=["POST"])
def opportunity_close(opportunity_id):
    r = _check("Cerrar Oportunidad")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()
    outcome = request.form.get("outcome", "ganada")
    ok, msg = CRMService.close_opportunity(
        owner_uid,
        opportunity_id,
        outcome=outcome,
        lost_reason=request.form.get("lostReason", ""),
        invoice_id=request.form.get("invoiceId", ""),
        sandbox=sandbox,
    )
    flash(msg, "success" if ok else "error")
    return redirect(url_for("web_crm.pipeline"))


@web_crm_bp.route("/crm/opportunities/<opportunity_id>/delete", methods=["POST"])
def opportunity_delete(opportunity_id):
    r = _check("Eliminar Oportunidad")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()
    opportunity = CRMService.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox)
    CRMService.delete_opportunity(owner_uid, opportunity_id, sandbox=sandbox)
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
    r = _check("Agenda CRM")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()
    status = request.args.get("status", "pendientes")
    include_completed = status == "todas"
    activity_list = CRMService.get_activities(owner_uid, sandbox=sandbox, include_completed=include_completed)
    if status == "vencidas":
        activity_list = [a for a in activity_list if a.get("isOverdue")]
    elif status == "hoy":
        activity_list = [a for a in activity_list if a.get("isDueToday")]
    elif status == "completadas":
        activity_list = [a for a in CRMService.get_activities(owner_uid, sandbox=sandbox, include_completed=True) if a.get("status") == "completada"]
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
    r = _check("Nueva Actividad")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()

    if request.method == "POST":
        activity = _activity_from_form()
        if not activity["title"]:
            activity["title"] = activity["type"]
        saved = CRMService.save_activity(owner_uid, "", activity, sandbox=sandbox)
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

    context = _crm_context(owner_uid, sandbox=sandbox)
    context["activity"] = None
    context["selected_contact_id"] = request.args.get("contact_id", "")
    context["selected_opportunity_id"] = request.args.get("opportunity_id", "")
    return render_template("crm/activity_form.html", active_page="crm_activities", **context)


@web_crm_bp.route("/crm/activities/<activity_id>/edit", methods=["GET", "POST"])
def activity_edit(activity_id):
    r = _check("Editar Actividad")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()
    activity = CRMService.get_activity(owner_uid, activity_id, sandbox=sandbox)
    if not activity:
        flash("Actividad no encontrada.", "error")
        return redirect(url_for("web_crm.activities"))

    if request.method == "POST":
        before = activity.copy()
        saved = CRMService.save_activity(owner_uid, activity_id, _activity_from_form(), sandbox=sandbox)
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

    context = _crm_context(owner_uid, sandbox=sandbox)
    context["activity"] = activity
    context["selected_contact_id"] = activity.get("contactId", "")
    context["selected_opportunity_id"] = activity.get("opportunityId", "")
    return render_template("crm/activity_form.html", active_page="crm_activities", **context)


@web_crm_bp.route("/crm/activities/<activity_id>/complete", methods=["POST"])
def activity_complete(activity_id):
    r = _check("Completar Actividad")
    if r:
        return r
    ok, msg = CRMService.complete_activity(_owner(), activity_id, sandbox=_sandbox())
    flash(msg, "success" if ok else "error")
    return redirect(request.referrer or url_for("web_crm.activities"))


@web_crm_bp.route("/crm/activities/<activity_id>/delete", methods=["POST"])
def activity_delete(activity_id):
    r = _check("Eliminar Actividad")
    if r:
        return r
    owner_uid, sandbox = _owner(), _sandbox()
    activity = CRMService.get_activity(owner_uid, activity_id, sandbox=sandbox)
    CRMService.delete_activity(owner_uid, activity_id, sandbox=sandbox)
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
