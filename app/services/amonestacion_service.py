"""AmonestacionService — Carta de Amonestación (empleado).

Genera el PDF de la carta de amonestación pre-llenado con los datos del
empleado y la empresa. Soporta dos modos:

- **Plantilla en blanco** (tab Documentos): ``tipo`` y ``hecho`` vacíos → el
  template imprime líneas ``______`` para rellenar a mano.
- **Formulario** (Acciones de personal): ``tipo`` y ``hecho`` completos → PDF
  listo para firmar.
"""

from flask import render_template

from app.utils.pdf import pdf_write_options


AMONESTACION_TIPOS = {
    "verbal": "Verbal",
    "escrita_simple": "Escrita Simple",
    "escrita_advertencia": "Escrita con Advertencia",
}


def _today_ddmmyyyy() -> str:
    from datetime import date
    today = date.today()
    return f"{today.day:02d}/{today.month:02d}/{today.year}"


def _normalize_fecha(fecha: str) -> str:
    """Normaliza la fecha a dd/mm/aaaa (acepta input type=date ISO)."""
    import re
    fecha = (fecha or "").strip()
    if not fecha:
        return _today_ddmmyyyy()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", fecha)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return fecha


def build_amonestacion_data(tipo: str = "", hecho: str = "",
                            fecha: str = "", signer_name: str = "",
                            signer_position: str = "") -> dict:
    """Normaliza los campos de la amonestación para el template PDF."""
    return {
        "tipo": tipo,
        "tipo_label": AMONESTACION_TIPOS.get(tipo, ""),
        "hecho": (hecho or "").strip(),
        "fecha": _normalize_fecha(fecha),
        "signer_name": (signer_name or "").strip(),
        "signer_position": (signer_position or "").strip(),
    }


def generate_amonestacion_pdf(employee: dict, company: dict, host_url: str,
                              data: dict) -> bytes:
    from weasyprint import HTML as WeasyprintHTML
    from app.utils.logo import resolve_logo_data_uri

    data = data or {}
    rendered = render_template(
        "rrhh/amonestacion/carta_amonestacion_pdf.html",
        employee=employee,
        company=company,
        data=data,
        logo_src=resolve_logo_data_uri(company),
    )
    return WeasyprintHTML(string=rendered, base_url=host_url).write_pdf(**pdf_write_options())
