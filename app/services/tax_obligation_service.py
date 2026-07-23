"""
tax_obligation_service.py — Lógica de obligaciones tributarias DGII (República Dominicana).
Calcula vencimientos, envía notificaciones y expone estado de obligaciones.
"""
import logging
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Definiciones de obligaciones DGII ──────────────────────────────────────
DGII_OBLIGATIONS = [
    {
        "key": "form_606",
        "label": "Formato de Compras — 606",
        "description": "Reporte mensual de compras de bienes y servicios.",
        "recurrence": "monthly_15",
        "default_enabled": True,
    },
    {
        "key": "form_607",
        "label": "Formato de Ventas — 607",
        "description": "Reporte mensual de ventas de bienes y servicios.",
        "recurrence": "monthly_15",
        "default_enabled": True,
    },
    {
        "key": "it1",
        "label": "Declaración Jurada de ITBIS — IT1",
        "description": "Declaración y pago mensual del ITBIS.",
        "recurrence": "monthly_20",
        "default_enabled": True,
    },
    {
        "key": "ir2",
        "label": "Impuesto Sobre la Renta Sociedades — IR2",
        "description": (
            "Declaración jurada anual del Impuesto Sobre la Renta. "
            "Genera 12 anticipos mensuales (art. 314 Código Tributario)."
        ),
        "recurrence": "annual_120days",
        "default_enabled": True,
    },
    {
        "key": "ir3",
        "label": "Retenciones y Retribuciones en Renta — IR3",
        "description": "Declaración mensual de retenciones de ISR a empleados.",
        "recurrence": "monthly_10",
        "default_enabled": False,
    },
    {
        "key": "act",
        "label": "Activos Imponibles — ACT",
        "description": "Declaración jurada anual de activos imponibles.",
        "recurrence": "annual_120days",
        "default_enabled": True,
    },
    {
        "key": "ir3_ret",
        "label": "Anticipos ISR (Art. 314) — Mensual",
        "description": "Pago mensual del anticipo del Impuesto Sobre la Renta.",
        "recurrence": "monthly_15",
        "default_enabled": True,
    },
]

# ── Recurrence helpers ─────────────────────────────────────────────────────

def _next_due_date(first_due_date_str, recurrence, reference_date=None):
    """
    Calcula la próxima fecha de vencimiento a partir de first_due_date.
    Soporta monthly_15, monthly_20, monthly_10 y annual_120days.
    Retorna un objeto date o None si no se puede calcular.
    """
    if not first_due_date_str:
        return None
    try:
        first = datetime.strptime(first_due_date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

    today = reference_date or date.today()

    if recurrence == "monthly_15":
        return _next_monthly_day(first, 15, today)
    elif recurrence == "monthly_20":
        return _next_monthly_day(first, 20, today)
    elif recurrence == "monthly_10":
        return _next_monthly_day(first, 10, today)
    elif recurrence == "annual_120days":
        return _next_annual_120days(first, today)
    return None


def _next_monthly_day(first_due, day_of_month, today):
    """Calcula el próximo día {day_of_month} del mes corriente o siguiente."""
    # El primer vencimiento define que estamos activos desde esa fecha
    if today < first_due:
        return first_due
    # Buscar el día {day_of_month} del mes actual
    candidate = date(today.year, today.month, min(day_of_month, 28))
    # Ajustar si el día cae en un mes con menos días
    while True:
        try:
            candidate = date(today.year, today.month, day_of_month)
            break
        except ValueError:
            day_of_month -= 1

    if candidate >= today:
        return candidate
    # Si ya pasó, ir al mes siguiente
    next_month = today.month + 1
    next_year = today.year
    if next_month > 12:
        next_month = 1
        next_year += 1
    d = day_of_month
    while True:
        try:
            return date(next_year, next_month, d)
        except ValueError:
            d -= 1


def _next_annual_120days(first_due, today):
    """
    Anual: 120 días después del cierre fiscal (asumimos cierre 31-dic).
    El vencimiento es ~30 de abril del año siguiente.
    Si first_due es la primera declaración, calculamos desde ahí.
    """
    if today < first_due:
        return first_due
    # Calcular el cierre fiscal más reciente cuyo vencimiento ya pasó o está próximo
    # Asumimos cierre fiscal = 31-dic. Vencimiento = 30-abr del año siguiente.
    closing_year = first_due.year - 1  # el cierre que generó first_due
    # Para cada año: cierre 31-dic del año X → vencimiento ~30-abr del año X+1
    # Encontrar el próximo vencimiento >= today
    year = today.year
    # Si hoy es antes del 30-abr del año actual, el próximo vencimiento puede ser 30-abr de este año
    candidate = _april_30(year)
    if candidate < today:
        candidate = _april_30(year + 1)
    return candidate


def _april_30(year):
    return date(year, 4, 30)


def _due_period_key(due_date):
    """Genera una clave única por período para evitar notificaciones duplicadas.
    Ej: '2026-07' para mensual, '2026' para anual."""
    return due_date.strftime("%Y-%m")


def _due_period_key_annual(due_date):
    """Para obligaciones anuales, la clave es el año del vencimiento."""
    return due_date.strftime("%Y")


def _is_weekend_or_holiday(d):
    """Verifica si una fecha cae en fin de semana (RD). Retorna True si sábado o domingo."""
    return d.weekday() >= 5  # 5=Sat, 6=Sun


def _next_business_day(d):
    """Si cae en fin de semana, devuelve el próximo día laborable (lunes)."""
    while _is_weekend_or_holiday(d):
        d = d + timedelta(days=1)
    return d


# ── Service class ──────────────────────────────────────────────────────────

class TaxObligationService:
    COLLECTION = "tax_obligations"

    @classmethod
    def _get_db(cls):
        try:
            from app.services.db_service import db_firestore, firebase_initialized
            if firebase_initialized:
                return db_firestore
        except Exception:
            pass
        return None

    @classmethod
    def _profile_ref(cls, owner_uid, company_id=None):
        from app.services.db_service import _company_coll
        db = cls._get_db()
        if not db:
            return None
        return _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=cls.COLLECTION)

    @classmethod
    def seed_defaults(cls, owner_uid, company_id=None):
        """
        Crea las obligaciones por defecto si no existen para este owner_uid.
        """
        from app.services.db_service import _company_coll
        config_ref = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name=cls.COLLECTION)
        if not config_ref:
            return []
        obligations = []
        for ob in DGII_OBLIGATIONS:
            doc_ref = config_ref.document(ob["key"])
            doc = doc_ref.get()
            if not doc.exists:
                payload = {
                    "obligation_key": ob["key"],
                    "label": ob["label"],
                    "description": ob.get("description", ""),
                    "first_due_date": "",
                    "recurrence": ob["recurrence"],
                    "enabled": ob.get("default_enabled", True),
                    "last_notified_at": "",
                    "last_notified_period": "",
                }
                doc_ref.set(payload)
                obligations.append(payload)
            else:
                data = doc.to_dict()
                # Asegurar que tiene los campos nuevos
                dirty = False
                for field in ["description", "label"]:
                    if field not in data:
                        data[field] = ob.get(field, "")
                        dirty = True
                if dirty:
                    doc_ref.set(data, merge=True)
                obligations.append(data)
        return obligations

    @classmethod
    def get_all(cls, owner_uid, company_id=None):
        """Obtiene todas las obligaciones (con defaults si no existen)."""
        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        if not config_ref:
            return DGII_OBLIGATIONS  # fallback para modo local
        docs = config_ref.stream()
        result = []
        seen_keys = set()
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            result.append(data)
            seen_keys.add(doc.id)
        # Si no hay ninguna, seedear
        if not result:
            cls.seed_defaults(owner_uid, company_id=company_id)
            return cls.get_all(owner_uid, company_id=company_id)
        return result

    @classmethod
    def save(cls, owner_uid, obligation_data, company_id=None):
        """Guarda/actualiza una obligación. Solo actualiza los campos proporcionados."""
        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        if not config_ref:
            return False
        key = obligation_data.get("obligation_key") or obligation_data.get("key")
        if not key:
            return False
        # Solo incluir campos explícitamente pasados (no sobrescribir con defaults vacíos)
        payload = {"obligation_key": key}
        for field in ("label", "description", "first_due_date", "recurrence",
                      "last_notified_at", "last_notified_period"):
            if field in obligation_data:
                payload[field] = obligation_data[field]
        if "enabled" in obligation_data:
            payload["enabled"] = bool(obligation_data["enabled"])
        config_ref.document(key).set(payload, merge=True)
        return True

    @classmethod
    def get_status(cls, owner_uid, reference_date=None, company_id=None):
        """
        Devuelve una lista con el estado de cada obligación:
        - status: 'ok' | 'upcoming' (≤7 días) | 'due_soon' (≤3 días) | 'overdue'
        - next_due_date: próxima fecha de vencimiento
        - days_remaining: días hasta el vencimiento (negativo si vencido)
        """
        today = reference_date or date.today()
        obligations = cls.get_all(owner_uid, company_id=company_id)
        result = []
        for ob in obligations:
            if not ob.get("enabled", True):
                continue
            first = ob.get("first_due_date", "")
            if not first:
                # Si no tiene first_due_date, no podemos calcular
                result.append({
                    "key": ob.get("obligation_key", ob.get("id")),
                    "label": ob.get("label", ""),
                    "description": ob.get("description", ""),
                    "recurrence": ob.get("recurrence", ""),
                    "first_due_date": "",
                    "next_due_date": "",
                    "days_remaining": 0,
                    "status": "unconfigured",
                    "enabled": True,
                })
                continue

            next_due = _next_due_date(first, ob.get("recurrence"), today)
            if next_due is None:
                status = "unconfigured"
                days = 0
            else:
                # Ajustar al próximo día laborable si cae en fin de semana
                next_due = _next_business_day(next_due)
                days = (next_due - today).days
                if days < 0:
                    status = "overdue"
                elif days <= 3:
                    status = "due_soon"
                elif days <= 7:
                    status = "upcoming"
                else:
                    status = "ok"

            result.append({
                "key": ob.get("obligation_key", ob.get("id")),
                "label": ob.get("label", ""),
                "description": ob.get("description", ""),
                "recurrence": ob.get("recurrence", ""),
                "first_due_date": first,
                "next_due_date": next_due.isoformat() if next_due else "",
                "days_remaining": days if next_due else 0,
                "status": status,
                "enabled": ob.get("enabled", True),
            })
        return result

    @classmethod
    def get_pending_alerts(cls, owner_uid, reference_date=None, company_id=None):
        """Obligaciones que requieren alerta: due_soon, overdue, o upcoming."""
        status_list = cls.get_status(owner_uid, reference_date, company_id=company_id)
        return [s for s in status_list if s["status"] in ("due_soon", "overdue", "upcoming")]

    @classmethod
    def process_notifications(cls, owner_uid, dry_run=False, company_id=None):
        """
        Verifica obligaciones, envía emails para las que vencen en ≤ 3 días,
        y actualiza last_notified_period para evitar duplicados.
        Retorna (sent_count, errors).
        """
        from app.services.mailer import Mailer
        from flask import current_app
        from app.services.db_service import DatabaseService

        today = date.today()
        status_list = cls.get_status(owner_uid, today, company_id=company_id)
        obligations = {o.get("key"): o for o in cls.get_all(owner_uid, company_id=company_id)}
        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
        company_email = profile.get("companyEmail", "")
        company_name = profile.get("tradeName") or profile.get("companyName") or "Empresa"

        if not company_email:
            return 0, 0

        sent = 0
        errors = 0

        for s in status_list:
            if s["status"] != "due_soon":
                continue
            key = s["key"]
            ob = obligations.get(key)
            if not ob:
                continue
            period_key = s["next_due_date"][:7]  # YYYY-MM
            if ob.get("last_notified_period") == period_key:
                continue  # ya notificado este período

            if dry_run:
                sent += 1
                continue

            try:
                next_due = s["next_due_date"]
                subject = (
                    f"⚠️ Recordatorio DGII — {s['label']} vence el {next_due} — {company_name}"
                )
                html_body = f"""
                <html>
                <body style="font-family: 'Segoe UI', sans-serif; color:#333; max-width:600px; margin:0 auto; padding:20px;">
                    <h2 style="color:#d97706;">Recordatorio de Obligación Tributaria</h2>
                    <p>Estimado/a contribuyente,</p>
                    <p>Le recordamos que la siguiente obligación tributaria está próxima a vencer:</p>
                    <div style="background:#fef3c7; border:1px solid #f59e0b; border-radius:8px; padding:16px; margin:16px 0;">
                        <strong>{s['label']}</strong><br>
                        <span style="color:#92400e;">Fecha límite: {next_due}</span><br>
                        <span style="font-size:0.85rem; color:#666;">{s.get('description', '')}</span>
                    </div>
                    <p>Recuerde que el incumplimiento de esta obligación puede generar multas por parte de la DGII.</p>
                    <p style="font-size:0.85rem; color:#999; margin-top:24px;">
                        Este es un mensaje automático de {company_name}.
                    </p>
                </body>
                </html>
                """
                success = Mailer.send(
                    app=current_app._get_current_object(),
                    to_email=company_email,
                    subject=subject,
                    html_body=html_body,
                    from_name=company_name,
                    category="reminder",
                )
                if success:
                    cls.save(owner_uid, {
                        "obligation_key": key,
                        "last_notified_at": datetime.now(timezone.utc).isoformat(),
                        "last_notified_period": period_key,
                        "enabled": ob.get("enabled", True),
                        "label": ob.get("label", ""),
                        "description": ob.get("description", ""),
                        "first_due_date": ob.get("first_due_date", ""),
                        "recurrence": ob.get("recurrence", ""),
                    }, company_id=company_id)
                    sent += 1
                    logger.info(
                        f"✅ Notificación enviada: {s['label']} para {owner_uid} "
                        f"(vence {next_due})"
                    )
                else:
                    errors += 1
            except Exception as exc:
                logger.error(f"❌ Error notificando {s['label']} para {owner_uid}: {exc}")
                errors += 1

        return sent, errors
