import io
from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

from app.services.db_service import DatabaseService
from app.services.ir17_export_service import IR17ExportService
from app.services.ir17_service import IR17Service
from app.utils.decorators import check_permission
from app.utils.module_gate import gate_blueprint_module

web_reports_ir17_bp = Blueprint("web_reports_ir17", __name__)
gate_blueprint_module(web_reports_ir17_bp, "e_cf", feature_name="Formulario IR-17 DGII")


def _context():
    if "user" not in session:
        return None
    if not check_permission("canReportsFiscal"):
        return False
    return {
        "owner_uid": session["user"]["ownerUID"],
        "company_id": session.get("selected_company_id"),
        "sandbox": session.get("is_sandbox_mode", True),
        "user_id": session["user"].get("uid") or session["user"].get("email", "user"),
    }


@web_reports_ir17_bp.before_request
def restrict_ir17():
    if session.get("company_country", "DO") != "DO":
        return render_template("auth/restricted.html", feature_name="IR-17 DGII (solo disponible para República Dominicana)", required_permission=""), 403


@web_reports_ir17_bp.route("/reports/fiscal/ir17")
def ir17_list():
    ctx = _context()
    if ctx is None:
        return redirect(url_for("web_auth.login"))
    if ctx is False:
        return render_template("auth/restricted.html", feature_name="Formulario IR-17", required_permission="canReportsFiscal"), 403
    return render_template("reports/ir17_list.html", declarations=IR17Service.list(**{k: ctx[k] for k in ("owner_uid", "company_id", "sandbox")}), active_page="reports")


@web_reports_ir17_bp.route("/reports/fiscal/ir17/new", methods=["GET", "POST"])
def ir17_new():
    ctx = _context()
    if ctx is None:
        return redirect(url_for("web_auth.login"))
    if ctx is False:
        return render_template("auth/restricted.html", feature_name="Formulario IR-17", required_permission="canReportsFiscal"), 403
    now = datetime.now(timezone.utc)
    period = request.args.get("period", now.strftime("%Y%m"))
    profile = DatabaseService.get_company_profile(ctx["owner_uid"], company_id=ctx["company_id"]) or {}
    data = IR17Service.new_payload(profile, period)
    existing = next((row for row in IR17Service.list(ctx["owner_uid"], ctx["company_id"], ctx["sandbox"]) if row.get("period") == period and row.get("declaration_type", "Normal") == "Normal"), None)
    if existing and request.method == "GET":
        return redirect(url_for("web_reports_ir17.ir17_detail", declaration_id=existing["id"]))
    if request.method == "POST":
        data = _form_payload(request.form, data)
        try:
            declaration = IR17Service.save(
                owner_uid=ctx["owner_uid"],
                company_id=ctx["company_id"],
                sandbox=ctx["sandbox"],
                data=data,
                user_id=ctx["user_id"],
            )
            return redirect(url_for("web_reports_ir17.ir17_detail", declaration_id=declaration["id"]))
        except Exception as exc:
            flash(str(exc), "error")
    return render_template("reports/ir17_form.html", declaration=data, is_new=True, active_page="reports")


@web_reports_ir17_bp.route("/reports/fiscal/ir17/<declaration_id>", methods=["GET", "POST"])
def ir17_detail(declaration_id):
    ctx = _context()
    if ctx is None:
        return redirect(url_for("web_auth.login"))
    if ctx is False:
        return render_template("auth/restricted.html", feature_name="Formulario IR-17", required_permission="canReportsFiscal"), 403
    declaration = IR17Service.get(**{k: ctx[k] for k in ("owner_uid", "company_id", "sandbox")}, declaration_id=declaration_id)
    if not declaration:
        flash("Declaración IR-17 no encontrada.", "error")
        return redirect(url_for("web_reports_ir17.ir17_list"))
    if request.method == "POST":
        if declaration.get("status") == "Presentada":
            flash("La declaración presentada es inmutable. Cree una rectificativa.", "error")
        else:
            try:
                declaration = IR17Service.save(
                    owner_uid=ctx["owner_uid"],
                    company_id=ctx["company_id"],
                    sandbox=ctx["sandbox"],
                    data=_form_payload(request.form, declaration),
                    user_id=ctx["user_id"],
                    declaration_id=declaration_id,
                )
                flash("Borrador IR-17 guardado.", "success")
            except Exception as exc:
                flash(str(exc), "error")
    result = IR17Service.validate(declaration)
    declaration["totals"] = result["calculated"]
    declaration["line_items"] = result["calculated"]["line_items"]
    return render_template("reports/ir17_form.html", declaration=declaration, is_new=False, validation=result, active_page="reports")


@web_reports_ir17_bp.route("/reports/fiscal/ir17/<declaration_id>/validate", methods=["POST"])
def ir17_validate(declaration_id):
    ctx = _context()
    if not ctx or ctx is False:
        return redirect(url_for("web_reports_ir17.ir17_list"))
    declaration = IR17Service.get(**{k: ctx[k] for k in ("owner_uid", "company_id", "sandbox")}, declaration_id=declaration_id)
    result = IR17Service.validate(declaration or {})
    flash("IR-17 válido." if result["valid"] else "Hay errores de validación en el IR-17.", "success" if result["valid"] else "error")
    return redirect(url_for("web_reports_ir17.ir17_detail", declaration_id=declaration_id))


@web_reports_ir17_bp.route("/reports/fiscal/ir17/<declaration_id>/status", methods=["POST"])
def ir17_status(declaration_id):
    ctx = _context()
    if not ctx or ctx is False:
        return redirect(url_for("web_reports_ir17.ir17_list"))
    declaration = IR17Service.get(**{k: ctx[k] for k in ("owner_uid", "company_id", "sandbox")}, declaration_id=declaration_id)
    if declaration and declaration.get("status") != "Presentada":
        declaration["status"] = request.form.get("status", "Borrador")
        declaration["authorization_number"] = request.form.get("authorization_number", "")
        declaration["acknowledgement_number"] = request.form.get("acknowledgement_number", "")
        declaration["dgii_filing_date"] = request.form.get("dgii_filing_date", "")
        IR17Service.save(
            owner_uid=ctx["owner_uid"],
            company_id=ctx["company_id"],
            sandbox=ctx["sandbox"],
            data=declaration,
            user_id=ctx["user_id"],
            declaration_id=declaration_id,
        )
    return redirect(url_for("web_reports_ir17.ir17_detail", declaration_id=declaration_id))


@web_reports_ir17_bp.route("/reports/fiscal/ir17/<declaration_id>/rectify", methods=["POST"])
def ir17_rectify(declaration_id):
    ctx = _context()
    if not ctx or ctx is False:
        return redirect(url_for("web_reports_ir17.ir17_list"))
    original = IR17Service.get(**{k: ctx[k] for k in ("owner_uid", "company_id", "sandbox")}, declaration_id=declaration_id)
    if not original:
        return redirect(url_for("web_reports_ir17.ir17_list"))
    original = dict(original)
    original.pop("id", None)
    original["status"] = "Borrador"
    original["declaration_type"] = "Rectificativa"
    original["original_declaration_id"] = declaration_id
    created = IR17Service.save(
        owner_uid=ctx["owner_uid"],
        company_id=ctx["company_id"],
        sandbox=ctx["sandbox"],
        data=original,
        user_id=ctx["user_id"],
    )
    return redirect(url_for("web_reports_ir17.ir17_detail", declaration_id=created["id"]))


@web_reports_ir17_bp.route("/reports/fiscal/ir17/<declaration_id>/download/<fmt>")
def ir17_download(declaration_id, fmt):
    ctx = _context()
    if not ctx or ctx is False:
        return redirect(url_for("web_reports_ir17.ir17_list"))
    declaration = IR17Service.get(**{k: ctx[k] for k in ("owner_uid", "company_id", "sandbox")}, declaration_id=declaration_id)
    if not declaration:
        return redirect(url_for("web_reports_ir17.ir17_list"))
    stamp = declaration.get("period", "ir17")
    if fmt == "xlsx":
        return send_file(IR17ExportService.xlsx(declaration), as_attachment=True, download_name=f"IR17_{stamp}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if fmt == "csv":
        return send_file(io.BytesIO(IR17ExportService.csv(declaration)), as_attachment=True, download_name=f"IR17_{stamp}.csv", mimetype="text/csv")
    if fmt == "pdf":
        try:
            from weasyprint import HTML
            from app.utils.pdf import pdf_write_options
            pdf = HTML(string=IR17ExportService.pdf_html(declaration)).write_pdf(**pdf_write_options())
        except Exception as exc:
            flash(f"No fue posible generar el PDF: {exc}", "error")
            return redirect(url_for("web_reports_ir17.ir17_detail", declaration_id=declaration_id))
        return send_file(io.BytesIO(pdf), as_attachment=True, download_name=f"IR17_{stamp}.pdf", mimetype="application/pdf")
    return redirect(url_for("web_reports_ir17.ir17_detail", declaration_id=declaration_id))


def _form_payload(form, data):
    payload = dict(data)
    payload["rnc"] = form.get("rnc", data.get("rnc", "")).strip()
    payload["razon_social"] = form.get("razon_social", data.get("razon_social", "")).strip()
    payload["nombre_comercial"] = form.get("nombre_comercial", data.get("nombre_comercial", "")).strip()
    payload["period"] = form.get("period", data.get("period", "")).strip()
    payload["declaration_type"] = form.get("declaration_type", data.get("declaration_type", "Normal"))
    for key in ("conventions_amount", "supplementary_benefits", "supplementary_rate", "authorized_credits", "account_payments", "prior_balance", "surcharges", "indemnity_interest"):
        payload[key] = form.get(key, data.get(key, "0.00"))
    lines = []
    for item in data.get("line_items", []):
        number = item["number"]
        line = dict(item)
        line["base"] = form.get(f"base_{number}", item.get("base", "0.00"))
        lines.append(line)
    payload["line_items"] = lines
    for key in ("authorization_number", "acknowledgement_number", "dgii_filing_date"):
        payload[key] = form.get(key, data.get(key, ""))
    return payload
