import io
import uuid
import base64
import secrets
import hashlib
import qrcode
from datetime import datetime, timezone, date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file, current_app
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
)
from app.services import hr_data_service as hr
from app.services.db_service import DatabaseService
from app.utils.spanish_numbers import numero_a_letras


MONTHS_ES_FULL = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _format_date_es(date_str):
    if not date_str:
        return ""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        day = d.day
        month = MONTHS_ES_FULL[d.month]
        year = d.year
        return f"{day} de {month} del año {year}"
    except (ValueError, IndexError):
        return date_str


def _today_es():
    today = date.today()
    return f"{today.day} de {MONTHS_ES_FULL[today.month]} del año {today.year}"


def _generate_reference_code(owner_uid, sandbox):
    profile = DatabaseService.get_company_profile(owner_uid)
    seq = profile.get("nextCertificateNumber", 1)
    year = date.today().year
    code = f"CT-{year}-{seq:04d}"
    profile["nextCertificateNumber"] = seq + 1
    DatabaseService.save_company_profile(owner_uid, profile)
    return code


def _compute_avg_commission(owner_uid, employee_id, sandbox):
    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    commissions = []
    for p in periods:
        for line in p.get("lines", []):
            if line.get("employeeId") == employee_id:
                comm = float(line.get("commission", 0) or 0)
                if comm > 0:
                    commissions.append(comm)
    return sum(commissions) / len(commissions) if commissions else 0.0


def _get_company_data(owner_uid):
    profile = DatabaseService.get_company_profile(owner_uid) or {}
    return {
        "companyName": profile.get("companyName", ""),
        "tradeName": profile.get("tradeName", ""),
        "companyRNC": profile.get("companyRNC", ""),
        "companyAddress": profile.get("companyAddress", ""),
        "province": profile.get("province", ""),
        "municipality": profile.get("municipality", ""),
        "companyPhone": profile.get("companyPhone", ""),
        "companyEmail": profile.get("companyEmail", ""),
        "logoUrl": profile.get("logoUrl", ""),
        "logoBase64": profile.get("logoBase64", ""),
        "stampUrl": profile.get("stampUrl", ""),
        "signatureUrl": profile.get("signatureUrl", ""),
        "certificateSignerName": profile.get("certificateSignerName", ""),
        "certificateSignerPosition": profile.get("certificateSignerPosition", ""),
    }


# ═══════════════════════════════════════════════════════════════════════════
# VISTA PREVIA — Carta de Trabajo
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/certificate")
def employee_certificate(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    company = _get_company_data(owner_uid)
    certificates = [c for c in hr.get_work_certificates(owner_uid, sandbox=sandbox)
                    if c.get("employeeId") == employee_id]
    certificates.sort(key=lambda c: c.get("generatedAt", ""), reverse=True)

    return render_template("rrhh/certificate_view.html", active_page="rrhh_employees",
                           employee=employee, company=company,
                           certificates=certificates,
                           today_es=_today_es())


# ═══════════════════════════════════════════════════════════════════════════
# GENERAR — Guardar certificado en Firestore
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/certificate/generate", methods=["POST"])
def certificate_generate(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    purpose = request.form.get("purpose", "general").strip()
    addressee = request.form.get("addressee", "A QUIEN PUEDA INTERESAR").strip()
    if not addressee:
        addressee = "A QUIEN PUEDA INTERESAR"
    issue_city = request.form.get("issueCity", "").strip()

    company = _get_company_data(owner_uid)
    if not issue_city:
        issue_city = company.get("municipality") or company.get("province") or "Santo Domingo"

    base_salary = float(employee.get("baseSalary", 0) or 0)
    avg_commission = _compute_avg_commission(owner_uid, employee_id, sandbox)
    monthly_income = base_salary + avg_commission
    income_words = numero_a_letras(monthly_income)

    reference_code = _generate_reference_code(owner_uid, sandbox)
    verification_code = secrets.token_urlsafe(16)
    issue_date = date.today().isoformat()

    raw = (
        f"{employee.get('fullName', '')}"
        f"{employee.get('cedula', '') or employee.get('idNumber', '')}"
        f"{issue_date}"
        f"{monthly_income}"
    )
    document_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()

    signer_name = company.get("certificateSignerName", "")
    signer_position = company.get("certificateSignerPosition", "")

    cert = {
        "id": str(uuid.uuid4()),
        "referenceCode": reference_code,
        "employeeId": employee_id,
        "employeeName": employee.get("fullName", ""),
        "employeeCedula": employee.get("cedula", "") or employee.get("idNumber", ""),
        "position": employee.get("position", ""),
        "hireDate": employee.get("hireDate", ""),
        "monthlyIncome": monthly_income,
        "avgCommission": avg_commission,
        "monthlyIncomeWords": income_words,
        "issueDate": issue_date,
        "issueCity": issue_city,
        "purpose": purpose,
        "addressee": addressee,
        "signerName": signer_name,
        "signerPosition": signer_position,
        "signatureUrl": company.get("signatureUrl", ""),
        "stampUrl": company.get("stampUrl", ""),
        "logoUrl": company.get("logoUrl", ""),
        "logoBase64": company.get("logoBase64", ""),
        "verificationCode": verification_code,
        "documentHash": document_hash,
        "status": "active",
        "generatedBy": session.get("user", {}).get("email", ""),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }

    hr.save_work_certificate(owner_uid, cert, sandbox=sandbox)

    flash(f"Carta de Trabajo {reference_code} generada exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_certificate", employee_id=employee_id,
                            _anchor=f"cert-{cert['id']}"))


# ═══════════════════════════════════════════════════════════════════════════
# DESCARGAR PDF
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/certificate/<cert_id>/pdf")
def certificate_pdf(employee_id, cert_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    cert = hr.get_work_certificate(owner_uid, cert_id, sandbox=sandbox)
    if not employee or not cert:
        return "Certificado o empleado no encontrado.", 404

    company = _get_company_data(owner_uid)

    qr_url = url_for("web_rrhh.certificate_verify", code=cert["verificationCode"], _external=True)
    qr = qrcode.QRCode(version=1, box_size=10, border=0)
    qr.add_data(qr_url)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_b64 = base64.b64encode(qr_buf.getvalue()).decode("utf-8")

    try:
        from weasyprint import HTML as WeasyprintHTML
        rendered = render_template("rrhh/certificado_trabajo_pdf.html",
                                   employee=employee, cert=cert,
                                   company=company,
                                   qr_base64=qr_b64,
                                   format_date_es=_format_date_es)
        pdf_bytes = WeasyprintHTML(string=rendered, base_url=request.host_url).write_pdf()
        filename = f"carta_trabajo_{cert['referenceCode']}.pdf"
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"Error generando PDF de carta de trabajo: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.employee_certificate", employee_id=employee_id))


# ═══════════════════════════════════════════════════════════════════════════
# ENVIAR POR EMAIL
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/certificate/<cert_id>/email", methods=["POST"])
def certificate_email(employee_id, cert_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    cert = hr.get_work_certificate(owner_uid, cert_id, sandbox=sandbox)
    if not employee or not cert:
        flash("Certificado o empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_certificate", employee_id=employee_id))

    employee_email = (employee.get("email") or "").strip()
    if not employee_email:
        flash("El empleado no tiene un correo electrónico registrado.", "error")
        return redirect(url_for("web_rrhh.employee_certificate", employee_id=employee_id))

    company = _get_company_data(owner_uid)

    qr_url = url_for("web_rrhh.certificate_verify", code=cert["verificationCode"], _external=True)
    qr = qrcode.QRCode(version=1, box_size=10, border=0)
    qr.add_data(qr_url)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_b64 = base64.b64encode(qr_buf.getvalue()).decode("utf-8")

    try:
        from weasyprint import HTML as WeasyprintHTML
        rendered = render_template("rrhh/certificado_trabajo_pdf.html",
                                   employee=employee, cert=cert,
                                   company=company,
                                   qr_base64=qr_b64,
                                   format_date_es=_format_date_es)
        pdf_bytes = WeasyprintHTML(string=rendered, base_url=request.host_url).write_pdf()
    except Exception as e:
        print(f"Error generando PDF para email: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.employee_certificate", employee_id=employee_id))

    try:
        from app.services.mailer import Mailer
        html_body = render_template("rrhh/certificado_trabajo_email.html",
                                    employee=employee, cert=cert, company=company)
        subject = f"Carta de Trabajo — {cert['referenceCode']}"
        Mailer.send(
            app=current_app._get_current_object(),
            to_email=employee_email,
            subject=subject,
            html_body=html_body,
            from_name=company.get("companyName", ""),
            category="noreply",
            attachments=[{
                "filename": f"carta_trabajo_{cert['referenceCode']}.pdf",
                "data": pdf_bytes,
                "mimetype": "pdf",
            }],
        )
        flash(f"Carta de Trabajo enviada a {employee_email}.", "success")
    except Exception as e:
        print(f"Error enviando carta de trabajo por email: {e}")
        flash("Error al enviar la carta por correo.", "error")

    return redirect(url_for("web_rrhh.employee_certificate", employee_id=employee_id))


# ═══════════════════════════════════════════════════════════════════════════
# REVOCAR CERTIFICADO
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/certificate/<cert_id>/revoke", methods=["POST"])
def certificate_revoke(employee_id, cert_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    cert = hr.get_work_certificate(owner_uid, cert_id, sandbox=sandbox)
    if not cert:
        flash("Certificado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_certificate", employee_id=employee_id))

    cert["status"] = "revoked"
    cert["revokedAt"] = datetime.now(timezone.utc).isoformat()
    cert["revokedBy"] = session.get("user", {}).get("email", "")
    hr.save_work_certificate(owner_uid, cert, sandbox=sandbox)

    flash(f"Certificado {cert['referenceCode']} revocado.", "success")
    return redirect(url_for("web_rrhh.employee_certificate", employee_id=employee_id))


# ═══════════════════════════════════════════════════════════════════════════
# VERIFICACIÓN PÚBLICA (QR)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/verify/<code>")
def certificate_verify(code):
    cert = hr.get_work_certificate_by_verification_code(code)
    if not cert:
        return render_template("verify_certificate.html",
                               error="Certificado no encontrado o código inválido.",
                               status="not_found")

    owner_uid = cert.get("_owner_uid", "")
    company = _get_company_data(owner_uid)

    return render_template("verify_certificate.html",
                           cert=cert,
                           company=company,
                           status=cert.get("status", "active"),
                           format_date_es=_format_date_es)
