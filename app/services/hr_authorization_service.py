"""HrAuthorizationService — Motor generico de autorizaciones para RRHH.

Cola de solicitudes con quorum N de M por docType. Sin regla configurada,
el creador se auto-aprueba (quorum 1), lo que tambien aplica a nomina
(sustituye la segregacion calculador≠aprobador cuando no hay regla).

Flujo de estados:
    pending → approved | rejected | returned → (resubmit) → pending
"""

import uuid
import logging
import time
from datetime import datetime, timezone

from app.services import hr_data_service as hr
from app.services.db_service import DatabaseService

logger = logging.getLogger(__name__)


AUTHORIZATION_DOC_TYPES = {
    "salary_change": "Cambio de Salario",
    "position_change": "Cambio de Puesto",
    "promotion": "Promoción",
    "supervisor_change": "Cambio de Supervisor",
    "absence": "Ausencia / Licencia",
    "termination": "Desvinculación",
    "payroll_approval": "Aprobación de Nómina",
    "payroll_post_accounting": "Contabilización de Nómina",
    "payroll_member_change": "Cambio de Miembro de Nómina",
}

REQUEST_STATUS_LABELS = {
    "pending": "Pendiente",
    "approved": "Aprobada",
    "rejected": "Rechazada",
    "returned": "Devuelta para correccion",
    "cancelled": "Cancelada",
}

STEP_STATUS_LABELS = {
    "pending": "Pendiente",
    "approved": "Aprobado",
    "rejected": "Rechazado",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


MAX_INLINE_HISTORY = 50


def _append_history(request: dict, entry: dict, request_id: str = "",
                    sandbox: bool = True):
    """Agrega una entrada al approvalHistory. Si excede MAX_INLINE_HISTORY,
    mueve las entradas antiguas a la subcoleccion history/ del documento."""
    history = request.get("approvalHistory", [])
    history.append(entry)
    if len(history) > MAX_INLINE_HISTORY and request_id:
        overflow = history[:-MAX_INLINE_HISTORY]
        request["approvalHistory"] = history[-MAX_INLINE_HISTORY:]
        _archive_history_events(request_id, overflow, sandbox)
    else:
        request["approvalHistory"] = history


def _archive_history_events(request_id: str, events: list, sandbox: bool = True):
    """Archiva entradas de historial a subcoleccion history/ del request."""
    try:
        from app.services.db_service import db_firestore, _company_coll
        if not db_firestore:
            return
        coll_name = "sandbox_hr_authorization_requests" if sandbox else "hr_authorization_requests"
        for i, event in enumerate(events):
            event_id = f"{event.get('at', _now())}_{i}"
            event["archived"] = True
            _company_coll(company_id=None, coll_name=coll_name) \
                .document(request_id).collection("history").document(event_id).set(event)
    except Exception as e:
        logger.warning("_archive_history_events failed for %s: %s", request_id, e)


def _normalise_approvers(approvers) -> list:
    """Normaliza la lista de aprobadores a [{id, name, email}]."""
    normalised = []
    for item in approvers or []:
        if isinstance(item, dict):
            uid = item.get("id") or item.get("uid") or item.get("approver_id")
            name = item.get("name") or item.get("approver_name") or uid
            email = item.get("email") or item.get("approver_email") or ""
        else:
            parts = str(item).split("|")
            uid = parts[0].strip() if parts else ""
            name = parts[1].strip() if len(parts) > 1 else uid
            email = parts[2].strip() if len(parts) > 2 else ""
        if uid:
            normalised.append({"id": uid, "name": name, "email": email})
    return normalised


def resolve_approvers(company_id: str, doc_type: str, sandbox: bool = True,
                      created_by_uid: str = "", created_by_email: str = "",
                      created_by_name: str = "", owner_uid: str = "") -> dict:
    """Resuelve aprobadores para un docType.

    Regla activa configurada -> sus aprobadores, quorum y asignado por defecto.
    Sin regla -> auto-aprobacion del creador (quorum 1).

    Si owner_uid esta presente, valida que los aprobadores existan como miembros
    activos del equipo.  Los aprobadores inactivos se excluyen silenciosamente
    con un warning.  Si TODOS los aprobadores son inactivos, la solicitud se
    bloquea (NO se auto-aprueba) y se retorna un warning.
    """
    rule_id = None
    min_approvals = 1
    approvers = []
    default_assignee = None

    for rule in hr.get_authorization_rules(company_id, sandbox=sandbox):
        if (rule.get("docType") == doc_type
                and rule.get("isActive", True)
                and rule.get("approvers")):
            rule_id = rule.get("id")
            min_approvals = int(rule.get("minApprovals") or 1)
            approvers = _normalise_approvers(rule.get("approvers"))
            da = rule.get("defaultAssignee")
            if da and da.get("id"):
                if any(a.get("id") == da["id"] for a in approvers):
                    default_assignee = {"id": da["id"], "name": da.get("name", ""), "email": da.get("email", "")}
            break

    if not approvers:
        creator_id = created_by_uid or created_by_email or ""
        approvers = [{
            "id": creator_id,
            "name": created_by_name or created_by_email or creator_id,
            "email": created_by_email or "",
        }]

    if rule_id and owner_uid:
        approvers = _filter_active_approvers(company_id, owner_uid, approvers, doc_type, rule_id)

    return {
        "approvers": approvers,
        "minApprovals": max(1, min_approvals),
        "ruleId": rule_id,
        "isFallback": not rule_id,
        "defaultAssignee": default_assignee or (approvers[0] if approvers else None),
    }


def _filter_active_approvers(company_id, owner_uid, approvers, doc_type, rule_id) -> list:
    """Filtra aprobadores inactivos. Si todos son inactivos, retorna lista vacia."""
    try:
        from app.services.db_service import DatabaseService
        team = DatabaseService.get_team_members(owner_uid, company_id=company_id)
        active_uids = {m.get("uid") for m in team if m.get("uid")}
    except Exception:
        return approvers

    valid = []
    stale = []
    for a in approvers:
        if a["id"] in active_uids:
            valid.append(a)
        else:
            stale.append(a)

    if stale:
        logger.warning("resolve_approvers: %d inactive approver(s) for docType=%s rule=%s: %s",
                       len(stale), doc_type, rule_id, [a["id"] for a in stale])

    if not valid:
        logger.error("resolve_approvers: ALL %d approvers inactive for docType=%s rule=%s. Blocking.",
                     len(stale), doc_type, rule_id)
        return approvers  # Mantener originales para referencia, se bloquea arriba

    return valid


def get_authorization_request(company_id: str, request_id: str, sandbox: bool = True) -> dict | None:
    return hr.get_authorization_request(company_id, request_id, sandbox=sandbox)


def get_authorization_metrics(company_id: str, sandbox: bool = True) -> dict:
    """Metricas basicas del motor de autorizaciones (ultimos 30 dias)."""
    from datetime import datetime, timezone, timedelta
    requests = get_authorization_requests(company_id, sandbox=sandbox)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=30)).isoformat()

    total = len(requests)
    pending = sum(1 for r in requests if r.get("status") == "pending")
    approved = sum(1 for r in requests if r.get("status") == "approved")
    rejected = sum(1 for r in requests if r.get("status") == "rejected")
    returned = sum(1 for r in requests if r.get("status") == "returned")
    cancelled = sum(1 for r in requests if r.get("status") == "cancelled")

    recent = [r for r in requests if (r.get("createdAt") or "") >= cutoff]
    recent_resolved = [r for r in recent if r.get("status") in ("approved", "rejected")]

    approval_times = []
    for r in recent:
        if r.get("approvedAt") and r.get("createdAt"):
            try:
                created = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
                approved_at = datetime.fromisoformat(r["approvedAt"].replace("Z", "+00:00"))
                approval_times.append((approved_at - created).total_seconds() / 3600)
            except (ValueError, TypeError):
                pass

    avg_hours = round(sum(approval_times) / len(approval_times), 1) if approval_times else None
    rejection_rate = round(rejected / len(recent_resolved) * 100, 1) if recent_resolved else None

    return {
        "total": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "returned": returned,
        "cancelled": cancelled,
        "recent_30d": len(recent),
        "avg_approval_hours": avg_hours,
        "rejection_rate_pct": rejection_rate,
    }


def get_authorization_requests(company_id: str, sandbox: bool = True,
                               status: str = "", user_uid: str = "") -> list:
    """Lista solicitudes. Opcional: filtrar por status o por aprobador (user_uid)."""
    requests = hr.get_authorization_requests(company_id, sandbox=sandbox)
    filtered = []
    for req in requests:
        if status and req.get("status") != status:
            continue
        if user_uid and not _user_has_pending_step(req, user_uid):
            continue
        filtered.append(req)
    filtered.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
    return filtered


def get_pending_for_user(company_id: str, user_uid: str, sandbox: bool = True) -> list:
    """Solicitudes pendientes donde user_uid tiene un paso por decidir."""
    pending = []
    for req in get_authorization_requests(company_id, sandbox=sandbox, status="pending"):
        if _user_has_pending_step(req, user_uid):
            pending.append(req)
    return pending


def _user_has_pending_step(request: dict, user_uid: str) -> bool:
    for step in request.get("approvalSteps", []):
        if step.get("status") == "pending":
            if step.get("id") == user_uid or step.get("email") == user_uid:
                return True
    return False


def _step_matches(step: dict, approver_id: str, approver_email: str = "") -> bool:
    """Un paso coincide si su id o email corresponde al aprobador."""
    if step.get("id") == approver_id or step.get("email") == approver_id:
        return True
    if approver_email and (step.get("id") == approver_email or step.get("email") == approver_email):
        return True
    return False


def _find_open_request(company_id: str, doc_type: str, doc_id: str,
                       sandbox: bool = True) -> dict | None:
    for req in get_authorization_requests(company_id, sandbox=sandbox):
        if (req.get("docType") == doc_type
                and req.get("documentId") == doc_id
                and req.get("status") in ("pending", "returned")):
            return req
    return None


def create_authorization_request(
    company_id: str,
    doc_type: str,
    doc_id: str,
    doc_number: str = "",
    entity_type: str = "",
    created_by_uid: str = "",
    created_by_email: str = "",
    created_by_name: str = "",
    sandbox: bool = True,
    metadata: dict | None = None,
    link: str = "",
    owner_uid: str = "",
) -> dict:
    """Crea una solicitud de autorizacion para una entidad.

    Sin regla activa -> se auto-aprueba con quorum 1 y aplica la decision.
    Con regla -> queda pending y notifica a los aprobadores.
    Si owner_uid esta presente, valida que los aprobadores esten activos
    en el equipo.
    Retorna {"request": ..., "approved": bool, "isFallback": bool}.
    """
    existing = _find_open_request(company_id, doc_type, doc_id, sandbox=sandbox)
    if existing:
        return {
            "request": existing,
            "approved": existing.get("status") == "approved",
            "isFallback": not existing.get("ruleId"),
        }

    resolved = resolve_approvers(
        company_id, doc_type, sandbox=sandbox,
        created_by_uid=created_by_uid, created_by_email=created_by_email,
        created_by_name=created_by_name, owner_uid=owner_uid,
    )

    request_id = str(uuid.uuid4())
    now = _now()
    approvers = resolved["approvers"]
    assigned = resolved.get("defaultAssignee") or (approvers[0] if approvers else {})
    assigned_to_default = {
        "id": assigned.get("id", ""),
        "name": assigned.get("name", ""),
        "email": assigned.get("email", ""),
    }
    approval_steps = [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "email": a.get("email"),
            "status": "pending",
            "decidedAt": None,
            "comment": "",
        }
        for a in approvers
    ]

    request = {
        "id": request_id,
        "docType": doc_type,
        "docTypeLabel": AUTHORIZATION_DOC_TYPES.get(doc_type, doc_type),
        "documentId": doc_id,
        "documentNumber": doc_number,
        "entityType": entity_type,
        "createdByUid": created_by_uid,
        "createdByEmail": created_by_email,
        "createdByName": created_by_name,
        "ruleId": resolved["ruleId"],
        "minApprovals": resolved["minApprovals"],
        "approvalSteps": approval_steps,
        "pendingApproverIds": [a.get("id") for a in approvers],
        "assignedTo": assigned_to_default,
        "ruleDefaultAssignee": assigned_to_default,
        "assigneeHistory": [],
        "status": "pending",
        "isFallback": resolved["isFallback"],
        "metadata": metadata or {},
        "link": link,
        "approvalHistory": [{
            "action": "created",
            "by": created_by_name or created_by_email or created_by_uid,
            "at": now,
            "comment": "",
        }],
        "createdAt": now,
        "updatedAt": now,
        "sandbox": bool(sandbox),
    }

    is_fallback = resolved["isFallback"]
    if is_fallback:
        step = request["approvalSteps"][0]
        step["status"] = "approved"
        step["decidedAt"] = now
        step["comment"] = "Auto-aprobacion: sin regla de autorizacion configurada"
        request["status"] = "approved"
        request["approvedAt"] = now
        request["approvedBy"] = step.get("name") or step.get("id")
        _append_history(request, {
            "action": "approved",
            "by": step.get("name") or step.get("id"),
            "at": now,
            "comment": step["comment"],
        }, request_id, sandbox)

    hr.save_authorization_request(company_id, request_id, request, sandbox=sandbox)

    _stamp_entity(company_id, entity_type, doc_id, request, sandbox=sandbox)

    if not is_fallback:
        for approver in approvers:
            _notify(
                approver.get("id") or approver.get("email"),
                "Nueva autorización pendiente",
                f"{request['docTypeLabel']} {doc_number} espera tu aprobación.",
                link,
                "authorization_pending",
                sandbox=sandbox,
                email=approver.get("email") or "",
            )
    else:
        _notify(
            request.get("createdByUid") or request.get("createdByEmail"),
            "Autorización completada",
            f"{request['docTypeLabel']} {doc_number} fue autorizada automáticamente (sin regla configurada).",
            link,
            "authorization_approved",
            sandbox=sandbox,
            email=request.get("createdByEmail") or "",
        )

    return {
        "request": request,
        "approved": request["status"] == "approved",
        "isFallback": is_fallback,
    }


def _decide_authorization_direct(company_id, request_id, approver_id, approved,
                                 comment, approver_name, sandbox,
                                 approver_email=""):
    """Version no-transaccional de decide_authorization (fallback sin Firestore)."""
    logger.info("_decide_authorization_direct: using fallback path for request=%s approver=%s", request_id, approver_id)
    request = hr.get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request:
        return {"success": False, "error": "Solicitud de autorizacion no encontrada"}
    if request.get("status") != "pending":
        return {"success": False, "error": "La solicitud ya fue resuelta o esta devuelta para correccion"}

    step = None
    for s in request.get("approvalSteps", []):
        if s.get("status") == "pending" and _step_matches(s, approver_id, approver_email):
            step = s
            break
    if not step:
        return {"success": False, "error": "No tienes una decision pendiente en esta solicitud"}

    now = _now()
    step["status"] = "approved" if approved else "rejected"
    step["decidedAt"] = now
    step["comment"] = comment or ("Aprobado" if approved else "Rechazado")
    if approver_name and not step.get("name"):
        step["name"] = approver_name

    min_approvals = max(1, int(request.get("minApprovals") or 1))
    approved_count = sum(1 for s in request["approvalSteps"] if s.get("status") == "approved")
    any_rejected = any(s.get("status") == "rejected" for s in request["approvalSteps"])

    new_status = request["status"]
    if any_rejected:
        new_status = "rejected"
        request["rejectedBy"] = step.get("name") or approver_id
        request["rejectedAt"] = now
    elif approved_count >= min_approvals:
        new_status = "approved"
        request["approvedBy"] = step.get("name") or approver_id
        request["approvedAt"] = now

    request["status"] = new_status
    request["updatedAt"] = now
    request["pendingApproverIds"] = [
        s["id"] for s in request["approvalSteps"] if s.get("status") == "pending"
    ]
    _append_history(request, {
        "action": new_status,
        "by": step.get("name") or approver_id,
        "at": now,
        "comment": step["comment"],
    }, request_id, sandbox)
    hr.save_authorization_request(company_id, request_id, request, sandbox=sandbox)

    if new_status in ("approved", "rejected"):
        _stamp_entity(company_id, request.get("entityType", ""), request.get("documentId", ""),
                      request, sandbox=sandbox)
        _notify(
            request.get("createdByUid") or request.get("createdByEmail"),
            "Autorizacion resuelta",
            f"{request['docTypeLabel']} {request.get('documentNumber', '')} "
            f"fue {REQUEST_STATUS_LABELS.get(new_status, new_status).lower()} "
            f"por {step.get('name') or approver_id}.",
            request.get("link", ""),
            f"authorization_{new_status}",
            sandbox=sandbox,
            email=request.get("createdByEmail") or "",
        )
    else:
        remaining = [s for s in request["approvalSteps"] if s.get("status") == "pending"]
        for s in remaining:
            _notify(
                s.get("id") or s.get("email"),
                "Autorizacion pendiente",
                f"{request['docTypeLabel']} {request.get('documentNumber', '')} espera tu aprobacion "
                f"({approved_count}/{min_approvals} aprobadas).",
                request.get("link", ""),
                "authorization_pending",
                sandbox=sandbox,
                email=s.get("email") or "",
            )

    return {"success": True, "status": new_status, "request": request}


def _decide_authorization_transactional(company_id, request_id, approver_id, approved,
                                        comment, approver_name, sandbox,
                                        db_firestore, _company_coll, coll_name,
                                        fallback_request=None, approver_email=""):
    """Version transaccional de decide_authorization con proteccion Firestore.

    Usa el patron @firestore.transactional + transaction.get(ref) que es la
    API correcta para transacciones Firestore (ver purchase_credit_note_service.py).
    _stamp_entity y notificaciones se ejecutan fuera de la transaccion.
    """
    from firebase_admin import firestore as fs

    logger.info("_decide_authorization_transactional: using transactional path for request=%s approver=%s", request_id, approver_id)

    doc_ref = _company_coll(company_id=company_id, coll_name=coll_name).document(request_id)

    snapshot = doc_ref.get()
    if not snapshot.exists:
        if fallback_request:
            return _decide_authorization_direct(company_id, request_id, approver_id, approved,
                                                comment, approver_name, sandbox,
                                                approver_email=approver_email)
        return {"success": False, "error": "Solicitud de autorizacion no encontrada"}

    @fs.transactional
    def _do_decide(transaction):
        snapshot = transaction.get(doc_ref)
        if not snapshot.exists:
            raise ValueError("Solicitud de autorizacion no encontrada")
        req = snapshot.to_dict()
        if req.get("status") != "pending":
            raise ValueError("La solicitud ya fue resuelta o esta devuelta para correccion")

        txn_step = None
        for s in req.get("approvalSteps", []):
            if s.get("status") == "pending" and _step_matches(s, approver_id, approver_email):
                txn_step = s
                break
        if not txn_step:
            raise ValueError("No tienes una decision pendiente en esta solicitud")

        now = _now()
        txn_step["status"] = "approved" if approved else "rejected"
        txn_step["decidedAt"] = now
        txn_step["comment"] = comment or ("Aprobado" if approved else "Rechazado")
        if approver_name and not txn_step.get("name"):
            txn_step["name"] = approver_name

        min_approvals = max(1, int(req.get("minApprovals") or 1))
        approved_count = sum(1 for s in req["approvalSteps"] if s.get("status") == "approved")
        any_rejected = any(s.get("status") == "rejected" for s in req["approvalSteps"])

        new_status = req["status"]
        if any_rejected:
            new_status = "rejected"
            req["rejectedBy"] = txn_step.get("name") or approver_id
            req["rejectedAt"] = now
        elif approved_count >= min_approvals:
            new_status = "approved"
            req["approvedBy"] = txn_step.get("name") or approver_id
            req["approvedAt"] = now

        req["status"] = new_status
        req["updatedAt"] = now
        req["pendingApproverIds"] = [
            s["id"] for s in req["approvalSteps"] if s.get("status") == "pending"
        ]
        history = req.get("approvalHistory", [])
        history.append({
            "action": new_status,
            "by": txn_step.get("name") or approver_id,
            "at": now,
            "comment": txn_step["comment"],
        })
        if len(history) > MAX_INLINE_HISTORY:
            history = history[-MAX_INLINE_HISTORY:]
        req["approvalHistory"] = history

        transaction.set(doc_ref, req)
        return req, new_status, approved_count, min_approvals, (txn_step.get("name") or approver_id)

    transaction = db_firestore.transaction()
    try:
        req, new_status, approved_count, min_approvals, step_name = _do_decide(transaction)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Authorization transaction FAILED %s approver=%s: %s",
                     request_id, approver_id, e)
        return {"success": False, "error": "Conflicto de concurrencia. Intenta de nuevo."}

    if new_status in ("approved", "rejected"):
        _stamp_entity(company_id, req.get("entityType", ""), req.get("documentId", ""),
                      req, sandbox=sandbox)
        _notify(
            req.get("createdByUid") or req.get("createdByEmail"),
            "Autorizacion resuelta",
            f"{req['docTypeLabel']} {req.get('documentNumber', '')} "
            f"fue {REQUEST_STATUS_LABELS.get(new_status, new_status).lower()} "
            f"por {step_name}.",
            req.get("link", ""),
            f"authorization_{new_status}",
            sandbox=sandbox,
            email=req.get("createdByEmail") or "",
        )
    else:
        remaining = [s for s in req["approvalSteps"] if s.get("status") == "pending"]
        for s in remaining:
            _notify(
                s.get("id") or s.get("email"),
                "Autorizacion pendiente",
                f"{req['docTypeLabel']} {req.get('documentNumber', '')} espera tu aprobacion "
                f"({approved_count}/{min_approvals} aprobadas).",
                req.get("link", ""),
                "authorization_pending",
                sandbox=sandbox,
                email=s.get("email") or "",
            )

    return {"success": True, "status": new_status, "request": req}


def decide_authorization(company_id: str, request_id: str, approver_id: str,
                         approved: bool, comment: str = "",
                         approver_name: str = "", sandbox: bool = True,
                         approver_email: str = "") -> dict:
    """Decide un paso pendiente. Evalua quorum N de M y aplica la decision final.

    La lectura y escritura de la solicitud se ejecuta dentro de una transaccion
    Firestore para evitar condiciones de carrera entre aprobadores simultaneos.
    _stamp_entity y las notificaciones se ejecutan fuera de la transaccion.
    """
    request = hr.get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request:
        logger.warning("decide_authorization: request %s not found via hr_data_service", request_id)
        return {"success": False, "error": "Solicitud de autorizacion no encontrada"}
    if request.get("status") != "pending":
        logger.warning("decide_authorization: request %s status=%s (not pending)", request_id, request.get("status"))
        return {"success": False, "error": "La solicitud ya fue resuelta o esta devuelta para correccion"}

    step = None
    for s in request.get("approvalSteps", []):
        if s.get("status") == "pending" and _step_matches(s, approver_id, approver_email):
            step = s
            break
    if not step:
        logger.warning(
            "decide_authorization: no matching pending step for approver_id=%r approver_email=%r. Steps: %s",
            approver_id, approver_email,
            [{"id": s.get("id"), "email": s.get("email"), "status": s.get("status")}
             for s in request.get("approvalSteps", [])],
        )
        return {"success": False, "error": "No tienes una decision pendiente en esta solicitud"}

    coll_name = "sandbox_hr_authorization_requests" if sandbox else "hr_authorization_requests"
    try:
        from app.services.db_service import db_firestore, _company_coll
        if db_firestore is not None:
            return _decide_authorization_transactional(
                company_id, request_id, approver_id, approved, comment,
                approver_name, sandbox, db_firestore, _company_coll, coll_name,
                fallback_request=request, approver_email=approver_email,
            )
    except (ImportError, AttributeError):
        pass
    return _decide_authorization_direct(company_id, request_id, approver_id, approved,
                                        comment, approver_name, sandbox,
                                        approver_email=approver_email)


def return_for_correction(company_id: str, request_id: str, approver_id: str,
                          comment: str, approver_name: str = "",
                          sandbox: bool = True) -> dict:
    """Devuelve la solicitud al creador para corrección (solo si está pendiente)."""
    if not comment or not comment.strip():
        return {"success": False, "error": "Debes proporcionar un motivo para la devolución"}

    request = hr.get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request:
        return {"success": False, "error": "Solicitud de autorización no encontrada"}
    if request.get("status") != "pending":
        return {"success": False, "error": "Solo se pueden devolver solicitudes pendientes"}

    step = None
    already_decided = False
    for s in request.get("approvalSteps", []):
        if s.get("id") == approver_id or s.get("email") == approver_id:
            step = s
            if s.get("status") != "pending":
                already_decided = True
            break
    if not step:
        return {"success": False, "error": "No eres aprobador de esta solicitud"}
    if already_decided:
        return {"success": False, "error": "Ya registraste tu decision en esta solicitud"}

    now = _now()
    step["status"] = "returned"
    step["decidedAt"] = now
    step["comment"] = comment.strip()
    if approver_name and not step.get("name"):
        step["name"] = approver_name

    request["status"] = "returned"
    request["updatedAt"] = now
    request["returnedBy"] = step.get("name") or approver_id
    request["returnedAt"] = now
    request["returnComment"] = comment.strip()
    _append_history(request, {
        "action": "returned",
        "by": step.get("name") or approver_id,
        "at": now,
        "comment": comment.strip(),
    }, request_id, sandbox)
    request["assignedTo"] = {
        "id": request.get("createdByUid", ""),
        "name": request.get("createdByName", ""),
        "email": request.get("createdByEmail", ""),
    }
    hr.save_authorization_request(company_id, request_id, request, sandbox=sandbox)

    _stamp_entity(company_id, request.get("entityType", ""), request.get("documentId", ""),
                  request, sandbox=sandbox)

    _notify(
        request.get("createdByUid") or request.get("createdByEmail"),
        "Solicitud devuelta para corrección",
        f"{request['docTypeLabel']} {request.get('documentNumber', '')} fue devuelta por "
        f"{step.get('name') or approver_id}. Motivo: {comment.strip()}",
        request.get("link", ""),
        "authorization_returned",
        sandbox=sandbox,
        email=request.get("createdByEmail") or "",
    )

    return {"success": True, "status": "returned", "request": request}


def resubmit_authorization(company_id: str, request_id: str,
                           resubmitted_by: str = "", sandbox: bool = True) -> dict:
    """Reenvía una solicitud devuelta. Resetea los pasos a pendiente."""
    request = hr.get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request:
        return {"success": False, "error": "Solicitud de autorización no encontrada"}
    if request.get("status") != "returned":
        return {"success": False, "error": "Solo se pueden reenviar solicitudes devueltas para corrección"}

    now = _now()
    for s in request.get("approvalSteps", []):
        if s.get("status") != "approved":
            s["status"] = "pending"
            s["decidedAt"] = None
            s["comment"] = ""

    approval_count = sum(1 for s in request["approvalSteps"] if s.get("status") == "approved")
    min_approvals = max(1, int(request.get("minApprovals") or 1))
    request["status"] = "approved" if approval_count >= min_approvals else "pending"
    request["updatedAt"] = now
    request["resubmittedAt"] = now
    _append_history(request, {
        "action": "resubmitted",
        "by": resubmitted_by or request.get("createdByEmail") or request.get("createdByName") or "Creador",
        "at": now,
        "comment": "Reenviada despues de correccion",
    }, request_id, sandbox)
    if request["status"] != "approved":
        request["assignedTo"] = request.get("ruleDefaultAssignee") or request["approvalSteps"][0]
    hr.save_authorization_request(company_id, request_id, request, sandbox=sandbox)

    for s in request["approvalSteps"]:
        if s.get("status") == "pending":
            _notify(
                s.get("id") or s.get("email"),
                "Autorización reenviada",
                f"{request['docTypeLabel']} {request.get('documentNumber', '')} fue corregida y reenviada. "
                f"Espera tu aprobación.",
                request.get("link", ""),
                "authorization_pending",
                sandbox=sandbox,
                email=s.get("email") or "",
            )
    if request["status"] == "approved":
        _stamp_entity(company_id, request.get("entityType", ""), request.get("documentId", ""),
                      request, sandbox=sandbox)

    return {"success": True, "status": "pending", "request": request}


def cancel_authorization(company_id: str, request_id: str, cancelled_by: str = "",
                         sandbox: bool = True) -> dict:
    """Cancela una solicitud pendiente y estampa la entidad origen."""
    request = hr.get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request:
        return {"success": False, "error": "Solicitud de autorización no encontrada"}
    if request.get("status") not in ("pending", "returned"):
        return {"success": False, "error": "Solo se pueden cancelar solicitudes pendientes"}

    now = _now()
    request["status"] = "cancelled"
    request["updatedAt"] = now
    request["cancelledBy"] = cancelled_by or request.get("createdByEmail") or "Sistema"
    request["cancelledAt"] = now
    _append_history(request, {
        "action": "cancelled",
        "by": cancelled_by or request.get("createdByEmail") or "Sistema",
        "at": now,
        "comment": "Solicitud cancelada",
    }, request_id, sandbox)
    hr.save_authorization_request(company_id, request_id, request, sandbox=sandbox)

    _stamp_entity(company_id, request.get("entityType", ""), request.get("documentId", ""),
                  request, sandbox=sandbox)

    return {"success": True, "status": "cancelled", "request": request}


def reassign_authorization(company_id: str, request_id: str, new_assignee_id: str,
                           reassigned_by: str = "", sandbox: bool = True) -> dict:
    """Reasigna la solicitud a otro aprobador del grupo o al creador."""
    request = hr.get_authorization_request(company_id, request_id, sandbox=sandbox)
    if not request:
        return {"success": False, "error": "Solicitud de autorización no encontrada"}

    new_assignee = None
    for s in request.get("approvalSteps", []):
        if s.get("id") == new_assignee_id or s.get("email") == new_assignee_id:
            new_assignee = {"id": s["id"], "name": s.get("name", ""), "email": s.get("email", "")}
            break

    if not new_assignee and new_assignee_id in (request.get("createdByUid"), request.get("createdByEmail")):
        new_assignee = {
            "id": request.get("createdByUid", ""),
            "name": request.get("createdByName", ""),
            "email": request.get("createdByEmail", ""),
        }

    if not new_assignee:
        return {"success": False, "error": "La persona seleccionada no pertenece al grupo de aprobadores ni es el creador"}

    old = request.get("assignedTo", {})
    request["assignedTo"] = new_assignee
    request.setdefault("assigneeHistory", []).append({
        "from": old.get("id"),
        "fromName": old.get("name"),
        "to": new_assignee_id,
        "toName": new_assignee.get("name"),
        "by": reassigned_by,
        "at": _now(),
    })
    request["updatedAt"] = _now()
    hr.save_authorization_request(company_id, request_id, request, sandbox=sandbox)

    _notify(
        new_assignee.get("id") or new_assignee.get("email"),
        "Solicitud asignada a ti",
        f"{request['docTypeLabel']} {request.get('documentNumber', '')} fue reasignada a ti por {reassigned_by}.",
        request.get("link", ""),
        "authorization_assigned",
        sandbox=sandbox,
        email=new_assignee.get("email") or "",
    )

    return {"success": True, "request": request}


# ═══════════════════════════════════════════════════════════════════════════
# Aplicación de la decisión sobre la entidad origen
# ═══════════════════════════════════════════════════════════════════════════

def _stamp_entity(company_id: str, entity_type: str, doc_id: str, request: dict,
                  sandbox: bool = True):
    """Estampa el estado de la autorizacion sobre la entidad y aplica transiciones.

    Esta funcion es la UNICA fuente de verdad para modificar una entidad como
    consecuencia de una decision de autorizacion.  Ninguna ruta o servicio
    externo debe modificar el estado de la entidad directamente como reaccion
    a una autorizacion.

    Transiciones por tipo de entidad
    --------------------------------
    mass_action:
      pending_approval + approved  → status=approved
      pending_approval + rejected  → status=rejected
      pending_approval + returned  → status=returned
      pending_approval + cancelled → status=draft (limpia auth fields)

    offboarding:
      pending_hr_approval / pending_supervisor_approval + rejected → rejected
      pending_hr_approval / pending_supervisor_approval + returned → returned

    payroll:
      approved  → apply_payroll_authorization (aprobada/contabilizada)
      rejected  → apply_payroll_authorization (rechazada, solo stage)
      returned  → apply_payroll_authorization (devuelta, solo stage)
      cancelled → solo estampa authorizationStatus=cancelled
    """
    if not entity_type or not doc_id:
        return
    status = request.get("status", "")
    approved = status == "approved"
    request_id = request.get("id", "")
    stamp = {
        "authorizationRequestId": request_id,
        "authorizationStatus": status,
        "authorizationComment": request.get("approvalHistory", [{}])[-1].get("comment", ""),
        "authorizationStampedAt": _now(),
    }
    if approved:
        stamp["authorizationApprovedBy"] = request.get("approvedBy", "")
        stamp["authorizationApprovedAt"] = request.get("approvedAt", "")
    if status == "rejected":
        stamp["authorizationRejectedBy"] = request.get("rejectedBy", "")
        stamp["authorizationRejectedAt"] = request.get("rejectedAt", "")

    import logging
    import time
    logger = logging.getLogger(__name__)
    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            entity = _load_entity(company_id, entity_type, doc_id, sandbox)
            if entity is None:
                return

            if _is_already_stamped(entity, request_id, status):
                return

            if entity_type == "mass_action":
                _stamp_mass_action(entity, doc_id, request, stamp, status, company_id, sandbox)
            elif entity_type == "offboarding":
                _stamp_offboarding(entity, doc_id, stamp, status, company_id, sandbox)
            elif entity_type == "payroll":
                _stamp_payroll(entity, doc_id, stamp, status, request, company_id, sandbox)
            return
        except Exception as e:
            if attempt < max_retries:
                logger.warning("_stamp_entity retry %d/%d for %s/%s status=%s",
                               attempt + 1, max_retries, entity_type, doc_id, status)
                time.sleep(0.3 * (attempt + 1))
            else:
                logger.error("_stamp_entity FAILED for %s/%s status=%s after %d attempts: %s",
                             entity_type, doc_id, status, max_retries + 1, e, exc_info=True)


def _load_entity(company_id, entity_type, doc_id, sandbox):
    if entity_type == "mass_action":
        return hr.get_mass_action(company_id, doc_id, sandbox=sandbox)
    elif entity_type == "offboarding":
        from app.services.offboarding_service import OffboardingService
        off_svc = OffboardingService(company_id, sandbox)
        return off_svc.get_request(doc_id)
    elif entity_type == "payroll":
        return hr.get_payroll_period(company_id, doc_id, sandbox=sandbox)
    return None


def _is_already_stamped(entity, request_id, status):
    return (
        entity.get("authorizationRequestId") == request_id
        and entity.get("authorizationStatus") == status
        and entity.get("authorizationStampedAt")
    )


def _stamp_mass_action(action, doc_id, request, stamp, status, company_id, sandbox):
    action = {**action, **stamp}
    if action.get("status") == "pending_approval" and status in ("approved", "rejected", "returned", "cancelled"):
        now = _now()
        prev_status = action["status"]
        if status == "cancelled":
            action["status"] = "draft"
            action["authorizationRequestId"] = ""
        elif status == "approved":
            action["status"] = "approved"
            action["approvedBy"] = stamp.get("authorizationApprovedBy", "")
            action["approvedAt"] = stamp.get("authorizationApprovedAt", "")
        elif status == "rejected":
            action["status"] = "rejected"
            action["rejectedBy"] = request.get("rejectedBy", "")
            action["rejectedAt"] = request.get("rejectedAt", "")
            action["rejectionReason"] = stamp.get("authorizationComment", "")
        elif status == "returned":
            action["status"] = "returned"
            action["returnedBy"] = request.get("returnedBy", "")
            action["returnedAt"] = request.get("returnedAt", "")
            action["returnComment"] = stamp.get("authorizationComment", "")
        action["statusHistory"] = action.get("statusHistory", []) + [{
            "from": prev_status,
            "to": action["status"],
            "by": (stamp.get("authorizationApprovedBy")
                   or request.get("returnedBy")
                   or request.get("cancelledBy")
                   or "Sistema"),
            "at": now,
            "comment": stamp.get("authorizationComment", ""),
        }]
    hr.save_mass_action(company_id, doc_id, action, sandbox=sandbox)


def _stamp_offboarding(off, doc_id, stamp, status, company_id, sandbox):
    from app.services.offboarding_service import OffboardingService
    off_svc = OffboardingService(company_id, sandbox)
    off_svc.save_request_raw(doc_id, {**off, **stamp},
                             user_email=stamp.get("authorizationApprovedBy", "Sistema"))
    off_status = off.get("status", "")
    if status == "rejected" and off_status in ("pending_hr_approval", "pending_supervisor_approval"):
        off_svc.transition(doc_id, "rejected", user_email="Sistema", user_role="owner",
                           comment=stamp.get("authorizationComment", "Rechazada en cola de autorizaciones"))
    elif status == "returned" and off_status in ("pending_hr_approval", "pending_supervisor_approval"):
        off_svc.transition(doc_id, "returned", user_email="Sistema", user_role="owner",
                           comment=stamp.get("authorizationComment", "Devuelta para correccion"))


def _stamp_payroll(period, doc_id, stamp, status, request, company_id, sandbox):
    from app.web.rrhh.payroll_workflow import apply_payroll_authorization
    to_status_map = {
        "approved": "aprobada" if request.get("docType") == "payroll_approval" else "contabilizada",
        "rejected": "rechazada",
        "returned": "devuelta",
    }
    to_status = to_status_map.get(status)
    if to_status:
        apply_payroll_authorization(
            company_id, doc_id, to_status,
            comment=stamp.get("authorizationComment", ""),
            owner_uid=stamp.get("authorizationApprovedBy", "Sistema"),
            sandbox=sandbox,
            skip_sod=bool(request.get("isFallback", False)),
        )
    else:
        hr.save_payroll_period(company_id, doc_id, {**period, **stamp}, sandbox=sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# Notificaciones (in-app + email)
# ═══════════════════════════════════════════════════════════════════════════

_EMAIL_BRAND = "#7c3aed"


def _email_body(title: str, message: str, link: str) -> str:
    cta = ""
    if link:
        cta = (f'<p style="margin:24px 0 0 0;">'
               f'<a href="{link}" style="background:{_EMAIL_BRAND}; color:#ffffff; text-decoration:none; '
               f'padding:12px 26px; border-radius:6px; font-weight:bold; display:inline-block;">'
               f'Ver solicitud</a></p>')
    return f"""
<html><body style="font-family:Arial,Helvetica,sans-serif; background:#f4f5f7; margin:0; padding:24px;">
  <div style="max-width:560px; margin:auto; background:#ffffff; border-radius:12px; overflow:hidden; border:1px solid #e5e7eb;">
    <div style="background:{_EMAIL_BRAND}; padding:18px 24px;">
      <h2 style="color:#ffffff; margin:0; font-size:18px;">{title}</h2>
    </div>
    <div style="padding:24px;">
      <p style="color:#334155; font-size:14px; line-height:1.6;">{message}</p>
      {cta}
      <p style="color:#94a3b8; font-size:12px; margin-top:28px;">
        Enviado automáticamente por el módulo de RRHH. No responda a este correo.
      </p>
    </div>
  </div>
</body></html>"""


def _send_email(to_email: str, title: str, message: str, link: str):
    if not to_email:
        return
    try:
        from flask import current_app
        from app.services.mailer import Mailer
        app = current_app._get_current_object()
        Mailer.send(
            app=app,
            to_email=to_email,
            subject=title,
            html_body=_email_body(title, message, link),
            category='notification',
        )
    except Exception as e:
        print(f"⚠️ HrAuthorizationService._send_email: {e}")


def _notify(user_uid: str, title: str, message: str, link: str, ntype: str,
            sandbox: bool = True, email: str = ""):
    if not user_uid and not email:
        return
    try:
        DatabaseService.create_user_notification(user_uid, {
            "title": title,
            "message": message,
            "type": ntype,
            "link": link,
            "sandbox": bool(sandbox),
        })
    except Exception as e:
        print(f"⚠️ HrAuthorizationService._notify: {e}")
    _send_email(email, title, message, link)
