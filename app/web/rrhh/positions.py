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
        if request.form.get("schedule_submitted") == "1":
            work_schedule = parse_work_schedule_form(request.form)
        else:
            # Edición inline solo de nombre → preservar horario existente
            existing = next((p for p in hr.get_catalog(company_id, "positions", sandbox=sandbox)
                             if p.get("id") == item_id), None)
            work_schedule = existing.get("workSchedule", []) if existing else []
        hr.save_catalog_item(company_id, "positions", {
            "id": item_id, "name": name, "active": True,
            "workSchedule": work_schedule,
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
