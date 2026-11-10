"""Lógica de vigencia de cotizaciones.

Determina si una cotización está vencida en función de su fecha de emisión y
los días de validez configurados (``professionalData.validityDays``, con
fallback al campo top-level ``validityDays``). La vigencia se cuenta en días
calendario a partir de la fecha de emisión (``date``, o ``createdAt`` como
fallback). Si no hay vigencia definida, la cotización se considera sin
vencimiento.

También centraliza la transición ``Pendiente Aut. Cliente`` → ``Vencida``:

- ``apply_expiry_status`` es la regla de negocio pura: muta el dict en memoria
  y reporta si cambió. Nunca toca estados terminales (Aprobada, Rechazada,
  Cancelada, etc.) ni documentos que no sean cotizaciones.
- ``persist_quotation_vencida`` escribe únicamente el campo ``status``
  (actualización parcial) para no sobrescribir el resto del documento.
"""
from datetime import datetime, timezone, timedelta

_VENCIDA = "Vencida"
_PENDIENTE_AUT_CLIENTE = "Pendiente Aut. Cliente"


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


def apply_expiry_status(invoice, today=None):
    """Regla de negocio pura: si la cotización está vencida y en estado
    ``Pendiente Aut. Cliente``, fija ``status='Vencida'`` in-place.

    Nunca modifica estados terminales (Aprobada, Rechazada, Cancelada, etc.)
    ni documentos que no sean cotizaciones. Retorna ``True`` si cambió el
    estado (para que el llamador decida persistir); ``False`` en caso contrario.
    """
    if not invoice:
        return False
    if not invoice.get("isQuotation"):
        return False
    if invoice.get("status") != _PENDIENTE_AUT_CLIENTE:
        return False
    if not quotation_expiry(invoice, today=today).get("expired"):
        return False
    invoice["status"] = _VENCIDA
    return True


def persist_quotation_vencida(owner_uid, invoice_id, sandbox=True, company_id=None):
    """Persiste únicamente el campo ``status='Vencida'`` (actualización parcial).

    Usa ``DocumentReference.update`` para no sobrescribir el documento completo,
    evitando perder campos si la copia en memoria está incompleta. Retorna
    ``True`` si la escritura se completó; ``False`` si Firestore no está
    disponible o la actualización falló.
    """
    if not owner_uid or not invoice_id:
        return False
    try:
        from app.services.db_service import (
            db_firestore,
            firebase_initialized,
            _invalidate_invoices,
        )
    except Exception:
        return False
    if not firebase_initialized or db_firestore is None:
        return False
    try:
        coll_name = "sandbox_invoices" if sandbox else "invoices"
        base = (
            db_firestore.collection("companies").document(company_id).collection(coll_name)
            if company_id
            else db_firestore.collection("users").document(owner_uid).collection(coll_name)
        )
        base.document(invoice_id).update({"status": _VENCIDA})
    except Exception as e:
        print(f"⚠️ No se pudo persistir estado 'Vencida' de cotización {invoice_id}: {e}")
        return False
    try:
        _invalidate_invoices(owner_uid, company_id=company_id)
    except Exception:
        pass
    return True
