"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


def _safe_next(request):
    """Retorna la URL de retorno (next) si es una ruta local válida."""
    nxt = request.args.get("next", "") or request.form.get("next", "")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# CONCEPTOS DE NÓMINA (configurables)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/concepts")
def concept_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.payroll_concept_engine import get_concepts
    concepts = get_concepts(company_id, sandbox=sandbox)
    return render_template("rrhh/concepts/list.html", active_page="rrhh_settings",
                           concepts=concepts, next_url=_safe_next(request))


@web_rrhh_bp.route("/rrhh/concepts/new", methods=["GET", "POST"])
def concept_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.payroll_concept_engine import save_concept
    preset_type = request.args.get("type", "")
    preset_category = request.args.get("category", "")
    if request.method == "POST":
        save_concept(company_id, {
            "code": request.form.get("code", "").strip().upper(),
            "name": request.form.get("name", "").strip(),
            "type": request.form.get("type", "earning"),
            "category": request.form.get("category", "variable"),
            "taxable": request.form.get("taxable") == "on",
            "affects_afp": request.form.get("affects_afp") == "on",
            "affects_sfs": request.form.get("affects_sfs") == "on",
            "affects_isr": request.form.get("affects_isr") == "on",
            "account_debit": request.form.get("account_debit", ""),
            "account_credit": request.form.get("account_credit", ""),
            "priority": int(request.form.get("priority", 99) or 99),
            "active": True,
            "isManualEntry": request.form.get("is_manual_entry") == "on",
        }, sandbox=sandbox)
        flash("Concepto creado exitosamente.", "success")
        if _safe_next(request):
            return redirect(_safe_next(request))
        return redirect(url_for("web_rrhh.concept_list"))
    return render_template("rrhh/concepts/form.html", active_page="rrhh_settings", concept=None,
                           preset_type=preset_type, preset_category=preset_category,
                           next_url=_safe_next(request))


@web_rrhh_bp.route("/rrhh/concepts/<concept_code>/edit", methods=["GET", "POST"])
def concept_edit(concept_code):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.payroll_concept_engine import get_concept, save_concept
    concept = get_concept(company_id, concept_code, sandbox=sandbox)
    if not concept:
        flash("Concepto no encontrado.", "error")
        return redirect(url_for("web_rrhh.concept_list"))
    if request.method == "POST":
        concept.update({
            "name": request.form.get("name", "").strip(),
            "type": request.form.get("type", concept.get("type")),
            "category": request.form.get("category", concept.get("category")),
            "taxable": request.form.get("taxable") == "on",
            "affects_afp": request.form.get("affects_afp") == "on",
            "affects_sfs": request.form.get("affects_sfs") == "on",
            "affects_isr": request.form.get("affects_isr") == "on",
            "account_debit": request.form.get("account_debit", ""),
            "account_credit": request.form.get("account_credit", ""),
            "priority": int(request.form.get("priority", 99) or 99),
            "isManualEntry": request.form.get("is_manual_entry") == "on",
        })
        save_concept(company_id, concept, sandbox=sandbox)
        flash("Concepto actualizado.", "success")
        if _safe_next(request):
            return redirect(_safe_next(request))
        return redirect(url_for("web_rrhh.concept_list"))
    return render_template("rrhh/concepts/form.html", active_page="rrhh_settings", concept=concept,
                           preset_type="", preset_category="", next_url=_safe_next(request))


@web_rrhh_bp.route("/rrhh/concepts/<concept_code>/toggle", methods=["POST"])
def concept_toggle(concept_code):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.payroll_concept_engine import get_concept, save_concept
    concept = get_concept(company_id, concept_code, sandbox=sandbox)
    if concept:
        concept["active"] = not concept.get("active", True)
        save_concept(company_id, concept, sandbox=sandbox)
        flash(f"Concepto {'activado' if concept['active'] else 'desactivado'}.", "success")
    if _safe_next(request):
        return redirect(_safe_next(request))
    return redirect(url_for("web_rrhh.concept_list"))
