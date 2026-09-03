"""Blueprint de formularios DGT (Ministerio de Trabajo RD)."""

import io
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file

from app.services.dgt_service import DGTService
from app.services.dgt_export_service import DGTExportService
from app.services.db_service import DatabaseService
from app.data.occupations_catalog import OCCUPATIONS

web_dgt_bp = Blueprint("web_dgt", __name__, template_folder="templates")


@web_dgt_bp.before_request
def restrict_to_do():
    if session.get('company_country', 'DO') != 'DO':
        return render_template('auth/restricted.html',
            feature_name="Formularios DGT Ministerio de Trabajo (solo disponibles para República Dominicana)",
            required_permission="")


def _get_owner():
    uid = session.get("selected_owner_uid", "") or session.get("user", {}).get("ownerUID", "")
    sandbox = session.get("is_sandbox_mode", True)
    company_id = session.get("selected_company_id")
    return uid, sandbox, company_id


def _login_check():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    return None


# ═══════════════════════════════════════════════════════════════════════════
# INDEX — Menú principal DGT
# ═══════════════════════════════════════════════════════════════════════════

@web_dgt_bp.route("/rrhh/dgt")
def dgt_index():
    resp = _login_check()
    if resp:
        return resp
    return render_template("rrhh/dgt/index.html", active_page="rrhh_dgt")


# ═══════════════════════════════════════════════════════════════════════════
# DGT-3: Planilla de Personal Fijo
# ═══════════════════════════════════════════════════════════════════════════

@web_dgt_bp.route("/rrhh/dgt/dgt3")
def dgt3_view():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    data = DGTService.get_dgt3_data(company_id, year, month, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt3.html", data=data, year=year, month=month,
                           now=now, active_page="rrhh_dgt")


@web_dgt_bp.route("/rrhh/dgt/dgt3/export")
def dgt3_export():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    fmt = request.args.get("format", "txt")

    data = DGTService.get_dgt3_data(company_id, year, month, sandbox=sandbox)
    lines = data["lines"]
    filename = f"DGT3_{year:04d}{month:02d}"

    if fmt == "txt":
        content = DGTExportService.to_txt(lines, company_info=data.get("company", {}),
                                          year=year, month=month)
        buffer = io.BytesIO(content.encode("utf-8"))
        return send_file(buffer, mimetype="text/plain", as_attachment=True,
                         download_name=f"{filename}.txt")
    elif fmt == "xlsx":
        buffer = DGTExportService.to_excel(lines, title=f"DGT-3 {year}-{month:02d}")
        return send_file(buffer, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{filename}.xlsx")
    elif fmt == "pdf":
        buffer = DGTExportService.to_pdf(lines, "dgt3", f"DGT-3 {year}-{month:02d}", data=data)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                         download_name=f"{filename}.pdf")
    return redirect(url_for("web_dgt.dgt3_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-4: Cambios en Planilla de Personal Fijo
# ═══════════════════════════════════════════════════════════════════════════

@web_dgt_bp.route("/rrhh/dgt/dgt4")
def dgt4_view():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    data = DGTService.get_dgt4_data(company_id, year, month, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt4.html", data=data, year=year, month=month,
                           now=now, active_page="rrhh_dgt")


@web_dgt_bp.route("/rrhh/dgt/dgt4/export")
def dgt4_export():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    fmt = request.args.get("format", "txt")

    data = DGTService.get_dgt4_data(company_id, year, month, sandbox=sandbox)
    lines = [c["linea"] for c in data["lines"] if c.get("linea")]
    filename = f"DGT4_{year:04d}{month:02d}"

    if fmt == "txt":
        content = DGTExportService.to_sirla_txt_dgt4(
            lines,
            company_info=data.get("company", {}),
            year=year, month=month,
        )
        buffer = io.BytesIO(content.encode("utf-8"))
        return send_file(buffer, mimetype="text/plain", as_attachment=True,
                         download_name=f"{filename}.txt")
    elif fmt == "xlsx":
        buffer = DGTExportService.to_excel(lines, title=f"DGT-4 {year}-{month:02d}")
        return send_file(buffer, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{filename}.xlsx")
    elif fmt == "pdf":
        buffer = DGTExportService.to_pdf(lines, "dgt4", f"DGT-4 {year}-{month:02d}", data=data)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                         download_name=f"{filename}.pdf")
    return redirect(url_for("web_dgt.dgt4_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-2: Cartel de Horas y Vacaciones
# ═══════════════════════════════════════════════════════════════════════════

@web_dgt_bp.route("/rrhh/dgt/dgt2")
def dgt2_view():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    data = DGTService.get_dgt2_data(company_id, year, month, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt2.html", data=data, year=year, month=month,
                           now=now, active_page="rrhh_dgt")


@web_dgt_bp.route("/rrhh/dgt/dgt2/export")
def dgt2_export():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    fmt = request.args.get("format", "txt")

    data = DGTService.get_dgt2_data(company_id, year, month, sandbox=sandbox)
    sirla_lines = data.get("sirlaLines", [])
    filename = f"DGT2_{year:04d}{month:02d}"

    if fmt == "txt":
        content = DGTExportService.to_sirla_txt_dgt2(
            sirla_lines,
            company_info={"companyRNC": (DatabaseService.get_company(company_id) or {}).get("rnc", "")},
            establishment_id=data.get("establishmentId", "000000"),
            year=year,
            month=month,
        )
        buffer = io.BytesIO(content.encode("utf-8"))
        return send_file(buffer, mimetype="text/plain", as_attachment=True,
                         download_name=f"{filename}.txt")
    elif fmt == "xlsx":
        buffer = DGTExportService.to_excel(sirla_lines, title=f"DGT-2 {year}-{month:02d}")
        return send_file(buffer, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{filename}.xlsx")
    elif fmt == "pdf":
        buffer = DGTExportService.to_pdf(sirla_lines, "dgt2", f"DGT-2 {year}-{month:02d}", data=data)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                         download_name=f"{filename}.pdf")
    return redirect(url_for("web_dgt.dgt2_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-5: Personal Móvil u Ocasional
# ═══════════════════════════════════════════════════════════════════════════

@web_dgt_bp.route("/rrhh/dgt/dgt5")
def dgt5_view():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    data = DGTService.get_dgt5_data(company_id, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt5.html", data=data, now=now,
                           active_page="rrhh_dgt")


@web_dgt_bp.route("/rrhh/dgt/dgt5/export")
def dgt5_export():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    fmt = request.args.get("format", "xlsx")

    data = DGTService.get_dgt5_data(company_id, sandbox=sandbox)
    filename = f"DGT5"

    if fmt == "xlsx":
        buffer = DGTExportService.to_excel(data.get("lines", []), title="DGT-5")
        return send_file(buffer, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{filename}.xlsx")
    elif fmt == "pdf":
        buffer = DGTExportService.to_pdf(data.get("lines", []), "dgt5", "DGT-5", data=data)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                         download_name=f"{filename}.pdf")
    return redirect(url_for("web_dgt.dgt5_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-9: Suspensión de Contratos
# ═══════════════════════════════════════════════════════════════════════════

@web_dgt_bp.route("/rrhh/dgt/dgt9", methods=["GET", "POST"])
def dgt9_view():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)

    if request.method == "POST":
        data = {
            "establishmentId": request.form.get("establishmentId", ""),
            "fechaSolicitud": request.form.get("fechaSolicitud", ""),
            "causa": request.form.get("causa", ""),
            "fechaInicio": request.form.get("fechaInicio", ""),
            "fechaFinPrevista": request.form.get("fechaFinPrevista", ""),
            "trabajadores": [],
        }
        documentos = request.form.getlist("documento[]")
        nombres = request.form.getlist("nombre[]")
        cargos = request.form.getlist("cargo[]")
        employee_ids = request.form.getlist("employeeId[]")
        for i, (doc, nom, car) in enumerate(zip(documentos, nombres, cargos)):
            if doc.strip():
                emp_id = employee_ids[i] if i < len(employee_ids) else ""
                data["trabajadores"].append({
                    "documento": doc.strip(),
                    "nombre": nom.strip(),
                    "cargo": car.strip(),
                    "employeeId": emp_id.strip(),
                })
        DGTService.save_dgt9(company_id, data, sandbox=sandbox)
        flash("Suspensión DGT-9 registrada exitosamente.", "success")
        return redirect(url_for("web_dgt.dgt9_view"))

    employees = DGTService.get_dgt9_data(company_id, sandbox=sandbox)
    from app.services.hr_data_service import get_employees
    active_employees = get_employees(company_id, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt9.html", data=employees, now=now,
                           active_employees=active_employees, active_page="rrhh_dgt")


@web_dgt_bp.route("/rrhh/dgt/dgt9/export")
def dgt9_export():
    resp = _login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner()
    now = datetime.now(timezone.utc)
    fmt = request.args.get("format", "txt")

    data = DGTService.get_dgt9_sirla_data(company_id, sandbox=sandbox)
    filename = f"DGT9"

    if fmt == "txt":
        content = DGTExportService.to_sirla_txt_dgt9(data)
        buffer = io.BytesIO(content.encode("utf-8"))
        return send_file(buffer, mimetype="text/plain", as_attachment=True,
                         download_name=f"{filename}.txt")
    elif fmt == "xlsx":
        all_workers = []
        for s in data.get("suspensions", []):
            for w in s.get("trabajadores", []):
                all_workers.append(w)
        buffer = DGTExportService.to_excel(all_workers, title="DGT-9")
        return send_file(buffer, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{filename}.xlsx")
    elif fmt == "pdf":
        buffer = DGTExportService.to_pdf([], "dgt9", "DGT-9", data=data)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                         download_name=f"{filename}.pdf")
    return redirect(url_for("web_dgt.dgt9_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-12: Cese de Suspensión — DESHABILITADO
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# API: Occupation search
# ═══════════════════════════════════════════════════════════════════════════

@web_dgt_bp.route("/rrhh/dgt/occupations/search")
def occupations_search():
    q = request.args.get("q", "").lower()
    results = [oc for oc in OCCUPATIONS if q in oc["name"].lower() or q in oc["code"]]
    return jsonify(results[:20])


# ═══════════════════════════════════════════════════════════════════════════
# API: Employees for DGT-9/12
# ═══════════════════════════════════════════════════════════════════════════

@web_dgt_bp.route("/rrhh/dgt/employees/search")
def employees_search():
    owner_uid, sandbox, company_id = _get_owner()
    from app.services import hr_data_service as hr
    employees = hr.get_employees(company_id, sandbox=sandbox)
    q = request.args.get("q", "").lower()
    results = []
    for e in employees:
        name = e.get("fullName", "").lower()
        doc = (e.get("cedula") or e.get("idNumber", "")).lower()
        if q in name or q in doc:
            results.append({
                "id": e.get("id", ""),
                "fullName": e.get("fullName", ""),
                "cedula": (e.get("cedula") or e.get("idNumber", "")).replace("-", ""),
                "position": e.get("position", ""),
            })
    return jsonify(results[:20])
