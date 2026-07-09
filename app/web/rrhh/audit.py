"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_audit_service import get_audit_log


# ═══════════════════════════════════════════════════════════════════════════
# AUDITORÍA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/audit-log")
def audit_log():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_audit_service import get_audit_log
    entity = request.args.get("entity", "")
    limit = min(int(request.args.get("limit", 100) or 100), 500)
    logs = get_audit_log(owner_uid, entity=entity or None, limit=limit, sandbox=sandbox)
    return render_template("rrhh/audit_log.html", active_page="rrhh_settings",
                           logs=logs, entity=entity, limit=limit)


