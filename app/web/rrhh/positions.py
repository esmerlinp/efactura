"""RRHH — Maestro de Posiciones (grid + ficha de descripción de puesto)."""

import uuid

from flask import render_template, request, redirect, url_for, flash
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr

# Días de la semana para el editor de horario: (código, índice 0=Lun..6=Dom)
_SCHEDULE_DAYS = [
    ("L", 0), ("M", 1), ("X", 2), ("J", 3), ("V", 4), ("S", 5), ("D", 6),
]

# Nivel jerárquico del cargo (enum canónico → etiqueta)
POSITION_LEVELS = [
    ("estrategico", "Estratégico"),
    ("tactico", "Táctico"),
    ("operativo", "Operativo"),
]
POSITION_LEVEL_LABELS = dict(POSITION_LEVELS)


def _level_label(level: str) -> str:
    return POSITION_LEVEL_LABELS.get((level or "").strip(), "")


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


def _form_list(name: str) -> list:
    """Lista de strings no vacíos desde inputs repetidos del formulario."""
    values = []
    for v in request.form.getlist(name):
        v = (v or "").strip()
        if v:
            values.append(v)
    return values


def _get_position(company_id: str, item_id: str, sandbox: bool) -> dict | None:
    for p in hr.get_catalog(company_id, "positions", sandbox=sandbox):
        if p.get("id") == item_id:
            return p
    return None


@web_rrhh_bp.route("/rrhh/positions")
def position_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    items = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    departments = hr.get_catalog(company_id, "departments", sandbox=sandbox)
    dept_by_id = {d.get("id"): d for d in departments}
    pos_by_id = {p.get("id"): p for p in items}

    # Conteo de empleados por posición (por id, luego por nombre).
    emp_counts = {}
    try:
        employees = hr.get_employees(company_id, sandbox=sandbox)
        for e in employees:
            key = e.get("positionId")
            if not key or key not in pos_by_id:
                key = next(
                    (pid for pid, p in pos_by_id.items()
                     if (p.get("name", "") or "").strip().lower()
                     == (e.get("position", "") or "").strip().lower()),
                    None,
                )
            if key:
                emp_counts[key] = emp_counts.get(key, 0) + 1
    except Exception:
        pass

    rows = []
    for item in items:
        item_id = item.get("id", "")
        dept = dept_by_id.get(item.get("departmentId", ""), {})
        rows.append({
            "id": item_id,
            "name": item.get("name", ""),
            "area": dept.get("name", ""),
            "level": _level_label(item.get("level", "")),
            "reports_to": (pos_by_id.get(item.get("reportsTo", ""), {}) or {}).get("name", ""),
            "employee_count": emp_counts.get(item_id, 0),
        })

    return render_template("rrhh/positions_list.html", active_page="rrhh_positions",
                           rows=rows, title="Posiciones")


@web_rrhh_bp.route("/rrhh/positions/save", methods=["POST"])
def position_save():
    """Crea una nueva posición (nombre + reporta a) y redirige a su ficha."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    item_id = str(uuid.uuid4())
    name = request.form.get("name", "").strip()
    if name:
        hr.save_catalog_item(company_id, "positions", {
            "id": item_id, "name": name, "active": True,
            "workSchedule": [], "reportsTo": request.form.get("reportsTo", "").strip(),
        }, sandbox=sandbox)
        flash("Posición creada. Completa su descripción de puesto.", "success")
        return redirect(url_for("web_rrhh.position_detail", item_id=item_id))
    flash("El nombre de la posición es obligatorio.", "error")
    return redirect(url_for("web_rrhh.position_list"))


@web_rrhh_bp.route("/rrhh/positions/<item_id>")
def position_detail(item_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    items = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    item = next((p for p in items if p.get("id") == item_id), None)
    if item is None:
        flash("La posición no existe.", "error")
        return redirect(url_for("web_rrhh.position_list"))
    departments = hr.get_catalog(company_id, "departments", sandbox=sandbox)
    pos_by_id = {p.get("id"): p for p in items}
    dept_by_id = {d.get("id"): d for d in departments}

    competencies = item.get("competencies") or {}
    ctx = {
        "item": item,
        "area": dept_by_id.get(item.get("departmentId", ""), {}).get("name", ""),
        "level": _level_label(item.get("level", "")),
        "supervisor": (pos_by_id.get(item.get("reportsTo", ""), {}) or {}).get("name", ""),
        "departments": departments,
        "positions": items,
        "levels": POSITION_LEVELS,
        "functions": item.get("functions", []) or [],
        "responsibilities": item.get("responsibilities", []) or [],
        "performance_indicators": item.get("performanceIndicators", []) or [],
        "competencies_knowledge": competencies.get("knowledge", []) or [],
        "competencies_skills": competencies.get("skills", []) or [],
        "competencies_attitudes": competencies.get("attitudes", []) or [],
        "edit": request.args.get("edit") == "1",
    }
    return render_template("rrhh/positions_detail.html", active_page="rrhh_positions",
                           title=item.get("name", "Posición"), **ctx)


@web_rrhh_bp.route("/rrhh/positions/<item_id>/save", methods=["POST"])
def position_detail_save(item_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    positions = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    existing = next((p for p in positions if p.get("id") == item_id), None)
    if existing is None:
        flash("La posición no existe.", "error")
        return redirect(url_for("web_rrhh.position_list"))

    name = request.form.get("name", "").strip()
    if not name:
        flash("El nombre de la posición es obligatorio.", "error")
        return redirect(url_for("web_rrhh.position_detail", item_id=item_id))

    reports_to = request.form.get("reportsTo", "").strip()
    if not _reports_to_is_valid(positions, item_id, reports_to):
        flash("La jerarquía seleccionada crea un ciclo o se refiere a sí misma.", "error")
        return redirect(url_for("web_rrhh.position_detail", item_id=item_id, edit=1))

    level = request.form.get("level", "").strip()
    if level not in POSITION_LEVEL_LABELS:
        level = ""

    competencies = {
        "knowledge": _form_list("competencies_knowledge"),
        "skills": _form_list("competencies_skills"),
        "attitudes": _form_list("competencies_attitudes"),
    }

    hr.save_catalog_item(company_id, "positions", {
        "id": item_id,
        "name": name,
        "active": True,
        "workSchedule": existing.get("workSchedule", []) or [],
        "reportsTo": reports_to,
        "departmentId": request.form.get("departmentId", "").strip(),
        "level": level,
        "purpose": request.form.get("purpose", "").strip(),
        "functions": _form_list("functions"),
        "responsibilities": _form_list("responsibilities"),
        "competencies": competencies,
        "performanceIndicators": _form_list("performanceIndicators"),
    }, sandbox=sandbox)
    flash("Descripción de puesto guardada.", "success")
    return redirect(url_for("web_rrhh.position_detail", item_id=item_id))


@web_rrhh_bp.route("/rrhh/positions/<item_id>/delete", methods=["POST"])
def position_delete(item_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    hr.delete_catalog_item(company_id, "positions", item_id, sandbox=sandbox)
    flash("Posición eliminada.", "success")
    return redirect(url_for("web_rrhh.position_list"))
