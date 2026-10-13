"""Helpers para convertir la configuración de impuestos en listas de opciones
usadas por los formularios (Retenciones, Descuentos y Recargos)."""

ISR_WITHHOLDING_LABELS = {
    "payments_abroad": "Pagos al Exterior (E47)",
    "goods_services": "Bienes y servicios",
    "professional_fees": "Honorarios / Alquiler",
    "digital_services_abroad": "Servicios digitales al exterior",
}

ITBIS_WITHHOLDING_LABELS = {
    "corporate_goods": "Bienes corporativos",
    "legal_services": "Servicios jurídicos",
    "independent_professionals": "Profesionales independientes",
}

ISR_WITHHOLDING_ORDER = ("goods_services", "payments_abroad", "professional_fees", "digital_services_abroad")
ITBIS_WITHHOLDING_ORDER = ("corporate_goods", "legal_services", "independent_professionals")

DEFAULT_ISR_PAYMENTS_ABROAD = 0.27


def _fmt_rate(rate):
    return f"{rate * 100:g}%"


def _build_options(rates, labels, order, default_extra=None):
    options = []
    merged = dict(default_extra or {})
    merged.update(rates or {})
    for key in order:
        rate = float(merged.get(key, 0.0) or 0.0)
        if rate <= 0:
            continue
        label = labels.get(key, key.replace("_", " ").title())
        options.append({"value": rate, "label": f"{_fmt_rate(rate)} — {label}"})
    return options


def isr_withholding_options(rules, include_payments_abroad=False):
    """Lista de opciones de retención ISR a partir de tax_rules.

    ``include_payments_abroad=True`` agrega la opción de Pagos al Exterior (E47),
    usada solo por el módulo de compras. El valor cae a 0.27 si la empresa guardó
    su configuración sin esa clave (el merge de ``get_tax_rules`` es superficial).
    """
    rates = (rules or {}).get("withholding_isr", {}) or {}
    order = tuple(k for k in ISR_WITHHOLDING_ORDER if include_payments_abroad or k != "payments_abroad")
    default_extra = None
    if include_payments_abroad:
        default_extra = {"payments_abroad": float(rates.get("payments_abroad") or DEFAULT_ISR_PAYMENTS_ABROAD)}
    return _build_options(rates, ISR_WITHHOLDING_LABELS, order, default_extra)


def itbis_withholding_options(rules):
    """Lista de opciones de retención ITBIS a partir de tax_rules."""
    rules = rules or {}
    rates = rules.get("withholding_itbis", {}) or rules.get("withholding_vat", {}) or {}
    return _build_options(rates, ITBIS_WITHHOLDING_LABELS, ITBIS_WITHHOLDING_ORDER)