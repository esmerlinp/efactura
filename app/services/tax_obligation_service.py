"""
tax_obligation_service.py — Lógica de obligaciones tributarias DGII / TSS (República Dominicana).

Calcula vencimientos de forma dinámica (días laborables y feriados RD, Ley 139-97),
adapta las obligaciones al régimen fiscal del contribuyente y sus modalidades:

  - Régimen Ordinario (persona jurídica / persona física)
  - RST por ingresos — persona física (RS-1)
  - RST por ingresos — persona jurídica (RS-2)
  - RST por compras (RS-3)
  - RST agropecuario (RS-4)
  - Régimen Especial / Exento
  - Consumidor final

Las reglas y fuentes normativas viven en `app.countries.do.tax_obligation_rules.py`.
"""
import re
import logging
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Reglas centralizadas ─────────────────────────────────────────────────────
from app.countries.do.tax_obligation_rules import (
    OBLIGATION_CATALOG as DGII_OBLIGATIONS,
    OBLIGATIONS_DICT,
    REGIMES as REGIME_PRESETS,
    LEGACY_KEY_ALIASES,
    PENDING_CONFIRMATIONS,
)

# Condiciones de auto-gate que dependen de la existencia de trabajadores.
EMPLOYEE_CONDITIONS = {
    "employees_with_salary_retention",
    "registered_workers",
    "employer",
}


# ── Date Helpers ─────────────────────────────────────────────────────────────

def _last_day_of_month(year: int, month: int) -> date:
    """Devuelve el último día de un mes específico."""
    if month == 12:
        return date(year, 12, 31)
    first_of_next = date(year, month + 1, 1)
    return first_of_next - timedelta(days=1)


def _is_weekend_or_holiday(d: date, company_id: str = None) -> bool:
    """
    Verifica si una fecha cae en fin de semana (sábado/domingo) o feriado oficial RD (Ley 139-97).
    Nota: los plazos DGII/TSS usan feriados NACIONALES; los feriados propios de la empresa
    no desplazan plazos fiscales, por lo que aquí se usan los feriados RD únicamente.
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


def _last_business_day(year: int, month: int, company_id: str = None) -> date:
    """Último día laborable de un mes (retrocede si el fin de mes cae en fin de semana/feriado)."""
    d = _last_day_of_month(year, month)
    while _is_weekend_or_holiday(d, company_id):
        d = d - timedelta(days=1)
    return d


def _third_business_day(year: int, month: int, company_id: str = None) -> date:
    """Tercer día laborable de un mes (contando hacia adelante)."""
    d = date(year, month, 1)
    count = 0
    while count < 3:
        if not _is_weekend_or_holiday(d, company_id):
            count += 1
        d = d + timedelta(days=1)
    return d - timedelta(days=1)


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
    """Compatibilidad legacy: último día de febrero (Declaración Jurada anual de RST)."""
    return _next_last_business_day(today, 2, first_due=first_due)


def _next_last_business_day(today: date, month: int, first_due: date = None, company_id: str = None) -> date:
    """
    Próximo 'último día laborable' del mes indicado (p. ej. febrero para las DJ RST,
    marzo/junio/septiembre/diciembre para las cuotas RS2).
    """
    start_date = first_due if (first_due and first_due > today) else today

    for y in [start_date.year, start_date.year + 1, start_date.year + 2]:
        due = _last_business_day(y, month, company_id=company_id)
        if first_due and due < first_due:
            continue
        if due >= start_date:
            return due

    return _last_business_day(start_date.year + 1, month, company_id=company_id)


def _next_third_business_day(today: date, first_due: date = None, company_id: str = None) -> date:
    """
    Próximo 'tercer día laborable del mes siguiente' (pago TSS, FAQ TSS #34).
    """
    start_date = first_due if (first_due and first_due > today) else today

    for y in [start_date.year, start_date.year + 1, start_date.year + 2]:
        for m in range(1, 13):
            due = _third_business_day(y, m, company_id=company_id)
            if first_due and due < first_due:
                continue
            if due >= start_date:
                return due

    return _third_business_day(start_date.year + 1, 1, company_id=company_id)


def _next_due_date(first_due_date_str, recurrence, reference_date=None, fiscal_end_month=12, company_id=None):
    """
    Calcula la próxima fecha de vencimiento a partir de la recurrencia y la fecha de referencia.
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
    elif recurrence and recurrence.startswith("monthly_day_"):
        try:
            day_num = int(recurrence.replace("monthly_day_", ""))
            raw_due = _next_monthly_day(first, day_num, today)
        except ValueError:
            raw_due = _next_monthly_day(first, 15, today)
    elif recurrence == "annual_120days":
        raw_due = _next_annual_120days(today, fiscal_end_month, first)
    elif recurrence == "annual_90days":
        raw_due = _next_annual_90days(today, fiscal_end_month, first)
    elif recurrence in ("annual_rst_feb", "last_business_day_february"):
        raw_due = _next_last_business_day(today, 2, first_due=first, company_id=company_id)
    elif recurrence == "last_business_day_march":
        raw_due = _next_last_business_day(today, 3, first_due=first, company_id=company_id)
    elif recurrence == "last_business_day_june":
        raw_due = _next_last_business_day(today, 6, first_due=first, company_id=company_id)
    elif recurrence == "last_business_day_september":
        raw_due = _next_last_business_day(today, 9, first_due=first, company_id=company_id)
    elif recurrence == "last_business_day_december":
        raw_due = _next_last_business_day(today, 12, first_due=first, company_id=company_id)
    elif recurrence == "third_business_day_next_month":
        raw_due = _next_third_business_day(today, first_due=first, company_id=company_id)
    elif recurrence == "annual_date" and first:
        candidate_year = today.year
        try:
            candidate = date(candidate_year, first.month, first.day)
        except ValueError:
            candidate = date(candidate_year, first.month, 28)
        if candidate < today:
            try:
                candidate = date(candidate_year + 1, first.month, first.day)
            except ValueError:
                candidate = date(candidate_year + 1, first.month, 28)
        raw_due = candidate
    elif recurrence in ("fixed_date", "one_time"):
        raw_due = first if first else None

    if raw_due:
        return _next_business_day(raw_due, company_id=company_id)
    return None


def _is_annual_recurrence(recurrence: str) -> bool:
    if not recurrence:
        return False
    return recurrence.startswith("annual") or recurrence == "last_business_day_february"


def _get_period_key(next_due: date, recurrence: str) -> str:
    """
    Retorna la clave de período canónica asociada al vencimiento.
    - Mensuales/cuatrimestrales (monthly_*, last_business_day_mar/jun/sep/dic): 'YYYY-MM'
    - Anuales (annual_*, last_business_day_february): 'YYYY'
    - Fijas / Únicas (fixed_date, one_time): 'YYYY-MM-DD'
    """
    if not next_due:
        return ""
    if _is_annual_recurrence(recurrence):
        return str(next_due.year)
    elif recurrence in ("fixed_date", "one_time"):
        return next_due.isoformat()
    return f"{next_due.year:04d}-{next_due.month:02d}"


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

    # ── Detección de régimen ────────────────────────────────────────────────

    @staticmethod
    def _resolve_rst_modality(regimen: str, rst_modality: str, is_physical: bool) -> str:
        """
        Resuelve la modalidad RST con prioridad:
          1. Modalidad explícita (rst_modality / rstModality).
          2. Régimen base (regimenFiscal).
          3. Tipo de contribuyente (RNC / taxpayerType) — compatibilidad modalidad↔formulario.
        """
        m = (rst_modality or "").strip().lower()
        if m in ("rs1", "rst_income_fisica", "fisica", "ingresos_fisica"):
            return "rst_income_fisica"
        if m in ("rs2", "rst_income_juridica", "juridica", "ingresos_juridica"):
            return "rst_income_juridica"
        if m in ("rs3", "rst_purchases", "compras", "por_compras", "compra"):
            return "rst_purchases"
        if m in ("rs4", "rst_agropecuario", "agropecuario"):
            return "rst_agropecuario"

        r = (regimen or "").strip().lower()
        if r in ("rst_purchases", "compras", "por_compras"):
            return "rst_purchases"
        if r in ("rst_agropecuario", "agropecuario"):
            return "rst_agropecuario"
        if r in ("rst_income", "rst", "simplificado", "rs1", "rs2"):
            return "rst_income_fisica" if is_physical else "rst_income_juridica"

        return "rst_income_fisica" if is_physical else "rst_income_juridica"

    @classmethod
    def detect_tax_profile(cls, owner_uid, company_id=None):
        """
        Detecta el régimen fiscal y tipo de contribuyente (persona física vs jurídica)
        según el perfil de la empresa.

        Prioridad de detección:
          1. Modalidad tributaria explícita (rstModality).
          2. Régimen configurado (regimenFiscal).
          3. Tipo de contribuyente (taxpayerType) / validación RNC.
          4. Compatibilidad modalidad ↔ formulario.
        """
        from app.services.db_service import DatabaseService
        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
        raw_regimen = profile.get("regimenFiscal") or profile.get("regimen_fiscal") or "ordinary"
        rst_modality = profile.get("rstModality") or profile.get("rst_modality") or ""
        taxpayer_type = (profile.get("taxpayerType") or profile.get("taxpayer_type") or "").strip().lower()
        raw_rnc = (profile.get("companyRNC") or profile.get("rnc") or "")
        rnc_clean = re.sub(r"[^0-9]", "", str(raw_rnc))

        # 3. Tipo de contribuyente: explícito o por validación RNC.
        is_physical_explicit = (
            taxpayer_type in ("fisica", "persona_fisica", "pf", "physical", "física")
            or profile.get("is_physical_person") is True
        )
        is_physical = is_physical_explicit or len(rnc_clean) == 11

        regime_key = TaxObligationService._resolve_regime(raw_regimen, rst_modality, is_physical)

        preset_info = REGIME_PRESETS.get(regime_key, REGIME_PRESETS["ordinary_juridica"])

        return {
            "regime_key": regime_key,
            "label": preset_info["label"],
            "badge_color": preset_info["badge_color"],
            "description": preset_info["description"],
            "raw_regimen": raw_regimen,
            "rst_modality": rst_modality,
            "rnc": raw_rnc,
            "is_physical_person": is_physical,
            "recommended_keys": preset_info["enabled_keys"],
        }

    @staticmethod
    def _resolve_regime(raw_regimen, rst_modality, is_physical) -> str:
        reg = (raw_regimen or "").strip().lower()

        if reg in ("consumer", "consumidor", "consumidor final", "final"):
            return "consumer"
        if reg in ("exempt", "exento", "exenta", "especial", "special"):
            return "exempt"

        rst_tokens = {
            "rst", "simplificado", "rst_income", "rst_purchases", "rst_agropecuario",
            "rst_income_fisica", "rst_income_juridica",
            "rs1", "rs2", "rs3", "rs4",
        }
        rst_mod_tokens = {
            "rs1", "rs2", "rs3", "rs4", "rst_income_fisica", "rst_income_juridica",
            "rst_purchases", "rst_agropecuario", "compras", "agropecuario",
        }
        if reg in rst_tokens or (rst_modality or "").strip().lower() in rst_mod_tokens:
            return TaxObligationService._resolve_rst_modality(reg, rst_modality, is_physical)

        return "ordinary_fisica" if is_physical else "ordinary_juridica"

    # ── Presets / seed ───────────────────────────────────────────────────────

    @classmethod
    def apply_regime_preset(cls, owner_uid, company_id=None, preset_key=None):
        """
        Aplica un preset de obligaciones (ej. 'ordinary_juridica', 'rst_income_juridica', ...).
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
                    "conditional": bool(ob.get("conditional")),
                    "condition": ob.get("condition", ""),
                    "source": ob.get("source", ""),
                    "confirmation_status": ob.get("confirmation_status", "confirmed"),
                    "last_notified_at": "",
                    "last_notified_period": "",
                    "is_custom": False,
                }
                doc_ref.set(payload)
                obligations.append(payload)
            else:
                data = doc.to_dict()
                dirty = False
                if "is_custom" not in data:
                    data["is_custom"] = False
                    dirty = True
                if dirty:
                    doc_ref.set(data, merge=True)
                obligations.append(data)
        return obligations

    # ── Lectura / guardado ──────────────────────────────────────────────────

    @classmethod
    def get_all(cls, owner_uid, company_id=None):
        """
        Obtiene todas las obligaciones tributarias en orden canónico,
        incluyendo las alertas personalizadas creadas por el usuario.
        """
        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        if not config_ref:
            return cls.seed_defaults(owner_uid, company_id=company_id)

        docs = config_ref.stream()
        db_map = {}
        custom_docs = []
        for doc in docs:
            data = doc.to_dict()
            key = data.get("obligation_key") or doc.id
            key = LEGACY_KEY_ALIASES.get(key, key)
            data["id"] = doc.id
            data["obligation_key"] = key
            db_map[key] = data
            if key not in OBLIGATIONS_DICT or data.get("is_custom"):
                data["is_custom"] = True
                custom_docs.append(data)

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
                merged["is_custom"] = False
                result.append(merged)

        for c_doc in custom_docs:
            if c_doc["obligation_key"] not in OBLIGATIONS_DICT:
                result.append(c_doc)

        return result

    @classmethod
    def save(cls, owner_uid, obligation_data, company_id=None):
        """
        Guarda o actualiza una obligación o alerta para la empresa activa.
        """
        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        if not config_ref:
            return False
        key = obligation_data.get("obligation_key") or obligation_data.get("key")
        if not key:
            return False
        key = LEGACY_KEY_ALIASES.get(key, key)

        payload = {"obligation_key": key}
        for field in ("label", "description", "first_due_date", "recurrence",
                      "action_url", "action_label", "category", "is_custom",
                      "origin", "metadata", "conditional", "condition", "source",
                      "confirmation_status",
                      "last_notified_at", "last_notified_period",
                      "last_presented_period", "last_presented_at", "confirmation_number",
                      "completed_periods", "last_completed_period", "last_completed_at", "last_completed_by"):
            if field in obligation_data:
                payload[field] = obligation_data[field]
        if "enabled" in obligation_data:
            payload["enabled"] = bool(obligation_data["enabled"])

        if key not in OBLIGATIONS_DICT and "is_custom" not in payload:
            payload["is_custom"] = True

        config_ref.document(key).set(payload, merge=True)
        return True

    # ── Auto-gate por actividad ──────────────────────────────────────────────

    @classmethod
    def _has_active_employees(cls, owner_uid, company_id=None) -> bool | None:
        """
        Determina si la empresa tiene empleados activos (para gatear IR-3/TSS/DGT-3).
        Retorna True / False / None (None = desconocido → se asume que aplica, no se suprime).
        """
        cid = company_id or owner_uid
        try:
            from app.services import hr_data_service as hr
        except Exception:
            return None
        active_statuses = ("activo", "vacaciones", "licencia")
        reached = False
        for sandbox in (True, False):
            try:
                employees = hr.get_employees(cid, sandbox=sandbox)
                reached = True
                if employees and any((e.get("status") or "activo") in active_statuses for e in employees):
                    return True
            except Exception:
                continue
        if reached:
            return False
        return None

    # ── DGT-4 auto alert ────────────────────────────────────────────────────

    @classmethod
    def ensure_dgt4_alert(
        cls,
        company_id: str = None,
        transaction_date=None,
        year: int = None,
        month: int = None,
        owner_uid: str = None,
    ) -> dict:
        """
        Garantiza que exista una alerta en el Registro de Alertas para el reporte DGT-4
        del mes en curso correspondiente a la transacción de entrada (alta) o salida (baja)
        de un empleado.

        Idempotencia: si ya existe una alerta para ese período (clave 'dgt4_YYYY_MM'), no duplica.

        Vencimiento: día 5 del mes siguiente al corte (Reglamento 522-06, Art. 15), ajustado
        a día laborable hábil oficial RD (Ley 139-97).
        """
        if not company_id and not owner_uid:
            return {"created": False, "reason": "missing_company_or_owner"}

        target_year = year
        target_month = month

        if target_year is None or target_month is None:
            tx_date = None
            if transaction_date:
                if isinstance(transaction_date, (date, datetime)):
                    tx_date = transaction_date
                elif isinstance(transaction_date, str) and len(transaction_date) >= 7:
                    try:
                        tx_date = datetime.strptime(transaction_date[:10], "%Y-%m-%d").date()
                    except ValueError:
                        try:
                            parsed_dt = datetime.strptime(transaction_date[:7], "%Y-%m")
                            tx_date = date(parsed_dt.year, parsed_dt.month, 1)
                        except ValueError:
                            tx_date = None
            if not tx_date:
                tx_date = date.today()

            target_year = tx_date.year
            target_month = tx_date.month

        key = f"dgt4_{target_year}_{target_month:02d}"

        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        if not config_ref:
            return {"created": False, "key": key, "reason": "database_unavailable"}

        doc_ref = config_ref.document(key)
        try:
            doc = doc_ref.get()
            if doc.exists:
                return {
                    "created": False,
                    "key": key,
                    "reason": "already_exists",
                    "year": target_year,
                    "month": target_month,
                }
        except Exception as err:
            logger.warning(f"⚠️ Error verificando existencia de alerta DGT-4 ({key}): {err}")

        next_month = target_month + 1
        next_year = target_year
        if next_month > 12:
            next_month = 1
            next_year += 1

        raw_due = date(next_year, next_month, 5)
        due_date = _next_business_day(raw_due, company_id=company_id)

        meses_es = [
            "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        mes_nombre = meses_es[target_month] if 1 <= target_month <= 12 else f"Mes {target_month}"

        payload = {
            "obligation_key": key,
            "label": f"Reporte DGT-4: Cambios en Personal Fijo ({mes_nombre} {target_year})",
            "description": (
                f"Declaración obligatoria de novedades de personal (altas, bajas, cambios de turno, ocupación, "
                f"salario o traslado) del período {target_year}-{target_month:02d} ante el Ministerio de Trabajo (SIRLA)."
            ),
            "first_due_date": due_date.isoformat(),
            "recurrence": "fixed_date",
            "enabled": True,
            "category": "monthly",
            "action_url": f"/rrhh/dgt/dgt4?year={target_year}&month={target_month}",
            "action_label": "Ver / Generar DGT-4",
            "is_custom": True,
            "origin": "rrhh_auto",
            "metadata": {
                "year": target_year,
                "month": target_month,
                "period": f"{target_year}-{target_month:02d}",
                "auto_generated": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        saved = cls.save(owner_uid, payload, company_id=company_id)
        if saved:
            logger.info(f"✅ Alerta DGT-4 creada automáticamente: {key} (Vence: {due_date.isoformat()})")
            return {
                "created": True,
                "key": key,
                "due_date": due_date.isoformat(),
                "year": target_year,
                "month": target_month,
            }
        return {"created": False, "key": key, "reason": "save_failed"}

    # ── Estado ───────────────────────────────────────────────────────────────

    @classmethod
    def delete(cls, owner_uid, obligation_key, company_id=None):
        """
        Elimina una alerta personalizada registrada por el usuario.
        Las obligaciones canónicas DGII no pueden eliminarse, sólo desactivarse.
        """
        if obligation_key in OBLIGATIONS_DICT:
            return False, "Las obligaciones fiscales del sistema no pueden eliminarse, sólo desactivarse."
        config_ref = cls._profile_ref(owner_uid, company_id=company_id)
        if not config_ref:
            return False, "Error de acceso a la base de datos."
        doc_ref = config_ref.document(obligation_key)
        doc = doc_ref.get()
        if not doc.exists:
            return False, "La alerta especificada no existe."
        doc_ref.delete()
        return True, None

    @classmethod
    def get_status(cls, owner_uid, reference_date=None, company_id=None):
        """
        Devuelve una lista con el estado calculado de cada obligación o alerta activa.
        Las obligaciones condicionadas a empleados (IR-3/TSS/DGT-3) se suprimen si la
        empresa no tiene empleados activos (auto-gate). IR-17 no se suprime por empleados
        (depende de operaciones sujetas a retención, no de la nómina).
        """
        today = reference_date or date.today()
        fiscal_end_month = _get_fiscal_end_month(owner_uid, company_id=company_id)
        obligations = cls.get_all(owner_uid, company_id=company_id)

        has_employees = None
        if any(
            o.get("conditional") and o.get("condition") in EMPLOYEE_CONDITIONS
            for o in obligations
        ):
            has_employees = cls._has_active_employees(owner_uid, company_id=company_id)

        result = []

        for ob in obligations:
            key = ob.get("obligation_key") or ob.get("key") or ob.get("id")
            is_enabled = ob.get("enabled", True)
            if not is_enabled:
                continue

            condition = ob.get("condition", "")
            if ob.get("conditional") and condition in EMPLOYEE_CONDITIONS and has_employees is False:
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

            period_key = _get_period_key(next_due, recurrence) if next_due else ""

            completed_periods = ob.get("completed_periods") or {}
            last_comp_period = ob.get("last_completed_period", "")
            is_completed = False
            if period_key:
                is_completed = bool((last_comp_period == period_key) or (period_key in completed_periods))

            completed_at = ""
            if is_completed:
                if isinstance(completed_periods.get(period_key), dict):
                    completed_at = completed_periods[period_key].get("completed_at", "")
                elif period_key in completed_periods:
                    completed_at = str(completed_periods[period_key])
                else:
                    completed_at = ob.get("last_completed_at", "")

            if is_completed:
                status = "completed"
                days = (next_due - today).days if next_due else 0
            elif next_due is None:
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
                "period_key": period_key,
                "days_remaining": days if next_due else 0,
                "status": status,
                "is_completed": is_completed,
                "completed_at": completed_at,
                "enabled": True,
                "is_custom": ob.get("is_custom", False),
                "conditional": bool(ob.get("conditional", False)),
                "condition": condition,
                "source": ob.get("source", ""),
                "confirmation_status": ob.get("confirmation_status", "confirmed"),
            })
        return result

    @classmethod
    def toggle_complete(
        cls,
        owner_uid,
        key,
        period=None,
        completed=None,
        company_id=None,
        completed_by=None,
    ):
        """
        Marca o desmarca una obligación como completada/trabajada para un período específico.
        Si period es None, se calcula a partir del próximo vencimiento actual.
        Si completed es None, invierte el estado actual.
        """
        all_obs = cls.get_all(owner_uid, company_id=company_id)
        ob = next((o for o in all_obs if (o.get("obligation_key") == key or o.get("key") == key)), None)
        if not ob:
            if key not in OBLIGATIONS_DICT:
                return {"success": False, "error": f"Obligación '{key}' no encontrada"}
            ob = dict(OBLIGATIONS_DICT[key])

        recurrence = ob.get("recurrence", "monthly_15")
        target_period = period
        if not target_period:
            fiscal_end_month = _get_fiscal_end_month(owner_uid, company_id=company_id)
            next_due = _next_due_date(
                first_due_date_str=ob.get("first_due_date", ""),
                recurrence=recurrence,
                reference_date=date.today(),
                fiscal_end_month=fiscal_end_month,
                company_id=company_id,
            )
            target_period = _get_period_key(next_due, recurrence) if next_due else ""

        if not target_period:
            return {"success": False, "error": "No se pudo determinar el período de la obligación"}

        completed_periods = dict(ob.get("completed_periods") or {})
        last_period = ob.get("last_completed_period", "")
        is_currently_completed = (last_period == target_period) or (target_period in completed_periods)

        if completed is not None:
            new_state = bool(completed)
        else:
            new_state = not is_currently_completed

        now_iso = datetime.now(timezone.utc).isoformat()

        if new_state:
            completed_periods[target_period] = {
                "completed_at": now_iso,
                "completed_by": completed_by or "user",
            }
            update_payload = {
                "obligation_key": key,
                "completed_periods": completed_periods,
                "last_completed_period": target_period,
                "last_completed_at": now_iso,
                "last_completed_by": completed_by or "user",
            }
        else:
            completed_periods.pop(target_period, None)
            new_last_period = ""
            new_last_at = ""
            if last_period == target_period:
                if completed_periods:
                    new_last_period = max(completed_periods.keys())
                    rec_info = completed_periods[new_last_period]
                    new_last_at = rec_info.get("completed_at", "") if isinstance(rec_info, dict) else str(rec_info)
            else:
                new_last_period = last_period
                new_last_at = ob.get("last_completed_at", "")

            update_payload = {
                "obligation_key": key,
                "completed_periods": completed_periods,
                "last_completed_period": new_last_period,
                "last_completed_at": new_last_at,
            }

        saved = cls.save(owner_uid, update_payload, company_id=company_id)
        if not saved:
            return {"success": False, "error": "Error al persistir el estado de la obligación"}

        return {
            "success": True,
            "key": key,
            "period": target_period,
            "is_completed": new_state,
            "label": ob.get("label", key),
            "completed_at": now_iso if new_state else "",
        }

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

            period_key = s.get("period_key") or s["next_due_date"][:7]
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
