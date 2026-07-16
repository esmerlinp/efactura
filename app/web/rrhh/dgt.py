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
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    data = DGTService.get_dgt3_data(owner_uid, year, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt3.html", data=data, year=year, now=now,
                           active_page="rrhh_dgt")


@web_invoices_bp.route('/reports/rrhh/dgt/dgt3/export')
@web_rrhh_bp.route("/rrhh/dgt/dgt3/export")
@require_module('nomina')
def dgt3_export():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    fmt = request.args.get("format", "txt")

    data = DGTService.get_dgt3_data(owner_uid, year, sandbox=sandbox)
    lines = data["lines"]
    filename = f"DGT3_{year}"

    if fmt == "txt":
        content = DGTExportService.to_txt(lines)
        buffer = io.BytesIO(content.encode("utf-8"))
        return send_file(buffer, mimetype="text/plain", as_attachment=True,
                         download_name=f"{filename}.txt")
    elif fmt == "xlsx":
        buffer = DGTExportService.to_excel(lines, title=f"DGT-3 {year}")
        return send_file(buffer, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{filename}.xlsx")
    elif fmt == "pdf":
        profile = DatabaseService.get_company_profile(owner_uid)
        buffer = DGTExportService.to_pdf(lines, "dgt3", f"DGT-3 {year}", owner_info=profile)
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
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    data = DGTService.get_dgt4_data(owner_uid, year, month, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt4.html", data=data, year=year, month=month,
                           now=now, active_page="rrhh_dgt")


@web_invoices_bp.route('/reports/rrhh/dgt/dgt4/export')
@web_rrhh_bp.route("/rrhh/dgt/dgt4/export")
@require_module('nomina')
def dgt4_export():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    fmt = request.args.get("format", "txt")

    data = DGTService.get_dgt4_data(owner_uid, year, month, sandbox=sandbox)
    lines = [c["linea"] for c in data["lines"] if c.get("linea")]
    filename = f"DGT4_{year:04d}{month:02d}"

    if fmt == "txt":
        content = DGTExportService.to_txt(lines)
        buffer = io.BytesIO(content.encode("utf-8"))
        return send_file(buffer, mimetype="text/plain", as_attachment=True,
                         download_name=f"{filename}.txt")
    elif fmt == "xlsx":
        buffer = DGTExportService.to_excel(lines, title=f"DGT-4 {year}-{month:02d}")
        return send_file(buffer, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{filename}.xlsx")
    elif fmt == "pdf":
        profile = DatabaseService.get_company_profile(owner_uid)
        buffer = DGTExportService.to_pdf(lines, "dgt4", f"DGT-4 {year}-{month:02d}",
                                          owner_info=profile)
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
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    year = int(request.args.get("year", now.year))
    data = DGTService.get_dgt2_data(owner_uid, year, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt2.html", data=data, year=year, now=now,
                           active_page="rrhh_dgt")


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
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)
    data = DGTService.get_dgt5_data(owner_uid, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt5.html", data=data, now=now,
                           active_page="rrhh_dgt")


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
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
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
        for doc, nom, car in zip(documentos, nombres, cargos):
            if doc.strip():
                data["trabajadores"].append({
                    "documento": doc.strip(),
                    "nombre": nom.strip(),
                    "cargo": car.strip(),
                })
        DGTService.save_dgt9(owner_uid, data, sandbox=sandbox)
        flash("Suspensión DGT-9 registrada exitosamente.", "success")
        return redirect(url_for("web_invoices.dgt9_view"))

    employees = DGTService.get_dgt9_data(owner_uid, sandbox=sandbox)
    return render_template("rrhh/dgt/dgt9.html", data=employees, now=now,
                           active_page="rrhh_dgt")


# ═══════════════════════════════════════════════════════════════════════════
# DGT-12: Cese de Suspensión
# ═══════════════════════════════════════════════════════════════════════════

@web_invoices_bp.route('/reports/rrhh/dgt/dgt12', methods=["GET", "POST"])
@web_rrhh_bp.route("/rrhh/dgt/dgt12", methods=["GET", "POST"])
@require_module('nomina')
def dgt12_view():
    resp = _dgt_login_check()
    if resp:
        return resp
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    now = datetime.now(timezone.utc)

    if request.method == "POST":
        data = {
            "suspensionId": request.form.get("suspensionId", ""),
            "fechaCese": request.form.get("fechaCese", ""),
            "trabajadores": [],
        }
        documentos = request.form.getlist("documento[]")
        nombres = request.form.getlist("nombre[]")
        for doc, nom in zip(documentos, nombres):
            if doc.strip():
                data["trabajadores"].append({
                    "documento": doc.strip(),
                    "nombre": nom.strip(),
                    "fechaReincorporacion": request.form.get("fechaCese", ""),
                })
        DGTService.save_dgt12(owner_uid, data, sandbox=sandbox)
        flash("Cese de suspensión DGT-12 registrado exitosamente.", "success")
        return redirect(url_for("web_invoices.dgt12_view"))

    suspensions = DGTService.get_dgt9_data(owner_uid, sandbox=sandbox)
    active_suspensions = [s for s in suspensions if s.get("estado") == "activa"]
    return render_template("rrhh/dgt/dgt12.html", suspensions=active_suspensions,
                           now=now, active_page="rrhh_dgt")


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
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
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
