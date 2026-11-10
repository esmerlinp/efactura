"""Lógica de vigencia de cotizaciones.

Determina si una cotización está vencida en función de su fecha de emisión y
los días de validez configurados (``professionalData.validityDays``, con
fallback al campo top-level ``validityDays``). La vigencia se cuenta en días
calendario a partir de la fecha de emisión (``date``, o ``createdAt`` como
fallback). Si no hay vigencia definida, la cotización se considera sin
vencimiento.
"""
from datetime import datetime, timezone, timedelta


def quotation_expiry(invoice, today=None):
    """Devuelve información de vigencia de una cotización.

    Retorna un dict:
        {
            "expired": bool,
            "expiry_date": "YYYY-MM-DD" o None,
            "validity_days": int o None,
        }
    """
    professional_data = invoice.get("professionalData") or {}
    validity_days = professional_data.get("validityDays")
    if validity_days is None:
        validity_days = invoice.get("validityDays")

    try:
        validity_days = int(validity_days)
    except (TypeError, ValueError):
        validity_days = None

    if not validity_days or validity_days <= 0:
        return {"expired": False, "expiry_date": None, "validity_days": validity_days}

    date_str = (invoice.get("date") or invoice.get("createdAt") or "").strip()
    date_str = date_str[:10]
    if not date_str:
        return {"expired": False, "expiry_date": None, "validity_days": validity_days}

    try:
        base = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return {"expired": False, "expiry_date": None, "validity_days": validity_days}

    expiry_date = base + timedelta(days=validity_days)
    today = today or datetime.now(timezone.utc).date()

    return {
        "expired": today > expiry_date,
        "expiry_date": expiry_date.isoformat(),
        "validity_days": validity_days,
    }
