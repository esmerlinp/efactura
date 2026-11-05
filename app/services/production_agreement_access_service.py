"""Contrato de Producción — decisiones de acceso por contexto.

No centraliza la autorización en una única función: diferencia los cuatro
contextos de la especificación:

  - requires_company_agreement(company_id)
  - requires_user_acknowledgement(company_id, user_id)
  - requires_api_contract_access(company_id, credential)
  - requires_job_contract_access(company_id)

La evaluación se apoya en Firestore y en caché con invalidación. Nunca confía
en la sesión Flask para autorizar el acceso. Si Firestore no puede verificar
el estado contractual, el sistema falla de forma segura (bloqueando).
"""

from dataclasses import dataclass, field

from app.services.db_service import db_firestore, firebase_initialized
from app.services.production_agreement_service import ProductionAgreementService
from app.services.production_agreement_acceptance_service import (
    ProductionAgreementAcceptanceService,
)


@dataclass
class AccessDecision:
    allowed: bool = False
    reason: str = "unavailable"
    requires_company_agreement: bool = True
    requires_user_acknowledgement: bool = True
    is_owner: bool = False
    active_version_id: str = ""
    active_version: int = 0
    company_agreement_ok: bool = False
    user_acknowledged: bool = False


class ProductionAgreementAccessService:
    """Evalúa el cumplimiento contractual para cada contexto."""

    @classmethod
    def _available(cls) -> bool:
        return bool(firebase_initialized and db_firestore)

    @classmethod
    def _company_active(cls, company_id: str) -> bool:
        try:
            doc = db_firestore.collection("companies").document(company_id).get()
            if not doc.exists:
                return False
            status = doc.to_dict().get("status", "active")
            return status in ("active", "Activo", "")
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al leer compañía: {e}")
            return False

    @classmethod
    def _production_enabled(cls, company_id: str) -> bool:
        try:
            doc = db_firestore.collection("companies").document(company_id).get()
            if not doc.exists:
                return True
            return bool(doc.to_dict().get("production_enabled", True))
        except Exception:
            return True

    @classmethod
    def _is_owner(cls, company_id: str, user_id: str) -> bool:
        if not company_id or not user_id:
            return False
        try:
            doc = db_firestore.collection("companies").document(company_id).get()
            if not doc.exists:
                return False
            return doc.to_dict().get("owner_uid", "") == user_id
        except Exception:
            return False

    @classmethod
    def _active_membership(cls, company_id: str, user_id: str) -> bool:
        try:
            docs = db_firestore.collection("company_memberships") \
                .where(filter=_FieldFilter("uid", "==", user_id)) \
                .where(filter=_FieldFilter("company_id", "==", company_id)) \
                .where(filter=_FieldFilter("status", "==", "active")) \
                .limit(1) \
                .get()
            for _ in docs:
                return True
        except Exception:
            return False
        return False

    # ── Decisión empresarial ────────────────────────────────────────────────

    @classmethod
    def requires_company_agreement(cls, company_id: str, sandbox: bool = False) -> bool:
        """True si la compañía NO tiene aceptación empresarial vigente (bloquea)."""
        if not company_id:
            return True
        if not cls._available():
            return True
        if not cls._company_active(company_id):
            return False
        active = ProductionAgreementService.get_active_version()
        if not active:
            return False
        version_id = active.get("id", "")
        content_hash = active.get("contentHash", "")
        if not version_id:
            return False
        acceptance = ProductionAgreementAcceptanceService.get_company_acceptance(
            company_id, version_id, sandbox=sandbox
        )
        if not acceptance:
            return True
        return acceptance.get("contentHash", "") != content_hash

    # ── Decisión de reconocimiento individual ───────────────────────────────

    @classmethod
    def requires_user_acknowledgement(cls, company_id: str, user_id: str,
                                      sandbox: bool = False) -> bool:
        """True si el usuario NO tiene reconocimiento individual vigente (bloquea)."""
        if not company_id or not user_id:
            return True
        if not cls._available():
            return True
        if not cls._active_membership(company_id, user_id):
            return False
        active = ProductionAgreementService.get_active_version()
        if not active:
            return False
        version_id = active.get("id", "")
        content_hash = active.get("contentHash", "")
        if not version_id:
            return False
        ack = ProductionAgreementAcceptanceService.get_user_acknowledgement(
            company_id, user_id, version_id, sandbox=sandbox
        )
        if not ack:
            return True
        return ack.get("contentHash", "") != content_hash

    # ── Evaluación web (humano autenticado) ─────────────────────────────────

    @classmethod
    def evaluate_web_access(cls, company_id: str, user_id: str,
                            sandbox: bool = False) -> AccessDecision:
        if not company_id or not user_id:
            return AccessDecision(reason="missing_context")
        if not cls._available():
            return AccessDecision(reason="unavailable")

        active = ProductionAgreementService.get_active_version()
        active_id = active.get("id", "") if active else "__none__"

        try:
            from app.services.cache_service import CacheService
            from app.cache import cache as _cache
            cache_key = CacheService.domain_key(
                "production_agreement", company_id, bool(sandbox),
                "web_access", user_id, active_id,
            )
            cached = _cache.get(cache_key)
            if cached is not None:
                return cls._decision_from_dict(cached)
            decision = cls._evaluate_uncached(company_id, user_id, active, sandbox=sandbox)
            _cache.set(cache_key, cls._decision_to_dict(decision), timeout=30)
            return decision
        except Exception as e:
            print(f"⚠️ [ProductionAgreement] Error al cachear decisión: {e}")
            return cls._evaluate_uncached(company_id, user_id, active, sandbox=sandbox)

    @classmethod
    def _evaluate_uncached(cls, company_id: str, user_id: str, active,
                           sandbox: bool = False) -> AccessDecision:
        decision = AccessDecision()

        if not cls._company_active(company_id):
            decision.reason = "company_inactive"
            decision.allowed = False
            decision.requires_company_agreement = False
            decision.requires_user_acknowledgement = False
            return decision

        if not cls._active_membership(company_id, user_id):
            decision.reason = "no_active_membership"
            decision.allowed = False
            decision.requires_company_agreement = False
            decision.requires_user_acknowledgement = False
            return decision

        if not active:
            # Sin versión publicada aún: no hay exigencia contractual.
            decision.allowed = True
            decision.reason = "no_active_version"
            decision.requires_company_agreement = False
            decision.requires_user_acknowledgement = False
            return decision

        decision.active_version_id = active.get("id", "")
        try:
            decision.active_version = int(active.get("version", 0) or 0)
        except (TypeError, ValueError):
            decision.active_version = 0
        content_hash = active.get("contentHash", "")

        decision.is_owner = cls._is_owner(company_id, user_id)

        company_acceptance = ProductionAgreementAcceptanceService.get_company_acceptance(
            company_id, decision.active_version_id, sandbox=sandbox
        )
        decision.company_agreement_ok = bool(company_acceptance and company_acceptance.get("contentHash", "") == content_hash)

        ack = ProductionAgreementAcceptanceService.get_user_acknowledgement(
            company_id, user_id, decision.active_version_id, sandbox=sandbox
        )
        decision.user_acknowledged = bool(ack and ack.get("contentHash", "") == content_hash)

        decision.requires_company_agreement = not decision.company_agreement_ok
        decision.requires_user_acknowledgement = not decision.user_acknowledged

        if decision.requires_company_agreement:
            decision.allowed = False
            decision.reason = "company_agreement_required"
        elif decision.requires_user_acknowledgement:
            decision.allowed = False
            decision.reason = "user_acknowledgement_required"
        else:
            decision.allowed = True
            decision.reason = "ok"

        return decision

    @staticmethod
    def _decision_to_dict(decision: AccessDecision) -> dict:
        from dataclasses import asdict
        return asdict(decision)

    @staticmethod
    def _decision_from_dict(data: dict) -> AccessDecision:
        return AccessDecision(**data)

    # ── Contexto API ────────────────────────────────────────────────────────

    @classmethod
    def requires_api_contract_access(cls, company_id: str, credential: dict) -> bool:
        """Bloquea las APIs de producción mientras la credencial no tenga
        identidad contractual verificable generada por el servidor.

        Devuelve True (bloqueo) por defecto. El ``credential`` nunca es
        aceptado desde el navegador/consumidor como identidad humana.
        """
        if not company_id:
            return True
        # La identidad contractual verificable debe venir del servidor.
        # Mientras no exista, el acceso de producción queda bloqueado.
        return True

    # ── Contexto jobs ───────────────────────────────────────────────────────

    @classmethod
    def requires_job_contract_access(cls, company_id: str) -> bool:
        """Los procesos automáticos requieren aceptación empresarial vigente,
        pero no reconocimiento individual."""
        if not company_id:
            return True
        if not cls._available():
            return True
        if not cls._company_active(company_id):
            return False
        return cls.requires_company_agreement(company_id)

    @classmethod
    def requires_job_contract_access_for_owner(cls, owner_uid: str) -> bool:
        """Política de jobs resuelta desde un owner_uid legacy (bridge multi-empresa)."""
        if not owner_uid:
            return True
        from app.services.db_service import _resolve_company_id
        try:
            company_id = _resolve_company_id(owner_uid)
        except Exception:
            company_id = None
        if not company_id:
            return True
        return cls.requires_job_contract_access(company_id)


def _FieldFilter(field, op, value):
    try:
        from firebase_admin import firestore as _fstore
        return _fstore.FieldFilter(field, op, value)
    except Exception:
        return (field, op, value)
