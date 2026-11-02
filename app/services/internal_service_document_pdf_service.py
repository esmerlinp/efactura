"""Generación PDF basada exclusivamente en el snapshot persistido."""

from flask import render_template
try:
    from weasyprint import HTML
except ImportError:  # pragma: no cover - dependency is present in production
    HTML = None

from app.utils.pdf import pdf_write_options
from app.utils.logo import resolve_logo_data_uri


def generate_internal_service_document_pdf(document, company, base_url=""):
    if HTML is None:
        raise RuntimeError("WeasyPrint no está disponible para generar el PDF.")
    html = render_template(
        "internal_documents/service_free_document_pdf.html",
        document=document,
        company=company,
        logo_src=resolve_logo_data_uri(company),
    )
    return HTML(string=html, base_url=base_url).write_pdf(**pdf_write_options())
