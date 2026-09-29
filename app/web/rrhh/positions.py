"""RRHH — Catálogo de Posiciones."""

import uuid

from flask import render_template, request, redirect, url_for, session, flash
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr

# Días de la semana para el editor de horario: (código, índice 0=Lun..6=Dom)
_SCHEDULE_DAYS = [
    ("L", 0), ("M", 1), ("X", 2), ("J", 3), ("V", 4), ("S", 5), ("D", 6),
]


def _reports_to_is_valid(positions: list, item_id: str, reports_to: str) -> bool:
    """Evita auto-referencia y ciclos en la jerarquía de posiciones."""
    if not reports_to or reports_to == item_id:
        return False if reports_to == item_id else True
    by_id = {p.get("id"): p for p in positions}
    seen = {item_id}
    cursor = reports_to
    while cursor:
        if cursor in seen:
            return False
        seen.add(cursor)
        parent = by_id.get(cursor)
        cursor = (parent or {}).get("reportsTo", "") if parent else ""
    return True


@web_rrhh_bp.route("/rrhh/positions")
def position_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    items = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    for item in items:
        schedule_map = {}
        for entry in (item.get("workSchedule") or []):
            try:
                schedule_map[int(entry.get("day", -1))] = entry
            except (ValueError, TypeError):
                continue
        item["_schedule_map"] = schedule_map
    return render_template("rrhh/positions_list.html", active_page="rrhh_positions",
                           items=items, title="Posiciones", days=_SCHEDULE_DAYS)


@web_rrhh_bp.route("/rrhh/positions/save", methods=["POST"])
def position_save():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    item_id = request.form.get("id", str(uuid.uuid4()))
    name = request.form.get("name", "").strip()
    if name:
        from app.utils.hr_utils import parse_work_schedule_form
        positions = hr.get_catalog(company_id, "positions", sandbox=sandbox)
        existing = next((p for p in positions if p.get("id") == item_id), None)
        # Preservar jerarquía si el formulario no trae el campo (edición inline de nombre/horario).
        if "reportsTo" in request.form:
            reports_to = request.form.get("reportsTo", "").strip()
        else:
            reports_to = existing.get("reportsTo", "") if existing else ""
        if request.form.get("schedule_submitted") == "1":
            work_schedule = parse_work_schedule_form(request.form)
        else:
            # Edición inline solo de nombre → preservar horario existente
            work_schedule = existing.get("workSchedule", []) if existing else []
        if not _reports_to_is_valid(positions, item_id, reports_to):
            flash("La jerarquía seleccionada crea un ciclo o se refiere a sí misma.", "error")
            return redirect(url_for("web_rrhh.position_list"))
        hr.save_catalog_item(company_id, "positions", {
            "id": item_id, "name": name, "active": True,
            "workSchedule": work_schedule,
            "reportsTo": reports_to,
        }, sandbox=sandbox)
        flash("Posición guardada.", "success")
    return redirect(url_for("web_rrhh.position_list"))


@web_rrhh_bp.route("/rrhh/positions/<item_id>/delete", methods=["POST"])
def position_delete(item_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    hr.delete_catalog_item(company_id, "positions", item_id, sandbox=sandbox)
    flash("Posición eliminada.", "success")
    return redirect(url_for("web_rrhh.position_list"))
