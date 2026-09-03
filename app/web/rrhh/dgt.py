"""DGT forms (Ministerio de Trabajo RD) — merged into rrhh package."""

import io
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file

from app.web.rrhh import web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required
from app.web.invoices import web_invoices_bp
from app.utils.module_gate import require_module
from app.services.dgt_service import DGTService
from app.services.dgt_export_service import DGTExportService
from app.services.db_service import DatabaseService
from app.data.occupations_catalog import OCCUPATIONS


def _dgt_login_check():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return None


# ═══════════════════════════════════════════════════════════════════════════
# INDEX — Menú principal DGT
# ═══════════════════════════════════════════════════════════════════════════

@web_invoices_bp.route('/reports/rrhh/dgt')
@web_rrhh_bp.route("/rrhh/dgt")
@require_module('nomina')
def dgt_index():
    resp = _dgt_login_check()
    if resp:
        return resp
    return render_template("rrhh/dgt/index.html", active_page="rrhh_dgt")


# ═══════════════════════════════════════════════════════════════════════════
# DGT-3: Planilla de Personal Fijo
# ═══════════════════════════════════════════════════════════════════════════

@web_invoices_bp.route('/reports/rrhh/dgt/dgt3')
@web_rrhh_bp.route("/rrhh/dgt/dgt3")
@require_module('nomina')
def dgt3_view():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    data = DGTService.get_dgt3_data(company_id, year, month, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt3.html", data=data, year=year, month=month,
                           now=now, active_page="rrhh_dgt")


@web_invoices_bp.route('/reports/rrhh/dgt/dgt3/export')
@web_rrhh_bp.route("/rrhh/dgt/dgt3/export")
@require_module('nomina')
def dgt3_export():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
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
    return redirect(url_for("web_invoices.dgt3_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-4: Cambios en Planilla de Personal Fijo
# ═══════════════════════════════════════════════════════════════════════════

@web_invoices_bp.route('/reports/rrhh/dgt/dgt4')
@web_rrhh_bp.route("/rrhh/dgt/dgt4")
@require_module('nomina')
def dgt4_view():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    data = DGTService.get_dgt4_data(company_id, year, month, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt4.html", data=data, year=year, month=month,
                           now=now, active_page="rrhh_dgt")


@web_invoices_bp.route('/reports/rrhh/dgt/dgt4/export')
@web_rrhh_bp.route("/rrhh/dgt/dgt4/export")
@require_module('nomina')
def dgt4_export():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
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
    return redirect(url_for("web_invoices.dgt4_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-2: Cartel de Horas y Vacaciones
# ═══════════════════════════════════════════════════════════════════════════

@web_invoices_bp.route('/reports/rrhh/dgt/dgt2')
@web_rrhh_bp.route("/rrhh/dgt/dgt2")
@require_module('nomina')
def dgt2_view():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    data = DGTService.get_dgt2_data(company_id, year, month, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt2.html", data=data, year=year, month=month,
                           now=now, active_page="rrhh_dgt")


@web_invoices_bp.route('/reports/rrhh/dgt/dgt2/export')
@web_rrhh_bp.route("/rrhh/dgt/dgt2/export")
@require_module('nomina')
def dgt2_export():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
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
    return redirect(url_for("web_invoices.dgt2_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-5: Personal Móvil u Ocasional
# ═══════════════════════════════════════════════════════════════════════════

@web_invoices_bp.route('/reports/rrhh/dgt/dgt5')
@web_rrhh_bp.route("/rrhh/dgt/dgt5")
@require_module('nomina')
def dgt5_view():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    data = DGTService.get_dgt5_data(company_id, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt5.html", data=data, now=now,
                           active_page="rrhh_dgt")


@web_invoices_bp.route('/reports/rrhh/dgt/dgt5/export')
@web_rrhh_bp.route("/rrhh/dgt/dgt5/export")
@require_module('nomina')
def dgt5_export():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
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
    return redirect(url_for("web_invoices.dgt5_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-9: Suspensión de Contratos
# ═══════════════════════════════════════════════════════════════════════════

@web_invoices_bp.route('/reports/rrhh/dgt/dgt9', methods=["GET", "POST"])
@web_rrhh_bp.route("/rrhh/dgt/dgt9", methods=["GET", "POST"])
@require_module('nomina')
def dgt9_view():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
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
        return redirect(url_for("web_invoices.dgt9_view"))

    employees = DGTService.get_dgt9_data(company_id, sandbox=sandbox)
    from app.services.hr_data_service import get_employees
    active_employees = get_employees(company_id, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt9.html", data=employees, now=now,
                           active_employees=active_employees, active_page="rrhh_dgt")


@web_invoices_bp.route('/reports/rrhh/dgt/dgt9/export')
@web_rrhh_bp.route("/rrhh/dgt/dgt9/export")
@require_module('nomina')
def dgt9_export():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
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
    return redirect(url_for("web_invoices.dgt9_view"))


# ═══════════════════════════════════════════════════════════════════════════
# DGT-12: Cese de Suspensión — DESHABILITADO
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# API: Occupation search
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/dgt/occupations/search")
def occupations_search():
    q = request.args.get("q", "").lower()
    results = [oc for oc in OCCUPATIONS if q in oc["name"].lower() or q in oc["code"]]
    return jsonify(results[:20])


# ═══════════════════════════════════════════════════════════════════════════
# API: Employees for DGT-9/12
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/dgt/employees/search")
def employees_search():
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
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
