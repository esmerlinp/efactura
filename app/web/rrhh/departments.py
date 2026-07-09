"""RRHH — Catálogo de Departamentos."""

import uuid

from flask import render_template, request, redirect, url_for, session, flash
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr


@web_rrhh_bp.route("/rrhh/departments")
def department_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    items = hr.get_catalog(owner_uid, "departments", sandbox=sandbox)
    return render_template("rrhh/departments_list.html", active_page="rrhh_departments",
                           items=items, title="Departamentos")


@web_rrhh_bp.route("/rrhh/departments/save", methods=["POST"])
def department_save():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    item_id = request.form.get("id", str(uuid.uuid4()))
    name = request.form.get("name", "").strip()
    if name:
        hr.save_catalog_item(owner_uid, "departments", {
            "id": item_id, "name": name, "active": True,
        }, sandbox=sandbox)
        flash("Departamento guardado.", "success")
    return redirect(url_for("web_rrhh.department_list"))


@web_rrhh_bp.route("/rrhh/departments/<item_id>/delete", methods=["POST"])
def department_delete(item_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    hr.delete_catalog_item(owner_uid, "departments", item_id, sandbox=sandbox)
    flash("Departamento eliminado.", "success")
    return redirect(url_for("web_rrhh.department_list"))
