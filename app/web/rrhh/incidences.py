"""RRHH module — Vista de incidencias de datos de empleados."""

from flask import render_template, request, redirect, url_for, session

from app.web.rrhh import web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required
from app.services.employee_incidences_service import (
    get_incidences, SEVERITY_LABELS, BLOQUEANTE, REQUERIDO, ADVERTENCIA,
)


@web_rrhh_bp.route("/rrhh/incidencias")
def incidences():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    result = get_incidences(company_id, sandbox=sandbox)
    items = result["items"]
    summary = result["summary"]

    # ── Filtros ──
    filter_process = request.args.get("process", "").strip()
    filter_severity = request.args.get("severity", "").strip()

    processes = sorted({i["process"] for it in items for i in it["incidences"]})

    def _matches(it):
        if filter_process and not any(i["process"] == filter_process for i in it["incidences"]):
            return False
        if filter_severity and not any(i["severity"] == filter_severity for i in it["incidences"]):
            return False
        return True

    filtered = [it for it in items if _matches(it)]
    filtered_total = len(filtered)

    # ── Paginación ──
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(10, min(100000, int(request.args.get("per_page", 50))))
    except (ValueError, TypeError):
        page, per_page = 1, 50
    if filtered_total == 0:
        page, per_page = 1, 50
    elif per_page >= filtered_total:
        per_page = filtered_total
        page = 1
    total_pages = max(1, (filtered_total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    paged = filtered[start:start + per_page]

    return render_template(
        "rrhh/incidencias.html",
        active_page="rrhh_incidences",
        items=paged,
        summary=summary,
        processes=processes,
        severity_labels=SEVERITY_LABELS,
        filter_process=filter_process,
        filter_severity=filter_severity,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        filtered_total=filtered_total,
        severity_blocking=BLOQUEANTE,
        severity_required=REQUERIDO,
        severity_advertencia=ADVERTENCIA,
    )
