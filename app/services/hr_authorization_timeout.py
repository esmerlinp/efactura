"""HrAuthorizationTimeoutService — Timeout, escalacion y purga de autorizaciones.

Ejecutado via APScheduler diariamente.  Configuracion por defecto:
  3 dias   → recordatorio a aprobadores pendientes
  7 dias   → escalacion al defaultAssignee de la regla
  14 dias  → escalacion al administrador (owner)
  90 dias  → purga de solicitudes cancelled

El rechazo automatico esta deshabilitado por defecto (requiere flag explícito).
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

DEFAULT_REMINDER_DAYS = 3
DEFAULT_ESCALATION_DAYS = 7
DEFAULT_ADMIN_ESCALATION_DAYS = 14
DEFAULT_PURGE_DAYS = 90


def _days_since(iso_str: str) -> int:
    if not iso_str:
        return 0
    try:
        created = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - created).days
    except (ValueError, TypeError):
        return 0


def process_authorization_timeouts(company_id: str, sandbox: bool = True,
                                    owner_uid: str = "",
                                    reminder_days: int = DEFAULT_REMINDER_DAYS,
                                    escalation_days: int = DEFAULT_ESCALATION_DAYS,
                                    admin_days: int = DEFAULT_ADMIN_ESCALATION_DAYS):
    """Procesa autorizaciones vencidas para una empresa."""
    from app.services.hr_authorization_service import (
        get_authorization_requests,
        get_authorization_request,
    )
    from app.services.hr_authorization_service import _notify

    requests = get_authorization_requests(company_id, sandbox=sandbox, status="pending")
    acted = 0

    for req in requests:
        request_id = req.get("id", "")
        created_at = req.get("createdAt", "")
        age = _days_since(created_at)
        if age < reminder_days:
            continue

        link = req.get("link", "")
        label = req.get("docTypeLabel", req.get("docType", "Solicitud"))
        doc_num = req.get("documentNumber", "")

        if age >= admin_days:
            _notify(
                owner_uid or req.get("createdByUid", ""),
                "Autorizacion vencida — escalada a administracion",
                f"{label} {doc_num} lleva {age} dias pendiente de aprobacion. "
                f"Se ha escalado a administracion para resolucion manual.",
                link, "authorization_escalated_admin",
                sandbox=sandbox,
                email=req.get("createdByEmail") or "",
            )
            acted += 1
        elif age >= escalation_days:
            assigned = req.get("assignedTo") or req.get("ruleDefaultAssignee") or {}
            _notify(
                assigned.get("id") or assigned.get("email", ""),
                "Autorizacion vencida — requiere tu atencion",
                f"{label} {doc_num} lleva {age} dias pendiente. "
                f"Por favor revisa y aprueba o rechaza la solicitud.",
                link, "authorization_escalated",
                sandbox=sandbox,
                email=assigned.get("email") or "",
            )
            acted += 1
        else:
            for step in req.get("approvalSteps", []):
                if step.get("status") == "pending":
                    _notify(
                        step.get("id") or step.get("email", ""),
                        "Recordatorio de autorizacion pendiente",
                        f"{label} {doc_num} espera tu aprobacion desde hace {age} dias.",
                        link, "authorization_reminder",
                        sandbox=sandbox,
                        email=step.get("email") or "",
                    )
            acted += 1

    if acted:
        logger.info("Authorization timeout: %d request(s) processed for company=%s sandbox=%s",
                    acted, company_id, sandbox)


def purge_cancelled_authorizations(company_id: str, sandbox: bool = True,
                                    purge_days: int = DEFAULT_PURGE_DAYS):
    """Elimina solicitudes cancelled con mas de purge_days dias de antiguedad."""
    from app.services import hr_data_service as hr

    requests = hr.get_authorization_requests(company_id, sandbox=sandbox)
    purged = 0

    for req in requests:
        if req.get("status") != "cancelled":
            continue
        age = _days_since(req.get("createdAt", ""))
        if age >= purge_days:
            try:
                hr.delete_authorization_request(company_id, req["id"], sandbox=sandbox)
                purged += 1
            except Exception as e:
                logger.warning("Failed to purge authorization %s: %s", req.get("id"), e)

    if purged:
        logger.info("Purged %d cancelled authorization(s) for company=%s sandbox=%s",
                    purged, company_id, sandbox)


def run_authorization_timeout_job(company_id=None):
    """Job diario: timeout y purga de autorizaciones para todos los owners."""
    from app.services.scheduler import _get_all_owner_uids

    owner_uids = _get_all_owner_uids(company_id=company_id)
    if not owner_uids:
        logger.info("Authorization timeout: no owners found.")
        return

    total_acted = 0
    total_purged = 0

    for owner_uid in owner_uids:
        for sandbox in (True, False):
            try:
                process_authorization_timeouts(
                    owner_uid, sandbox=sandbox, owner_uid=owner_uid,
                )
                total_acted += 1
            except Exception as e:
                logger.error("Authorization timeout error for %s sandbox=%s: %s",
                             owner_uid, sandbox, e)

            try:
                purge_cancelled_authorizations(owner_uid, sandbox=sandbox)
                total_purged += 1
            except Exception as e:
                logger.error("Authorization purge error for %s sandbox=%s: %s",
                             owner_uid, sandbox, e)

    logger.info("Authorization timeout job complete: %d owner(s) processed.", len(owner_uids))
