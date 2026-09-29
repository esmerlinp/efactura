"""RRHH module — auto-extracted."""

import calendar
from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file, make_response
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.utils.hr_utils import is_active_equivalent


def _build_employee_tree(employees):
    """Árbol por empleado (reportsTo) → lista de nodos raíz."""
    emp_map = {e["id"]: e for e in employees}
    for e in employees:
        e["direct_reports"] = []
    for e in employees:
        supervisor_id = e.get("reportsTo", "")
        if supervisor_id and supervisor_id in emp_map:
            emp_map[supervisor_id]["direct_reports"].append(e)

    actual_roots = []
    orphans = []
    for e in employees:
        if not e.get("reportsTo") or e.get("reportsTo") not in emp_map:
            if e["direct_reports"]:
                actual_roots.append(e)
            else:
                orphans.append(e)

    if orphans:
        fake_supervisor = {
            "id": "unassigned_group",
            "firstName": "Sin",
            "lastName": "Asignar",
            "fullName": "Sin Supervisor Asignado",
            "position": "Empleados no agrupados",
            "area": "N/A",
            "direct_reports": orphans,
        }
        actual_roots.append(fake_supervisor)
    return actual_roots


def _resolve_position(emp, pos_by_id, pos_by_name):
    """Resuelve el nodo de posición de un empleado (por id, luego por nombre)."""
    return (
        pos_by_id.get(emp.get("positionId", ""))
        or pos_by_name.get((emp.get("position", "") or "").strip().lower())
    )


def build_position_nodes(positions, employees):
    """Árbol por posición (reportsTo del catálogo) → lista de nodos raíz.

    Cada nodo: {id, name, employees[], children[]}. Los empleados sin posición
    (o con posición inexistente) caen en un nodo sintético 'Sin posición asignada'.
    """
    positions = positions or []
    pos_by_id = {p.get("id"): p for p in positions}
    pos_by_name = {(p.get("name") or "").strip().lower(): p for p in positions}

    nodes = {
        p.get("id"): {
            "id": p.get("id"),
            "name": p.get("name", ""),
            "reportsTo": p.get("reportsTo", ""),
            "employees": [],
            "children": [],
        }
        for p in positions
    }

    unassigned = []
    for emp in employees:
        pos = _resolve_position(emp, pos_by_id, pos_by_name)
        if pos:
            nodes[pos["id"]]["employees"].append(emp)
        else:
            unassigned.append(emp)

    parent_map = {}
    for nid, node in nodes.items():
        pid = node.get("reportsTo", "")
        if pid and pid in nodes and pid != nid:
            parent_map[nid] = pid

    # Romper ciclos legacy: quitar la arista que cierra el ciclo.
    def _break_cycle(nid):
        chain = set()
        cur = nid
        while cur in parent_map:
            if cur in chain:
                parent_map.pop(cur, None)
                return
            chain.add(cur)
            cur = parent_map[cur]

    for nid in list(parent_map.keys()):
        _break_cycle(nid)

    roots = []
    for node in nodes.values():
        pid = parent_map.get(node["id"])
        if pid:
            nodes[pid]["children"].append(node)
        else:
            roots.append(node)

    if unassigned:
        unassigned.sort(key=lambda e: (e.get("fullName", "") or "").lower())
        roots.append({
            "id": "unassigned_positions_group",
            "name": "Sin posición asignada",
            "employees": unassigned,
            "children": [],
        })

    for node in nodes.values():
        node["employees"].sort(key=lambda e: (e.get("fullName", "") or "").lower())
    return roots


def _org_chart_data():
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    employees = [e for e in hr.get_employees(company_id, sandbox=sandbox) if is_active_equivalent(e.get("status", ""))]
    view = request.args.get("view", "employee")
    if view not in ("employee", "position"):
        view = "employee"
    root_nodes = _build_employee_tree(employees)
    position_nodes = build_position_nodes(
        hr.get_catalog(company_id, "positions", sandbox=sandbox), employees)
    return {
        "owner_uid": owner_uid,
        "sandbox": sandbox,
        "company_id": company_id,
        "view": view,
        "root_nodes": root_nodes,
        "position_nodes": position_nodes,
        "flat_employees": [],
        "emp_map": {e["id"]: e for e in employees},
    }


@web_rrhh_bp.route("/rrhh/org-chart")
def org_chart():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    data = _org_chart_data()
    return render_template("rrhh/org_chart.html", active_page="rrhh_org_chart", **data)


@web_rrhh_bp.route("/rrhh/org-chart/pdf")
def org_chart_pdf():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    from app.utils.pdf import pdf_write_options
    from weasyprint import HTML as WeasyprintHTML
    from app.web.rrhh.work_certificate import _get_company_data

    data = _org_chart_data()
    company = _get_company_data(data["owner_uid"], company_id=data["company_id"])
    data["is_pdf"] = True

    try:
        rendered = render_template("rrhh/org_chart_pdf.html", active_page="rrhh_org_chart",
                                   company=company, now=date.today().strftime("%d/%m/%Y"),
                                   **data)
        pdf_bytes = WeasyprintHTML(string=rendered, base_url=request.host_url).write_pdf(**pdf_write_options())
    except Exception as e:
        print(f"Error generando PDF de organigrama: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.org_chart"))

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = 'attachment; filename="organigrama.pdf"'
    return response


@web_rrhh_bp.route("/rrhh/calendar")
def team_calendar():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    try:
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))
    except (ValueError, TypeError):
        year, month = date.today().year, date.today().month

    vacations = hr.get_vacation_requests(company_id, sandbox=sandbox)
    leaves = hr.get_leave_requests(company_id, sandbox=sandbox)
    employees = {e["id"]: e for e in hr.get_employees(company_id, sandbox=sandbox)}

    events = []
    for v in vacations:
        if v.get("status") == "aprobada":
            events.append({"type": "vacation", "employeeName": v.get("employeeName", ""),
                          "employeeId": v.get("employeeId", ""),
                          "start": v.get("startDate", ""), "end": v.get("endDate", ""),
                          "days": v.get("days", 0)})
    for l in leaves:
        if l.get("status") == "aprobada":
            events.append({"type": "leave", "employeeName": l.get("employeeName", ""),
                          "employeeId": l.get("employeeId", ""),
                          "start": l.get("startDate", ""), "end": l.get("endDate", ""),
                          "days": l.get("days", 0), "leaveType": l.get("leaveType", "")})

    return render_template("rrhh/team_calendar.html", active_page="rrhh_team_calendar",
                           events=events, year=year, month=month,
                           months_es=MONTHS_ES, employees=employees,
                           num_days=calendar.monthrange(year, month)[1])


