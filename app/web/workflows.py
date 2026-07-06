from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services.approval_service import ApprovalService, APPROVAL_DOCUMENT_TYPES
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission


web_workflows_bp = Blueprint("web_workflows", __name__)


def _require_user():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    return None


def _team_options(owner_uid):
    options = []
    owner = DatabaseService.get_user_profile(owner_uid)
    if owner:
        options.append({
            "uid": owner_uid,
            "name": owner.get("name") or "Propietario",
            "email": owner.get("email", ""),
        })
    for member in DatabaseService.get_team_members(owner_uid) or []:
        options.append({
            "uid": member.get("uid", ""),
            "name": member.get("name", ""),
            "email": member.get("email", ""),
        })
    return [o for o in options if o.get("uid")]


@web_workflows_bp.route("/workflows")
def dashboard():
    guard = _require_user()
    if guard:
        return guard
    if not (check_permission("canExpenses") or check_permission("canModifySettings")):
        return render_template("auth/restricted.html", feature_name="Workflows y aprobaciones")

    owner_uid = session["user"]["ownerUID"]
    status = request.args.get("status", "")
    current_uid = session["user"].get("uid", "")
    rules = ApprovalService.get_rules(owner_uid)
    requests = ApprovalService.get_requests(owner_uid, status=status)
    my_pending = ApprovalService.get_pending_approvals(owner_uid, current_uid)
    return render_template(
        "workflows/dashboard.html",
        active_page="workflows",
        rules=rules,
        requests=requests,
        my_pending=my_pending,
        status=status,
        document_types=APPROVAL_DOCUMENT_TYPES,
        team_options=_team_options(owner_uid),
    )


@web_workflows_bp.route("/workflows/rules/save", methods=["POST"])
def save_rule():
    guard = _require_user()
    if guard:
        return guard
    if not check_permission("canModifySettings"):
        return render_template("auth/restricted.html", feature_name="Reglas de aprobación", required_permission="canModifySettings")

    owner_uid = session["user"]["ownerUID"]
    rule_id = request.form.get("id", "")
    existing = ApprovalService.get_rule(owner_uid, rule_id) if rule_id else {}
    data = {
        "id": rule_id,
        "document_type": request.form.get("document_type", "expense"),
        "min_amount": request.form.get("min_amount", 0),
        "approvers": request.form.getlist("approvers"),
        "require_all": request.form.get("require_all") == "on",
        "is_active": request.form.get("is_active") == "on",
        "notes": request.form.get("notes", "").strip(),
        "createdAt": (existing or {}).get("createdAt"),
    }
    if not data["approvers"]:
        flash("Debes seleccionar al menos un aprobador.", "error")
        return redirect(url_for("web_workflows.dashboard"))
    ApprovalService.save_rule(owner_uid, data)
    flash("Regla de aprobación guardada.", "success")
    return redirect(url_for("web_workflows.dashboard"))


@web_workflows_bp.route("/workflows/rules/<rule_id>/delete", methods=["POST"])
def delete_rule(rule_id):
    guard = _require_user()
    if guard:
        return guard
    if not check_permission("canModifySettings"):
        return render_template("auth/restricted.html", feature_name="Reglas de aprobación", required_permission="canModifySettings")
    ApprovalService.delete_rule(session["user"]["ownerUID"], rule_id)
    flash("Regla eliminada.", "success")
    return redirect(url_for("web_workflows.dashboard"))


@web_workflows_bp.route("/workflows/requests/<request_id>/decide", methods=["POST"])
def decide_request(request_id):
    guard = _require_user()
    if guard:
        return guard
    owner_uid = session["user"]["ownerUID"]
    approved = request.form.get("decision") == "approve"
    result = ApprovalService.decide_approval(
        owner_uid=owner_uid,
        request_id=request_id,
        approver_id=session["user"].get("uid", ""),
        approved=approved,
        comment=request.form.get("comment", "").strip(),
        approver_name=session["user"].get("name") or session["user"].get("email", ""),
    )
    if result.get("success"):
        flash("Decisión registrada.", "success")
    else:
        flash(result.get("error", "No se pudo registrar la decisión."), "error")
    return redirect(url_for("web_workflows.dashboard"))

