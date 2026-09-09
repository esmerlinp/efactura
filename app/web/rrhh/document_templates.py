"""RRHH module — Descarga de plantillas de documentos (pre-llenadas con empleado/empresa).

Asocia cada categoría de documento (del tab Documentos) con una plantilla PDF
existente. Las categorías sin plantilla asociada quedan deshabilitadas en la UI.
"""

import io

from flask import render_template, request, send_file, url_for, redirect

from app.web.rrhh import web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required
from app.services import hr_data_service as hr
from app.utils.pdf import pdf_write_options
from app.web.rrhh.work_certificate import _today_es


# ── Mapa categoría → plantilla ──────────────────────────────────────────────
# Cada clave de categoría se asocia a un generador de PDF "en blanco"
# (pre-llenado con datos de empleado/empresa; campos variables en blanco).
# Los alias mapean claves de categoría equivalentes a la misma plantilla.
DOC_TEMPLATE_MAP = {
    "autorizacion_descuento": "autorizacion_descuento",
    "authorization": "autorizacion_descuento",
    "carta_desvinculacion": "carta_desvinculacion",
    "carta_ministerio_trabajo": "carta_desvinculacion",
}

# Claves de categoría que tienen plantilla descargable (para la UI).
DOC_TEMPLATE_CATEGORIES = set(DOC_TEMPLATE_MAP.keys())


def _generate_autorizacion_descuento(employee, company, host_url, today_es):
    from weasyprint import HTML as WeasyprintHTML

    ctx = {
        "valor_total": None,
        "valor_en_letras": "",
        "n_cuotas": "",
        "valor_cuota": None,
        "concepto": "",
        "periodo_adj": "",
    }
    rendered = render_template(
        "rrhh/recurring/autorizacion_descuento_pdf.html",
        employee=employee,
        company=company,
        ctx=ctx,
        today_es=today_es,
    )
    return WeasyprintHTML(string=rendered, base_url=host_url).write_pdf(**pdf_write_options())


def _generate_carta_desvinculacion(employee, company, host_url, today_es):
    from weasyprint import HTML as WeasyprintHTML

    request_data = {"effectiveDate": ""}
    representative_name = company.get("representativeName", "")
    representative_position = company.get("representativePosition", "") or "Representante Legal"
    rendered = render_template(
        "rrhh/offboarding/carta_desvinculacion_pdf.html",
        request_data=request_data,
        employee=employee,
        company=company,
        representative_name=representative_name,
        representative_position=representative_position,
    )
    return WeasyprintHTML(string=rendered, base_url=host_url).write_pdf(**pdf_write_options())


def _company_data(owner_uid, sandbox, company_id=None):
    from app.services.offboarding_document_service import _company_data as _off_company_data
    return _off_company_data(owner_uid, sandbox=sandbox, company_id=company_id)


_TEMPLATE_GENERATORS = {
    "autorizacion_descuento": _generate_autorizacion_descuento,
    "carta_desvinculacion": _generate_carta_desvinculacion,
}


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/document-template/<category>")
def employee_document_template(employee_id, category):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    template_key = DOC_TEMPLATE_MAP.get(category)
    if not template_key:
        return "Sin plantilla asociada.", 404

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        return "Empleado no encontrado.", 404

    company = _company_data(owner_uid, sandbox, company_id=company_id)
    today_es = _today_es()

    try:
        pdf_bytes = _TEMPLATE_GENERATORS[template_key](employee, company, request.host_url, today_es)
    except Exception as e:
        print(f"Error generando plantilla {category}: {e}")
        return "Error al generar la plantilla.", 500

    filename = f"plantilla_{category}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=filename)
