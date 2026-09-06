"""DeductionAuthorizationService — Plantilla PDF de Autorización de Descuento de Nómina.

Genera un PDF pre-llenado (empleado, empresa, monto en pesos y letras, cuotas y
concepto) que el empleado firma y que RRHH vuelve a subir como documento firmado.
"""

from flask import render_template

from app.utils.pdf import pdf_write_options
from app.utils.spanish_numbers import numero_a_letras


def can_generate_authorization(movement: dict) -> bool:
    """La autorización aplica a deducciones regulares y préstamos, no a embargos."""
    return movement.get("movementType") == "deduction" and not movement.get("isGarnishment", False)


PAYMENT_PERIOD_LABELS = {
    "mensual": "mensuales",
    "quincenal": "quincenales",
    "semanal": "semanales",
    "diario": "diarias",
}


def _payment_period_adj(employee: dict) -> str:
    """Devuelve el adjetivo del periodo de pago (mensuales/quincenales/...).

    Devuelve "" si la frecuencia es 'ambos' o desconocida, en cuyo caso el
    texto mantiene la coletilla '(dependiendo de mi periodo de pago)'.
    """
    freq = (employee.get("paymentFrequency") or "").strip().lower() if employee else ""
    return PAYMENT_PERIOD_LABELS.get(freq, "")


def authorization_context(movement: dict, employee: dict = None) -> dict:
    """Mapea los campos del movimiento al texto de la autorización."""
    is_loan = bool(movement.get("isLoan", False))
    if is_loan:
        valor_total = float(movement.get("totalAmount", 0) or 0)
        n_cuotas = int(movement.get("totalInstallments", 0) or 0)
        valor_cuota = float(movement.get("installmentAmount", 0) or 0)
    else:
        valor_total = float(movement.get("amount", 0) or 0)
        n_cuotas = 1
        valor_cuota = valor_total

    concepto = (movement.get("description") or "").strip() or (movement.get("conceptCode") or "").strip()

    return {
        "valor_total": valor_total,
        "valor_en_letras": numero_a_letras(valor_total),
        "n_cuotas": n_cuotas,
        "valor_cuota": valor_cuota,
        "concepto": concepto,
        "periodo_adj": _payment_period_adj(employee),
    }


def generate_authorization_pdf(movement: dict, employee: dict, company: dict,
                               host_url: str, today_es: str = "") -> bytes:
    from weasyprint import HTML as WeasyprintHTML

    ctx = authorization_context(movement, employee)
    rendered = render_template(
        "rrhh/recurring/autorizacion_descuento_pdf.html",
        movement=movement,
        employee=employee,
        company=company,
        ctx=ctx,
        today_es=today_es,
    )
    return WeasyprintHTML(string=rendered, base_url=host_url).write_pdf(**pdf_write_options())
