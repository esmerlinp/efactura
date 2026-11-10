"""
notification_center.py — Centro de Notificaciones unificado de VykOne.

Normaliza, clasifica y consolida elementos de múltiples fuentes en una única
línea de tiempo, sin mover la fuente de verdad de cada dominio:

  - CRM menciones        → DatabaseService.get_user_notifications()
  - CRM compromisos      → DatabaseService.get_crm_contacts()
  - Fiscal               → TaxObligationService.get_status()   (EN VIVO, no se persiste)
  - Sistema / RRHH       → preparadas (vacías) para fuentes futuras.

Principios:
  * TaxObligationService sigue siendo la fuente de verdad de las obligaciones
    tributarias. Marcar una alerta como "leída" NUNCA modifica la obligación
    ni completa el período (eso lo hace TaxObligationService.toggle_complete).
  * El estado de lectura se persiste por USUARIO y EMPRESA en una subcolección
    escalable (no en un mapa ilimitado).
  * La autorización fiscal se valida en el backend ANTES de consultar
    TaxObligationService (ocultar en UI no es suficiente).
"""
import hashlib
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Permisos que habilitan la consulta de información fiscal ─────────────────
# (check estricto: sin fallback permisivo; el owner siempre puede ver.)
FISCAL_PERMISSIONS = (
    "canAccounting",
    "canAccountingDashboard",
    "canManageTaxes",
    "canReportsFiscal",
    "canReportsAccounting",
)


def can_view_fiscal(access) -> bool:
    """Determina si un acceso de empresa permite consultar obligaciones fiscales."""
    if access is None:
        return False
    if getattr(access, "role", None) == "owner":
        return True
    perms = getattr(access, "permissions", None) or {}
    return any(perms.get(p) for p in FISCAL_PERMISSIONS)


# ── Estado de lectura (por usuario + empresa) ───────────────────────────────

class NotificationStateService:
    """
    Persiste el estado de lectura de los elementos del centro por usuario y empresa.
    Estructura escalable (subcolección por item, no un mapa ilimitado):

        users/{uid}/notification_state/{company_id}/read_items/{sha1(item_id)}
            → { item_id, read_at }
    """
    COLLECTION = "notification_state"

    @classmethod
    def _db(cls):
        try:
            from app.services.db_service import db_firestore, firebase_initialized
            if firebase_initialized:
                return db_firestore
        except Exception:
            pass
        return None

    @staticmethod
    def _doc_key(item_id: str) -> str:
        return hashlib.sha1(str(item_id).encode("utf-8")).hexdigest()

    @classmethod
    def _read_items_ref(cls, uid, company_id):
        db = cls._db()
        if not db:
            return None
        company_key = str(company_id or "_global")
        return (
            db.collection("users").document(uid)
            .collection(cls.COLLECTION).document(company_key)
            .collection("read_items")
        )

    @classmethod
    def get_read_item_ids(cls, uid, company_id) -> set:
        """Retorna el conjunto de item_id marcados como leídos por el usuario."""
        ref = cls._read_items_ref(uid, company_id)
        if not ref:
            return set()
        try:
            return {d.get("item_id") for d in ref.stream() if d.get("item_id")}
        except Exception as e:
            logger.warning(f"notification_state: error leyendo read_items: {e}")
            return set()

    @classmethod
    def mark_read(cls, uid, company_id, item_id) -> bool:
        ref = cls._read_items_ref(uid, company_id)
        if not ref:
            return False
        try:
            ref.document(cls._doc_key(item_id)).set({
                "item_id": item_id,
                "read_at": datetime.now(timezone.utc).isoformat(),
            })
            return True
        except Exception as e:
            logger.warning(f"notification_state: error marcando leído {item_id}: {e}")
            return False

    @classmethod
    def mark_unread(cls, uid, company_id, item_id) -> bool:
        ref = cls._read_items_ref(uid, company_id)
        if not ref:
            return False
        try:
            ref.document(cls._doc_key(item_id)).delete()
            return True
        except Exception as e:
            logger.warning(f"notification_state: error desmarcando {item_id}: {e}")
            return False


# ── Agregador ────────────────────────────────────────────────────────────────

class NotificationAggregator:
    """Normaliza y consolida las notificaciones de todas las fuentes."""

    # Cache TTL para los contadores fiscales (evita lecturas repetidas de Firestore).
    _fiscal_cache = {}

    @classmethod
    def _fiscal_counts_cached(cls, owner_uid, company_id):
        key = f"{owner_uid}:{company_id or ''}"
        now = time.time()
        hit = cls._fiscal_cache.get(key)
        if hit and now - hit[0] < 60:
            return hit[1]
        result = cls._compute_fiscal_counts(owner_uid, company_id)
        cls._fiscal_cache[key] = (now, result)
        return result

    @classmethod
    def _compute_fiscal_counts(cls, owner_uid, company_id):
        try:
            from app.services.tax_obligation_service import TaxObligationService
            statuses = TaxObligationService.get_status(owner_uid, company_id=company_id)
        except Exception as e:
            logger.warning(f"notification_center: error consultando obligaciones fiscales: {e}")
            return {"fiscal_overdue": 0, "fiscal_upcoming": 0}
        overdue = sum(1 for s in statuses if s["status"] == "overdue")
        upcoming = sum(1 for s in statuses if s["status"] in ("due_soon", "upcoming"))
        return {"fiscal_overdue": overdue, "fiscal_upcoming": upcoming}

    @classmethod
    def _mentions(cls, uid, sandbox):
        try:
            from app.services.db_service import DatabaseService
            return DatabaseService.get_user_notifications(uid, limit=50, sandbox=sandbox)
        except Exception:
            return []

    @classmethod
    def _commitments(cls, owner_uid, company_id, sandbox):
        try:
            from app.services.db_service import DatabaseService
            return DatabaseService.get_crm_contacts(owner_uid, sandbox=sandbox, company_id=company_id)
        except Exception:
            return []

    @classmethod
    def aggregate(cls, uid, owner_uid, company_id, sandbox=None):
        """
        Retorna (items, counters) para el centro de notificaciones.

        La autorización fiscal se valida en backend: si el usuario no tiene permiso
        no se consulta TaxObligationService ni se exponen datos fiscales.
        """
        fiscal_allowed = False
        try:
            from app.services.company_authorization import get_company_access
            access = get_company_access(uid, company_id) if (uid and company_id) else None
            fiscal_allowed = can_view_fiscal(access)
            if access is not None:
                owner_uid = access.owner_uid or owner_uid
        except Exception:
            access = None
            fiscal_allowed = False

        read_ids = NotificationStateService.get_read_item_ids(uid, company_id)

        items = []

        # ── Fuente: CRM menciones ──────────────────────────────────────────
        mentions_unread = 0
        for n in cls._mentions(uid, sandbox):
            is_read = bool(n.get("read", False))
            if not is_read:
                mentions_unread += 1
            items.append({
                "id": f"mention:{n.get('id') or n.get('documentNumber') or n.get('title', '')}",
                "type": "mention",
                "category": "crm",
                "filter_key": "mention",
                "title": n.get("title", "Mención"),
                "description": n.get("message") or n.get("body", ""),
                "severity": "info",
                "status": "read" if is_read else "unread",
                "is_read": is_read,
                "created_at": n.get("createdAt", ""),
                "due_date": None,
                "action_url": n.get("link") or n.get("documentUrl", ""),
                "action_label": "Ver",
                "source": "notifications",
            })

        # ── Fuente: CRM compromisos ────────────────────────────────────────
        commitments_pending = 0
        for c in cls._commitments(owner_uid, company_id, sandbox):
            item_id = f"commitment:{c.get('activityId') or c.get('id') or c.get('razonSocial', '')}"
            is_read = item_id in read_ids
            if not is_read:
                commitments_pending += 1
            overdue = bool(c.get("isOverdue", False))
            items.append({
                "id": item_id,
                "type": "commitment",
                "category": "crm",
                "filter_key": "commitment",
                "title": c.get("razonSocial", "Compromiso"),
                "description": c.get("crmNotes", ""),
                "severity": "warning" if overdue else "info",
                "status": "overdue" if overdue else "pending",
                "is_read": is_read,
                "created_at": "",
                "due_date": c.get("nextContactDate", ""),
                "action_url": "",
                "action_label": "",
                "source": "crm",
            })

        # ── Fuente: Fiscal (solo si el backend autoriza) ───────────────────
        fiscal_overdue = 0
        fiscal_upcoming = 0
        if fiscal_allowed:
            try:
                from app.services.tax_obligation_service import TaxObligationService
                statuses = TaxObligationService.get_status(owner_uid, company_id=company_id)
            except Exception as e:
                logger.warning(f"notification_center: error consultando obligaciones fiscales: {e}")
                statuses = []
            for s in statuses:
                if s["status"] not in ("overdue", "due_soon", "upcoming"):
                    continue
                period = s.get("period_key") or ""
                item_id = f"fiscal:{s['key']}:{period}" if period else f"fiscal:{s['key']}"
                is_read = item_id in read_ids
                if s["status"] == "overdue":
                    fiscal_overdue += 1
                    severity = "critical"
                elif s["status"] == "due_soon":
                    fiscal_upcoming += 1
                    severity = "warning"
                else:
                    fiscal_upcoming += 1
                    severity = "info"
                items.append({
                    "id": item_id,
                    "type": "tax_obligation",
                    "category": "fiscal",
                    "filter_key": "fiscal",
                    "title": s.get("label", s["key"]),
                    "description": s.get("description", ""),
                    "severity": severity,
                    "status": s["status"],
                    "is_read": is_read,
                    "created_at": "",
                    "due_date": s.get("next_due_date", ""),
                    "action_url": s.get("action_url") or "/accounting/tax-obligations",
                    "action_label": s.get("action_label") or "Ver obligación",
                    "source": "TaxObligationService",
                })
        else:
            fiscal_overdue = 0
            fiscal_upcoming = 0

        # ── Ordenar: crítico → por vencimiento → por fecha de creación ─────
        severity_rank = {"critical": 0, "warning": 1, "info": 2, "none": 3}
        items.sort(key=lambda i: (
            severity_rank.get(i["severity"], 3),
            i.get("due_date") or "9999-99-99",
            "" if i.get("created_at") else "9999",
        ))

        counters = {
            "mentions_unread": mentions_unread,
            "commitments_pending": commitments_pending,
            "fiscal_overdue": fiscal_overdue,
            "fiscal_upcoming": fiscal_upcoming,
            "total": mentions_unread + commitments_pending + fiscal_overdue + fiscal_upcoming,
            "fiscal_allowed": fiscal_allowed,
        }

        return items, counters

    @classmethod
    def get_badge_counts(cls, uid, company_id, sandbox=None):
        """
        Contadores para el badge de la campana (elementos que requieren atención).
        Cada categoría se cuenta con su propia regla, sin duplicar una misma obligación.
        """
        try:
            from app.services.company_authorization import get_company_access
            access = get_company_access(uid, company_id) if (uid and company_id) else None
        except Exception:
            access = None

        owner_uid = getattr(access, "owner_uid", "") if access else ""

        # menciones no leídas
        mentions_unread = 0
        for n in cls._mentions(uid, sandbox):
            if not n.get("read", False):
                mentions_unread += 1

        # compromisos pendientes de atender (no leídos)
        commitments_pending = 0
        read_ids = NotificationStateService.get_read_item_ids(uid, company_id)
        for c in cls._commitments(owner_uid, company_id, sandbox):
            item_id = f"commitment:{c.get('activityId') or c.get('id') or c.get('razonSocial', '')}"
            if item_id not in read_ids:
                commitments_pending += 1

        # fiscal (si autorizado), cacheado 60s
        if can_view_fiscal(access):
            fiscal = cls._fiscal_counts_cached(owner_uid, company_id)
            fiscal_overdue = fiscal["fiscal_overdue"]
            fiscal_upcoming = fiscal["fiscal_upcoming"]
        else:
            fiscal_overdue = 0
            fiscal_upcoming = 0

        return {
            "mentions_unread": mentions_unread,
            "commitments_pending": commitments_pending,
            "fiscal_overdue": fiscal_overdue,
            "fiscal_upcoming": fiscal_upcoming,
            "total": mentions_unread + commitments_pending + fiscal_overdue + fiscal_upcoming,
        }
