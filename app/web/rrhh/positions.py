"""RRHH — Catálogo de Posiciones."""

import uuid

from flask import render_template, request, redirect, url_for, session, flash
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr


@web_rrhh_bp.route("/rrhh/positions")
def position_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    items = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    return render_template("rrhh/positions_list.html", active_page="rrhh_positions",
                           items=items, title="Posiciones")


@web_rrhh_bp.route("/rrhh/positions/save", methods=["POST"])
def position_save():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    item_id = request.form.get("id", str(uuid.uuid4()))
    name = request.form.get("name", "").strip()
    if name:
        hr.save_catalog_item(company_id, "positions", {
            "id": item_id, "name": name, "active": True,
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
