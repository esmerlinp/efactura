"""
tax_obligation_service.py — Lógica de obligaciones tributarias DGII (República Dominicana).
Calcula vencimientos, considera feriados oficiales RD (Ley 139-97), cierres fiscales variables (Art. 300 CT),
adapta las obligaciones al Régimen Fiscal del contribuyente (Ordinario Jurídico, Ordinario Persona Física,
RST Ingresos/Compras, Especial/Exento) y expone estado de obligaciones fiscales y laborales.
"""
import logging
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Catálogo de obligaciones DGII / TSS ──────────────────────────────────────
DGII_OBLIGATIONS = [
    {
        "key": "form_606",
        "label": "Formato de Compras — 606",
        "description": "Reporte mensual de compras de bienes y servicios para sustentar costos y gastos.",
        "recurrence": "monthly_15",
        "default_enabled": True,
        "action_url": "/reports-606",
        "action_label": "Generar 606",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "exempt"],
    },
    {
        "key": "form_607",
        "label": "Formato de Ventas — 607",
        "description": "Reporte mensual de ventas de bienes y servicios y retenciones de ITBIS/ISR.",
        "recurrence": "monthly_15",
        "default_enabled": True,
        "action_url": "/reports-607",
        "action_label": "Generar 607",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "exempt"],
    },
    {
        "key": "it1",
        "label": "Declaración Jurada de ITBIS — IT-1",
        "description": "Declaración jurada y pago mensual del ITBIS devengado, retenido y deducible.",
        "recurrence": "monthly_20",
        "default_enabled": True,
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica"],
    },
    {
        "key": "ir17",
        "label": "Retenciones y Retribuciones — IR-17",
        "description": "Declaración y pago mensual de retenciones de ISR y retribuciones complementarias.",
        "recurrence": "monthly_10",
        "default_enabled": True,
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "rst", "exempt"],
    },
    {
        "key": "tss",
        "label": "Seguridad Social y Laboral — TSS / DGT-3",
        "description": "Pago mensual de cotizaciones TSS (Salud, Pensión, Riesgos) y novedades laborales.",
        "recurrence": "monthly_10",
        "default_enabled": True,
        "action_url": "/rrhh/tss",
        "action_label": "Ver TSS",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "rst", "exempt"],
    },
    {
        "key": "ir3_ret",
        "label": "Anticipos ISR (Art. 314 CT) — Mensual",
        "description": "Pago mensual de anticipos del Impuesto Sobre la Renta (12 cuotas del IR-2 / IR-1).",
        "recurrence": "monthly_15",
        "default_enabled": True,
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica"],
    },
    {
        "key": "ir3",
        "label": "Retenciones de Renta a Empleados — IR-3",
        "description": "Declaración mensual de retenciones de ISR aplicadas a los salarios de empleados.",
        "recurrence": "monthly_10",
        "default_enabled": False,
        "action_url": "/rrhh",
        "action_label": "Nómina",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "exempt"],
    },
    {
        "key": "form_608",
        "label": "Comprobantes Anulados — 608",
        "description": "Reporte mensual de NCF y e-CF anulados o cancelados durante el período.",
        "recurrence": "monthly_15",
        "default_enabled": False,
        "action_url": "/reports-608",
        "action_label": "Generar 608",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "exempt"],
    },
    {
        "key": "form_623",
        "label": "Retenciones del Estado — 623",
        "description": "Reporte mensual de retenciones efectuadas por entidades del Estado (5% ITBIS / ISR).",
        "recurrence": "monthly_15",
        "default_enabled": False,
        "action_url": "/reports-623",
        "action_label": "Generar 623",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica"],
    },
    {
        "key": "ir2",
        "label": "Impuesto Sobre la Renta Sociedades — IR-2",
        "description": "Declaración jurada anual del ISR para personas jurídicas (120 días post-cierre fiscal).",
        "recurrence": "annual_120days",
        "default_enabled": True,
        "category": "annual",
        "applies_to": ["ordinary_juridica", "exempt"],
    },
    {
        "key": "act",
        "label": "Activos Imponibles — ACT",
        "description": "Declaración jurada anual del Impuesto sobre los Activos (1% anual en 2 cuotas).",
        "recurrence": "annual_120days",
        "default_enabled": True,
        "category": "annual",
        "applies_to": ["ordinary_juridica"],
    },
    {
        "key": "ir1",
        "label": "Impuesto Sobre la Renta Personas Físicas — IR-1",
        "description": "Declaración jurada anual de personas físicas y negocios de único dueño (90 días post-cierre).",
        "recurrence": "annual_90days",
        "default_enabled": False,
        "category": "annual",
        "applies_to": ["ordinary_fisica"],
    },
    {
        "key": "rst",
        "label": "Régimen Simplificado de Tributación — RST",
        "description": "Declaración jurada anual para contribuyentes acogidos al régimen simplificado RST.",
        "recurrence": "annual_rst_feb",
        "default_enabled": False,
        "category": "annual",
        "applies_to": ["rst"],
    },
]

OBLIGATIONS_DICT = {ob["key"]: ob for ob in DGII_OBLIGATIONS}


# ── Presets por Régimen Fiscal DGII ─────────────────────────────────────────

REGIME_PRESETS = {
    "ordinary_juridica": {
        "key": "ordinary_juridica",
        "label": "Régimen Ordinario (Persona Jurídica / Sociedades)",
        "badge_color": "purple",
        "description": "Aplica a sociedades comerciales (SRL, SA, SAS, EIRL). Declaraciones mensuales 606, 607, IT-1, IR-17, anticipos y anuales IR-2 y Activos (ACT).",
        "enabled_keys": ["form_606", "form_607", "it1", "ir17", "tss", "ir3_ret", "ir2", "act"],
    },
    "ordinary_fisica": {
        "key": "ordinary_fisica",
        "label": "Régimen Ordinario (Persona Física / Servicios Profesionales)",
        "badge_color": "blue",
        "description": "Aplica a personas físicas con negocio de único dueño o servicios independientes. Reportes 606, 607, IT-1, IR-17, anticipos y declaración anual IR-1.",
        "enabled_keys": ["form_606", "form_607", "it1", "ir17", "tss", "ir3_ret", "ir1"],
    },
    "rst": {
        "key": "rst",
        "label": "Régimen Simplificado de Tributación (RST)",
        "badge_color": "emerald",
        "description": "Aplica a contribuyentes acogidos al RST (Compras o Ingresos). No remiten 606/607 mensual ni IT-1 ordinario; presentan declaración jurada anual en febrero.",
        "enabled_keys": ["rst", "ir17", "tss"],
    },
    "exempt": {
        "key": "exempt",
        "label": "Régimen Especial / Exento (Zonas Francas, ONGs)",
        "badge_color": "amber",
        "description": "Aplica a empresas acogidas a incentivos fiscales (Ley 8-90, Ley de Cine, Proindustria) o instituciones sin fines de lucro. Reportes informativos 606, 607, IR-17 y memoria IR-2.",
        "enabled_keys": ["form_606", "form_607", "ir17", "tss", "ir2"],
    },
    "consumer": {
        "key": "consumer",
        "label": "Consumidor Final / No Contribuyente",
        "badge_color": "gray",
        "description": "No sujeto a obligaciones tributarias mensuales ante la DGII.",
        "enabled_keys": [],
    },
}


# ── Recurrence & Date Helpers ───────────────────────────────────────────────

def _last_day_of_month(year: int, month: int) -> date:
    """Devuelve el último día de un mes específico."""
    if month == 12:
        return date(year, 12, 31)
    first_of_next = date(year, month + 1, 1)
    return first_of_next - timedelta(days=1)


def _is_weekend_or_holiday(d: date, company_id: str = None) -> bool:
    """
    Verifica si una fecha cae en fin de semana (sábado/domingo) o feriado oficial RD (Ley 139-97).
    """
    if d.weekday() >= 5:
        return True
    try:
        from app.services.holiday_service import rd_holidays
        hols = {h["date"] for h in rd_holidays(d.year)}
        return d.isoformat() in hols
    except Exception:
        return False


def _next_business_day(d: date, company_id: str = None) -> date:
    """
    Si cae en fin de semana o feriado oficial RD, devuelve el próximo día laborable hábil.
    """
    while _is_weekend_or_holiday(d, company_id):
        d = d + timedelta(days=1)
    return d


def _next_monthly_day(first_due: date, day_of_month: int, today: date) -> date:
    """
    Calcula el próximo vencimiento mensual (día 10, 15, 20) a partir de hoy o first_due.
    """
    start_date = first_due if (first_due and first_due > today) else today

    candidate = date(start_date.year, start_date.month, min(day_of_month, 28))
    while True:
        try:
            candidate = date(start_date.year, start_date.month, day_of_month)
            break
        except ValueError:
            day_of_month -= 1

    if candidate >= start_date:
        return candidate

    next_month = start_date.month + 1
    next_year = start_date.year
    if next_month > 12:
        next_month = 1
        next_year += 1

    d = day_of_month
    while True:
        try:
            return date(next_year, next_month, d)
        except ValueError:
            d -= 1


def _next_annual_120days(today: date, fiscal_end_month: int = 12, first_due: date = None) -> date:
    """
    Anual: 120 días calendario después del cierre fiscal (Art. 300 / 314 CT).
    Para cierre 31-Dic: vence ~30 de Abril.
    Para cierre 31-Mar: vence ~29 de Julio.
    Para cierre 30-Jun: vence ~28 de Octubre.
    Para cierre 30-Sep: vence ~28 de Enero del año siguiente.
    """
    start_date = first_due if (first_due and first_due > today) else today
    year = start_date.year

    for y in [year - 1, year, year + 1, year + 2]:
        closing = _last_day_of_month(y, fiscal_end_month)
        due = closing + timedelta(days=120)
        if first_due and due < first_due:
            continue
        if due >= start_date:
            return due

    closing = _last_day_of_month(year + 1, fiscal_end_month)
    return closing + timedelta(days=120)


def _next_annual_90days(today: date, fiscal_end_month: int = 12, first_due: date = None) -> date:
    """
    Anual: 90 días después del cierre fiscal (IR-1 Personas Físicas).
    Para cierre 31-Dic: vence ~31 de Marzo.
    """
    start_date = first_due if (first_due and first_due > today) else today
    year = start_date.year

    for y in [year - 1, year, year + 1, year + 2]:
        closing = _last_day_of_month(y, fiscal_end_month)
        due = closing + timedelta(days=90)
        if first_due and due < first_due:
            continue
        if due >= start_date:
            return due

    closing = _last_day_of_month(year + 1, fiscal_end_month)
    return closing + timedelta(days=90)


def _next_annual_rst_feb(today: date, first_due: date = None) -> date:
    """
    Anual: Último día hábil de febrero (Declaración Jurada anual de RST).
    """
    start_date = first_due if (first_due and first_due > today) else today
    year = start_date.year

    for y in [year, year + 1, year + 2]:
        due = _last_day_of_month(y, 2)
        if first_due and due < first_due:
            continue
        if due >= start_date:
            return due

    return _last_day_of_month(year + 1, 2)


def _next_due_date(first_due_date_str, recurrence, reference_date=None, fiscal_end_month=12, company_id=None):
    """
    Calcula la próxima fecha de vencimiento a partir de la recurrencia y la fecha de referencia.
    Soporta monthly_15, monthly_20, monthly_10, annual_120days, annual_90days y annual_rst_feb.
    Retorna un objeto date ajustado a día laborable hábil o None.
    """
    today = reference_date or date.today()
    first = None
    if first_due_date_str:
        try:
            first = datetime.strptime(first_due_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            first = None

    raw_due = None
    if recurrence == "monthly_15":
        raw_due = _next_monthly_day(first, 15, today)
    elif recurrence == "monthly_20":
        raw_due = _next_monthly_day(first, 20, today)
    elif recurrence == "monthly_10":
        raw_due = _next_monthly_day(first, 10, today)
    elif recurrence == "annual_120days":
        raw_due = _next_annual_120days(today, fiscal_end_month, first)
    elif recurrence == "annual_90days":
        raw_due = _next_annual_90days(today, fiscal_end_month, first)
    elif recurrence == "annual_rst_feb":
        raw_due = _next_annual_rst_feb(today, first)

    if raw_due:
        return _next_business_day(raw_due, company_id=company_id)
    return None


def _get_fiscal_end_month(owner_uid, company_id=None) -> int:
    """Obtiene el mes de cierre fiscal de la empresa (por defecto 12 = Diciembre)."""
    try:
        from app.services.db_service import DatabaseService
        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
        month = profile.get("fiscalYearEndMonth") or profile.get("fiscal_year_end_month") or profile.get("fiscalClosingMonth")
        if month:
            return int(month)
    except Exception:
        pass
    return 12


# ── Service Class ──────────────────────────────────────────────────────────

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
    def detect_tax_profile(cls, owner_uid, company_id=None):
        """
        Detecta el régimen fiscal y tipo de contribuyente (persona física vs jurídica)
        según el perfil de la empresa en DatabaseService.
        """
        from app.services.db_service import DatabaseService
        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
        raw_regimen = profile.get("regimenFiscal") or profile.get("regimen_fiscal") or "ordinary"
        raw_rnc = (profile.get("companyRNC") or profile.get("rnc") or "")
        rnc_clean = raw_rnc.replace("-", "").replace(" ", "").strip()

        # Determinar si es persona física (Cédula 11 dígitos) o jurídica (RNC 9 dígitos)
        is_physical = len(rnc_clean) == 11 or profile.get("taxpayerType") == "fisica" or profile.get("is_physical_person") is True

        if raw_regimen in ("rst_income", "rst_purchases", "RST", "Simplificado"):
            regime_key = "rst"
        elif raw_regimen in ("exempt", "especial"):
            regime_key = "exempt"
        elif raw_regimen == "consumer":
            regime_key = "consumer"
        else:
            regime_key = "ordinary_fisica" if is_physical else "ordinary_juridica"

        preset_info = REGIME_PRESETS.get(regime_key, REGIME_PRESETS["ordinary_juridica"])
        
        return {
            "regime_key": regime_key,
            "label": preset_info["label"],
            "badge_color": preset_info["badge_color"],
            "description": preset_info["description"],
            "raw_regimen": raw_regimen,
            "rnc": raw_rnc,
            "is_physical_person": is_physical,
            "recommended_keys": preset_info["enabled_keys"],
        }

    @classmethod
    def apply_regime_preset(cls, owner_uid, company_id=None, preset_key=None):
        """
        Aplica un preset de obligaciones (ej. 'ordinary_juridica', 'ordinary_fisica', 'rst', 'exempt').
        Si preset_key es None, detecta automáticamente el del perfil.
        """
        detected = cls.detect_tax_profile(owner_uid, company_id=company_id)
        target_key = preset_key if (preset_key and preset_key in REGIME_PRESETS) else detected["regime_key"]
        preset = REGIME_PRESETS.get(target_key, REGIME_PRESETS["ordinary_juridica"])
        recommended = set(preset["enabled_keys"])

        for ob in DGII_OBLIGATIONS:
            should_enable = ob["key"] in recommended
            cls.save(owner_uid, {
                "obligation_key": ob["key"],
                "enabled": should_enable,
            }, company_id=company_id)

        return {
            "preset_key": target_key,
            "label": preset["label"],
            "enabled_keys": list(recommended),
        }

    @classmethod
    def seed_defaults(cls, owner_uid, company_id=None, force_regime=None):
        """
        Crea o actualiza las obligaciones por defecto adaptadas al régimen fiscal del contribuyente.
        Preserva configuraciones existentes si el documento ya existe.
        """
        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        tax_profile = cls.detect_tax_profile(owner_uid, company_id=company_id)
        recommended_keys = set(tax_profile["recommended_keys"])

        if not config_ref:
            result = []
            for ob in DGII_OBLIGATIONS:
                ob_copy = dict(ob)
                ob_copy["enabled"] = ob["key"] in recommended_keys
                result.append(ob_copy)
            return result

        obligations = []
        for ob in DGII_OBLIGATIONS:
            doc_ref = config_ref.document(ob["key"])
            doc = doc_ref.get()
            if not doc.exists:
                default_enabled = ob["key"] in recommended_keys
                payload = {
                    "obligation_key": ob["key"],
                    "label": ob["label"],
                    "description": ob.get("description", ""),
                    "first_due_date": "",
                    "recurrence": ob["recurrence"],
                    "enabled": default_enabled,
                    "action_url": ob.get("action_url", ""),
                    "action_label": ob.get("action_label", ""),
                    "category": ob.get("category", "monthly"),
                    "last_notified_at": "",
                    "last_notified_period": "",
                }
                doc_ref.set(payload)
                obligations.append(payload)
            else:
                data = doc.to_dict()
                dirty = False
                for field in ["description", "label", "action_url", "action_label", "category", "recurrence"]:
                    if field in ob and data.get(field) != ob.get(field):
                        data[field] = ob.get(field)
                        dirty = True
                if dirty:
                    doc_ref.set(data, merge=True)
                obligations.append(data)
        return obligations

    @classmethod
    def get_all(cls, owner_uid, company_id=None):
        """
        Obtiene todas las obligaciones tributarias en orden canónico.
        """
        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        if not config_ref:
            return cls.seed_defaults(owner_uid, company_id=company_id)

        docs = config_ref.stream()
        db_map = {}
        for doc in docs:
            data = doc.to_dict()
            key = data.get("obligation_key") or doc.id
            data["id"] = doc.id
            data["obligation_key"] = key
            db_map[key] = data

        if not db_map:
            return cls.seed_defaults(owner_uid, company_id=company_id)

        missing = [ob for ob in DGII_OBLIGATIONS if ob["key"] not in db_map]
        if missing:
            cls.seed_defaults(owner_uid, company_id=company_id)
            return cls.get_all(owner_uid, company_id=company_id)

        result = []
        for ob in DGII_OBLIGATIONS:
            key = ob["key"]
            if key in db_map:
                merged = dict(ob)
                merged.update(db_map[key])
                result.append(merged)
        return result

    @classmethod
    def save(cls, owner_uid, obligation_data, company_id=None):
        """
        Guarda o actualiza una obligación para la empresa activa.
        """
        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        if not config_ref:
            return False
        key = obligation_data.get("obligation_key") or obligation_data.get("key")
        if not key:
            return False

        payload = {"obligation_key": key}
        for field in ("label", "description", "first_due_date", "recurrence",
                      "action_url", "action_label", "category",
                      "last_notified_at", "last_notified_period",
                      "last_presented_period", "last_presented_at", "confirmation_number"):
            if field in obligation_data:
                payload[field] = obligation_data[field]
        if "enabled" in obligation_data:
            payload["enabled"] = bool(obligation_data["enabled"])

        config_ref.document(key).set(payload, merge=True)
        return True

    @classmethod
    def get_status(cls, owner_uid, reference_date=None, company_id=None):
        """
        Devuelve una lista con el estado calculado de cada obligación activa.
        """
        today = reference_date or date.today()
        fiscal_end_month = _get_fiscal_end_month(owner_uid, company_id=company_id)
        obligations = cls.get_all(owner_uid, company_id=company_id)
        result = []

        for ob in obligations:
            key = ob.get("obligation_key", ob.get("id"))
            is_enabled = ob.get("enabled", True)
            if not is_enabled:
                continue

            first = ob.get("first_due_date", "")
            recurrence = ob.get("recurrence", "monthly_15")

            next_due = _next_due_date(
                first_due_date_str=first,
                recurrence=recurrence,
                reference_date=today,
                fiscal_end_month=fiscal_end_month,
                company_id=company_id,
            )

            if next_due is None:
                status = "unconfigured"
                days = 0
            else:
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
                "key": key,
                "label": ob.get("label", ""),
                "description": ob.get("description", ""),
                "recurrence": recurrence,
                "category": ob.get("category", "monthly"),
                "action_url": ob.get("action_url", ""),
                "action_label": ob.get("action_label", ""),
                "first_due_date": first,
                "next_due_date": next_due.isoformat() if next_due else "",
                "days_remaining": days if next_due else 0,
                "status": status,
                "enabled": True,
            })
        return result

    @classmethod
    def get_pending_alerts(cls, owner_uid, reference_date=None, company_id=None):
        """Retorna solo las obligaciones que requieren alerta (due_soon, overdue o upcoming)."""
        status_list = cls.get_status(owner_uid, reference_date, company_id=company_id)
        return [s for s in status_list if s["status"] in ("due_soon", "overdue", "upcoming")]

    @classmethod
    def process_notifications(cls, owner_uid, dry_run=False, company_id=None):
        """
        Verifica obligaciones, envía emails para las que vencen en ≤ 3 días,
        y actualiza last_notified_period para evitar duplicados.
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
                continue

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
                <body style="font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; color:#333; max-width:600px; margin:0 auto; padding:20px;">
                    <div style="text-align:center; margin-bottom:20px;">
                        <h2 style="color:#d97706; margin-bottom:4px;">Recordatorio de Obligación Tributaria DGII</h2>
                        <span style="font-size:0.9rem; color:#6b7280;">{company_name}</span>
                    </div>
                    <p>Estimado/a contribuyente,</p>
                    <p>Le recordamos que la siguiente obligación tributaria se encuentra próxima a su fecha límite de presentación y pago:</p>
                    <div style="background:#fffbeb; border:1px solid #f59e0b; border-radius:10px; padding:18px; margin:20px 0;">
                        <div style="font-size:1.1rem; font-weight:700; color:#92400e; margin-bottom:6px;">{s['label']}</div>
                        <div style="font-size:0.95rem; color:#b45309; font-weight:600; margin-bottom:8px;">
                            📅 Fecha límite: <strong>{next_due}</strong> ({s['days_remaining']} días restantes)
                        </div>
                        <p style="font-size:0.85rem; color:#4b5563; margin:0;">{s.get('description', '')}</p>
                    </div>
                    <p style="font-size:0.9rem; color:#374151;">
                        Recuerde realizar su declaración oportunamente a través de la Oficina Virtual (OFV) de la DGII para evitar recargos e intereses moratorios.
                    </p>
                    <hr style="border:none; border-top:1px solid #e5e7eb; margin:24px 0;" />
                    <p style="font-size:0.8rem; color:#9ca3af; text-align:center;">
                        Mensaje automático generado por VykOne ERP para {company_name}.
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
                    }, company_id=company_id)
                    sent += 1
                    logger.info(
                        f"✅ Notificación enviada: {s['label']} para {owner_uid} (company: {company_id}) "
                        f"(vence {next_due})"
                    )
                else:
                    errors += 1
            except Exception as exc:
                logger.error(f"❌ Error notificando {s['label']} para {owner_uid} (company: {company_id}): {exc}")
                errors += 1

        return sent, errors
