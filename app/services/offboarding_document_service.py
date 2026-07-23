"""OffboardingDocumentService — Generación de PDFs legales del proceso de offboarding.

Documentos:
  - Carta de Desvinculación Laboral
  - Acta de Liquidación y Finiquito
  - Certificado de Trabajo (post-offboarding)
"""

import io
import re
import base64
import qrcode
import hashlib
from datetime import date, datetime
from typing import Optional
from flask import render_template, request
from app.web.rrhh.work_certificate import _format_date_es, _today_es
from app.models.offboarding import OFFBOARDING_STATES


MONTHS_ES_FULL = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _company_data(owner_uid: str, sandbox: bool = True, company_id=None) -> dict:
    from app.services.db_service import DatabaseService
    try:
        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
        parts = [p for p in [profile.get("municipality", ""), profile.get("province", "")] if p]
        city = ", ".join(parts)
        return {
            "companyName": profile.get("companyName", ""),
            "rnc": profile.get("companyRNC", ""),
            "address": profile.get("companyAddress", ""),
            "city": city,
            "phone": profile.get("companyPhone", ""),
            "email": profile.get("companyEmail", ""),
            "logoBase64": profile.get("logoBase64", ""),
            "representativeName": profile.get("representativeName", ""),
            "representativePosition": profile.get("representativePosition", ""),
        }
    except Exception:
        return {}


def _generate_qr_base64(data: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=10, border=0)
    qr.add_data(data)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _verification_code() -> str:
    import uuid
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:12].upper()


def _format_key_label(key: str) -> str:
    key = key.replace('_', ' ')
    key = re.sub(r'([a-z])([A-Z])', r'\1 \2', key)
    key = re.sub(r'([A-Z]{2,})([A-Z][a-z])', r'\1 \2', key)
    return key.title()


def generate_termination_letter(
    request_data: dict,
    employee: dict,
    company_data: dict,
    host_url: str,
    settlement_completed: bool = False,
) -> bytes:
    from weasyprint import HTML as WeasyprintHTML

    verification_code = _verification_code()
    qr_data = f"offboarding-letter-{request_data.get('id', '')}-{verification_code}"
    qr_b64 = _generate_qr_base64(qr_data)

    representative_name = company_data.get("representativeName", "")
    representative_position = company_data.get("representativePosition", "") or "Representante Legal"

    rendered = render_template(
        "rrhh/offboarding/carta_desvinculacion_pdf.html",
        request_data=request_data,
        employee=employee,
        company=company_data,
        qr_base64=qr_b64,
        verification_code=verification_code,
        format_date_es=_format_date_es,
        today_es=_today_es(),
        settlement_completed=settlement_completed,
        representative_name=representative_name,
        representative_position=representative_position,
    )
    return WeasyprintHTML(string=rendered, base_url=host_url).write_pdf()


def generate_settlement_acta(
    request_data: dict,
    settlement: dict,
    employee: dict,
    company_data: dict,
    host_url: str,
    settlement_completed: bool = False,
) -> bytes:
    from weasyprint import HTML as WeasyprintHTML

    verification_code = _verification_code()
    qr_data = f"offboarding-settlement-{request_data.get('id', '')}-{verification_code}"
    qr_b64 = _generate_qr_base64(qr_data)

    representative_name = company_data.get("representativeName", "")
    representative_position = company_data.get("representativePosition", "")

    rendered = render_template(
        "rrhh/offboarding/acta_liquidacion_pdf.html",
        request_data=request_data,
        settlement=settlement,
        employee=employee,
        company=company_data,
        qr_base64=qr_b64,
        verification_code=verification_code,
        format_date_es=_format_date_es,
        today_es=_today_es(),
        format_key_label=_format_key_label,
        representative_name=representative_name,
        representative_position=representative_position,
        settlement_completed=settlement_completed,
    )
    return WeasyprintHTML(string=rendered, base_url=host_url).write_pdf()
