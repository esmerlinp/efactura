"""Servicios de CRM: oportunidades, actividades, pipeline y métricas comerciales."""

import uuid
from datetime import datetime, timedelta, timezone

from app.models.crm import (
    CRM_ACTIVITY_PRIORITIES,
    CRM_ACTIVITY_STATUSES,
    CRM_ACTIVITY_TYPES,
    CRM_OPPORTUNITY_STAGES,
    CRM_STAGE_PROBABILITY,
    VALID_OPPORTUNITY_TRANSITIONS,
    CONTACT_PIPELINE_MAP,
    LEAD_SCORE_WEIGHTS,
    CRMActivity,
    CRMOpportunity,
)
from app.services.contact_service import ContactService
from app.services.db_service import DatabaseService, db_firestore, firebase_initialized, serialize_field, _company_coll


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _date_key(value):
    if not value:
        return ""
    return str(value)[:10]


def _parse_date(value):
    value = _date_key(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _model_dump(model):
    if isinstance(model, dict):
        return model
    if hasattr(model, "model_dump"):
        try:
            dumped = model.model_dump()
            if isinstance(dumped, dict) and dumped:
                return dumped
        except Exception:
            pass
    if hasattr(model, "dict") and callable(model.dict):
        try:
            dumped = model.dict()
            if isinstance(dumped, dict) and dumped:
                return dumped
        except Exception:
            pass
    if hasattr(model, "__dict__"):
        return {k: v for k, v in model.__dict__.items() if not k.startswith("_")}
    return {}


def _opportunity_coll(sandbox):
    return "sandbox_crm_opportunities" if sandbox else "crm_opportunities"


def _activity_coll(sandbox):
    return "sandbox_crm_activities" if sandbox else "crm_activities"


def _normalize_stage(stage):
    stage = (stage or "Prospecto").strip()
    if stage == "En Negociación":
        stage = "Negociación"
    if stage not in CRM_OPPORTUNITY_STAGES:
        return "Prospecto"
    return stage


def _normalize_priority(priority):
    priority = (priority or "media").strip().lower()
    return priority if priority in CRM_ACTIVITY_PRIORITIES else "media"


def _normalize_activity_type(activity_type):
    activity_type = (activity_type or "Tarea").strip()
    return activity_type if activity_type in CRM_ACTIVITY_TYPES else "Tarea"


def _normalize_status(status):
    status = (status or "pendiente").strip().lower()
    return status if status in CRM_ACTIVITY_STATUSES else "pendiente"


def _require_company_id(company_id):
    if not company_id or not str(company_id).strip():
        raise ValueError("company_id es requerido para todas las operaciones de CRM.")
    return str(company_id).strip()


def _resolve_contact(owner_uid, contact_id, sandbox=True, company_id=None):
    if not contact_id:
        return None
    try:
        return ContactService.get_contact(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
    except Exception:
        return None


def _resolve_team_member_name(owner_uid, member_uid, company_id=None):
    if not member_uid:
        return ""
    try:
        members = DatabaseService.get_team_members(owner_uid, company_id=company_id) or []
        member = next((m for m in members if m.get("uid") == member_uid), None)
        if member:
            return member.get("name") or member.get("email", "")
    except Exception:
        pass
    return ""


CRM_ACTIVITY_SLA_DAYS = 3
CRM_STALE_OPPORTUNITY_DAYS = 7


def _annotate_activity(activity, today=None):
    if not isinstance(activity, dict):
        return activity
    due_date = _parse_date(activity.get("dueDate"))
    today = today or datetime.now(timezone.utc).date()
    status = activity.get("status", "pendiente")
    is_pending = status == "pendiente"
    activity["dueDate"] = _date_key(activity.get("dueDate"))
    activity["isOverdue"] = bool(is_pending and due_date and due_date < today)
    activity["isDueToday"] = bool(is_pending and due_date and due_date == today)
    activity["daysLate"] = (today - due_date).days if (activity["isOverdue"] and due_date) else 0

    # Clasificación SLA centralizada (F4.1)
    sla_info = CRMService.get_sla_status(activity.get("dueDate"), status=status, today_date=today)
    activity["slaStatus"] = sla_info["code"]
    activity["slaLabel"] = sla_info["label"]
    activity["slaBadgeClass"] = sla_info["badge_class"]
    activity["isUpcoming"] = sla_info["is_upcoming"]
    return activity


class CRMService:
    """Operaciones de alto nivel para el módulo CRM con aislamiento multiempresa estricto."""

    @classmethod
    def get_sla_status(cls, due_date, status="pendiente", today_str=None, today_date=None):
        """
        Clasifica el estado SLA de una fecha de compromiso o actividad (F4.1).
        Retorna dict con code ('vencida', 'hoy', 'proxima', 'normal', 'completada', 'cancelada', 'sin_fecha'),
        label legible, flags booleanos y clase CSS de badge.
        """
        status = _normalize_status(status)
        if status == "completada":
            return {
                "code": "completada",
                "label": "Completada",
                "is_overdue": False,
                "is_today": False,
                "is_upcoming": False,
                "days_diff": 0,
                "badge_class": "badge-success",
            }
        if status == "cancelada":
            return {
                "code": "cancelada",
                "label": "Cancelada",
                "is_overdue": False,
                "is_today": False,
                "is_upcoming": False,
                "days_diff": 0,
                "badge_class": "badge-secondary",
            }

        d = _parse_date(due_date)
        if not d:
            return {
                "code": "sin_fecha",
                "label": "Sin fecha",
                "is_overdue": False,
                "is_today": False,
                "is_upcoming": False,
                "days_diff": 0,
                "badge_class": "badge-light",
            }

        ref_today = today_date or (_parse_date(today_str) if today_str else datetime.now(timezone.utc).date())
        days_diff = (d - ref_today).days

        if days_diff < 0:
            days_abs = abs(days_diff)
            label = "Vencida ayer" if days_abs == 1 else f"Vencida hace {days_abs}d"
            return {
                "code": "vencida",
                "label": label,
                "is_overdue": True,
                "is_today": False,
                "is_upcoming": False,
                "days_diff": days_diff,
                "badge_class": "badge-danger",
            }
        elif days_diff == 0:
            return {
                "code": "hoy",
                "label": "Vence hoy",
                "is_overdue": False,
                "is_today": True,
                "is_upcoming": False,
                "days_diff": 0,
                "badge_class": "badge-warning",
            }
        elif 1 <= days_diff <= CRM_ACTIVITY_SLA_DAYS:
            label = "Vence mañana" if days_diff == 1 else f"En {days_diff} días"
            return {
                "code": "proxima",
                "label": label,
                "is_overdue": False,
                "is_today": False,
                "is_upcoming": True,
                "days_diff": days_diff,
                "badge_class": "badge-info",
            }
        else:
            return {
                "code": "normal",
                "label": f"En {days_diff}d",
                "is_overdue": False,
                "is_today": False,
                "is_upcoming": False,
                "days_diff": days_diff,
                "badge_class": "badge-light",
            }

    @classmethod
    def get_opportunity(cls, owner_uid, opportunity_id, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        if not firebase_initialized:
            return None
        try:
            doc = _company_coll(company_id=company_id, coll_name=_opportunity_coll(sandbox)).document(opportunity_id).get()
            if doc.exists:
                data = doc.to_dict() or {}
                if data.get("isDeleted", False):
                    return None
                data["id"] = doc.id
                data["companyId"] = data.get("companyId", company_id)
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                return cls._normalize_opportunity(data)
        except Exception as e:
            print(f"⚠️ Error al obtener oportunidad CRM {opportunity_id}: {e}")
        return None

    @classmethod
    def get_opportunities(cls, owner_uid, sandbox=True, company_id=None, include_closed=True, contact_id=None, branch_id=None, project_id=None):
        company_id = _require_company_id(company_id)
        opportunities = []
        if firebase_initialized:
            try:
                docs = _company_coll(company_id=company_id, coll_name=_opportunity_coll(sandbox)).get()
                for doc in docs:
                    data = doc.to_dict() or {}
                    if data.get("isDeleted", False):
                        continue
                    data["id"] = doc.id
                    data["companyId"] = data.get("companyId", company_id)
                    data["branchId"] = data.get("branchId", "default-sucursal-principal")
                    data["projectId"] = data.get("projectId")
                    opportunity = cls._normalize_opportunity(data)
                    if contact_id and opportunity.get("contactId") != contact_id:
                        continue
                    if not include_closed and opportunity.get("status") != "abierta":
                        continue
                    opportunities.append(opportunity)
            except Exception as e:
                print(f"⚠️ Error al obtener oportunidades CRM: {e}")

        opportunities.sort(key=lambda o: (
            o.get("status") != "abierta",
            _date_key(o.get("expectedCloseDate")) or "9999-12-31",
            o.get("contactName", "").lower(),
        ))
        if branch_id:
            opportunities = [o for o in opportunities if o.get("branchId") == branch_id]
        if project_id == '__no_project__':
            opportunities = [o for o in opportunities if not o.get("projectId")]
        elif project_id:
            opportunities = [o for o in opportunities if o.get("projectId") == project_id]
        return opportunities

    @classmethod
    def save_opportunity(cls, owner_uid, opportunity_id, opportunity_dict, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        opportunity_id = opportunity_id or opportunity_dict.get("id") or str(uuid.uuid4())
        existing = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id) or {}

        stage = _normalize_stage(opportunity_dict.get("stage") or existing.get("stage") or "Prospecto")
        status = "abierta"
        if stage == "Ganada":
            status = "ganada"
        elif stage == "Perdida":
            status = "perdida"

        probability = _safe_int(opportunity_dict.get("probability"), CRM_STAGE_PROBABILITY.get(stage, 10))
        if "probability" not in opportunity_dict or opportunity_dict.get("probability") in ("", None):
            probability = CRM_STAGE_PROBABILITY.get(stage, probability)

        contact_id = opportunity_dict.get("contactId") or existing.get("contactId", "")
        contact_name = opportunity_dict.get("contactName") or existing.get("contactName", "")
        contact = _resolve_contact(owner_uid, contact_id, sandbox=sandbox, company_id=company_id)
        if contact:
            contact_name = contact.get("razonSocial", contact_name)

        assigned_to = opportunity_dict.get("assignedTo") or existing.get("assignedTo", "")
        assigned_to_name = opportunity_dict.get("assignedToName") or _resolve_team_member_name(owner_uid, assigned_to, company_id=company_id)

        data = {
            **existing,
            **opportunity_dict,
            "id": opportunity_id,
            "ownerUID": owner_uid,
            "companyId": company_id,
            "branchId": opportunity_dict.get("branchId", existing.get("branchId", "default-sucursal-principal")),
            "projectId": opportunity_dict.get("projectId", existing.get("projectId")),
            "contactId": contact_id,
            "contactName": contact_name,
            "title": (opportunity_dict.get("title") or existing.get("title") or f"Oportunidad con {contact_name or 'prospecto'}").strip(),
            "stage": stage,
            "status": status,
            "amount": _safe_float(opportunity_dict.get("amount", existing.get("amount", 0.0))),
            "probability": max(0, min(100, probability)),
            "expectedCloseDate": _date_key(opportunity_dict.get("expectedCloseDate") or existing.get("expectedCloseDate")),
            "source": opportunity_dict.get("source") or existing.get("source") or "Manual",
            "assignedTo": assigned_to,
            "assignedToName": assigned_to_name,
            "quotationId": opportunity_dict.get("quotationId") or existing.get("quotationId", ""),
            "quotationNumber": opportunity_dict.get("quotationNumber") or existing.get("quotationNumber", ""),
            "invoiceId": opportunity_dict.get("invoiceId") or existing.get("invoiceId", ""),
            "invoiceNumber": opportunity_dict.get("invoiceNumber") or existing.get("invoiceNumber", ""),
            "invoices": opportunity_dict.get("invoices") or existing.get("invoices", []),
            "lostReason": opportunity_dict.get("lostReason") or existing.get("lostReason", ""),
            "notes": opportunity_dict.get("notes") or existing.get("notes", ""),
            "createdBy": opportunity_dict.get("createdBy") or existing.get("createdBy", ""),
            "createdAt": serialize_field(existing.get("createdAt") or opportunity_dict.get("createdAt") or _now_iso()),
            "updatedAt": serialize_field(opportunity_dict.get("updatedAt") or _now_iso()),
            "closedAt": existing.get("closedAt", ""),
        }

        if data["quotationId"] and not data["quotationNumber"]:
            try:
                quotation = DatabaseService.get_invoice(owner_uid, data["quotationId"], sandbox=sandbox, company_id=company_id)
                if quotation:
                    data["quotationNumber"] = quotation.get("invoiceNumber", "")
                    if data["amount"] <= 0:
                        data["amount"] = _safe_float(quotation.get("total") or quotation.get("netPayable"))
            except Exception:
                pass

        if data["invoiceId"] and not data["invoiceNumber"]:
            try:
                invoice = DatabaseService.get_invoice(owner_uid, data["invoiceId"], sandbox=sandbox, company_id=company_id)
                if invoice:
                    data["invoiceNumber"] = invoice.get("invoiceNumber", "")
                    if data["amount"] <= 0:
                        data["amount"] = _safe_float(invoice.get("total") or invoice.get("netPayable"))
            except Exception:
                pass

        if status in ("ganada", "perdida") and not data.get("closedAt"):
            data["closedAt"] = _now_iso()
        elif status == "abierta":
            data["closedAt"] = ""
            data["lostReason"] = ""

        data = cls._normalize_opportunity(data)

        if firebase_initialized:
            try:
                _company_coll(company_id=company_id, coll_name=_opportunity_coll(sandbox)).document(opportunity_id).set(data)
            except Exception as e:
                print(f"⚠️ Error al guardar oportunidad CRM: {e}")

        if contact_id:
            mapped_stage = CONTACT_PIPELINE_MAP.get(stage)
            if mapped_stage:
                try:
                    ContactService.update_pipeline(owner_uid=owner_uid, contact_id=contact_id, pipeline_stage=mapped_stage, sandbox=sandbox, company_id=company_id)
                except Exception:
                    pass

        return data

    @classmethod
    def transition_opportunity(
        cls,
        owner_uid,
        opportunity_id,
        target_stage,
        sandbox=True,
        company_id=None,
        user_name="Sistema",
        lost_reason="",
        invoice_id="",
        invoice_number="",
        total_amount=0.0,
        notes="",
    ):
        """
        Transiciona una oportunidad a una nueva etapa validando las reglas de la máquina de estados CRM-16.
        Garantiza sincronización con Contact.pipelineStage, registro de interacciones, validaciones de cierre
        y requerimiento estricto de lostReason para oportunidades Perdidas (CRM-09).
        """
        company_id = _require_company_id(company_id)
        opp = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
        if not opp:
            return False, "Oportunidad no encontrada.", None

        target_stage = _normalize_stage(target_stage)
        current_stage = opp.get("stage", "Prospecto")

        # Idempotencia: si ya está en la etapa solicitada
        if current_stage == target_stage:
            return True, f"La oportunidad ya se encuentra en la etapa {target_stage}.", opp

        # Validar transiciones permitidas según VALID_OPPORTUNITY_TRANSITIONS
        allowed = VALID_OPPORTUNITY_TRANSITIONS.get(current_stage, [])
        if target_stage not in allowed:
            return False, f"Transición no permitida de '{current_stage}' a '{target_stage}'.", None

        # Validaciones específicas por etapa:
        # 1. Prospecto -> Contactado: Requiere contacto asociado
        if current_stage == "Prospecto" and target_stage == "Contactado":
            if not opp.get("contactId"):
                return False, "Para avanzar a Contactado la oportunidad debe tener un contacto asignado.", None

        # 2. Contactado -> Calificado: Responsable comercial requerido
        if target_stage == "Calificado":
            if not opp.get("assignedTo") and not opp.get("assignedToName"):
                contact = _resolve_contact(owner_uid, opp.get("contactId"), sandbox=sandbox, company_id=company_id)
                if not (contact and contact.get("responsibleId")):
                    return False, "Se requiere un responsable comercial asignado para calificar la oportunidad.", None

        # 3. Calificado -> Propuesta: Requiere monto > 0 o cotización asociada
        if target_stage == "Propuesta":
            has_amount = _safe_float(opp.get("amount")) > 0 or _safe_float(total_amount) > 0
            has_quote = bool(opp.get("quotationId") or opp.get("quotationNumber"))
            if not (has_amount or has_quote):
                return False, "Para avanzar a Propuesta se requiere un monto estimado o una cotización asociada.", None

        # 4. Propuesta -> Negociación: Validar expectedCloseDate
        if target_stage == "Negociación":
            if not opp.get("expectedCloseDate"):
                opp["expectedCloseDate"] = (datetime.now(timezone.utc).date() + timedelta(days=30)).strftime("%Y-%m-%d")

        # 5. Ganada: Requiere trazabilidad o confirmación
        if target_stage == "Ganada":
            if invoice_id:
                opp["invoiceId"] = invoice_id
                opp["invoiceNumber"] = invoice_number or opp.get("invoiceNumber", "")
                invoices_list = opp.get("invoices") or []
                if not any(item.get("id") == invoice_id for item in invoices_list if isinstance(item, dict)):
                    invoices_list.append({
                        "id": invoice_id,
                        "number": invoice_number or "",
                        "amount": _safe_float(total_amount),
                        "linkedAt": _now_iso(),
                    })
                opp["invoices"] = invoices_list

        # 6. Perdida: lostReason obligatorio (CRM-09)
        if target_stage == "Perdida":
            reason = (lost_reason or opp.get("lostReason", "")).strip()
            if not reason:
                return False, "El motivo de pérdida (lostReason) es obligatorio para marcar la oportunidad como Perdida.", None
            opp["lostReason"] = reason

        # Manejo de Reapertura controlada (de Ganada/Perdida a etapa abierta)
        is_reopening = (current_stage in ("Ganada", "Perdida") and target_stage not in ("Ganada", "Perdida"))
        if is_reopening:
            opp["status"] = "abierta"
            opp["closedAt"] = ""
            if current_stage == "Perdida":
                opp["lostReason"] = ""

        # Actualizar datos de oportunidad
        opp["stage"] = target_stage
        if target_stage == "Ganada":
            opp["status"] = "ganada"
            opp["closedAt"] = opp.get("closedAt") or _now_iso()
            opp["probability"] = 100
        elif target_stage == "Perdida":
            opp["status"] = "perdida"
            opp["closedAt"] = opp.get("closedAt") or _now_iso()
            opp["probability"] = 0
        else:
            opp["status"] = "abierta"
            opp["probability"] = CRM_STAGE_PROBABILITY.get(target_stage, opp.get("probability", 10))

        if notes:
            opp["notes"] = f"{opp.get('notes', '')}\n[{_now_iso()[:10]} - {user_name}]: {notes}".strip()

        # Auditoría de cambio de etapa (CRM-17)
        history = list(opp.get("stageHistory") or [])
        history.append({
            "from": current_stage,
            "to": target_stage,
            "by": user_name or "Sistema",
            "timestamp": _now_iso(),
            "lostReason": opp.get("lostReason", ""),
            "notes": notes or "",
        })
        opp["stageHistory"] = history

        saved = cls.save_opportunity(owner_uid, opportunity_id, opp, sandbox=sandbox, company_id=company_id)

        # Registrar interacción en el contacto
        contact_id = opp.get("contactId")
        if contact_id:
            interaction_title = f"Transición CRM: {current_stage} ➔ {target_stage}"
            if is_reopening:
                interaction_title = f"Reapertura de Oportunidad: {target_stage}"
            content = f"Oportunidad '{opp.get('title')}'. Etapa anterior: {current_stage} ➔ Nueva etapa: {target_stage}."
            if target_stage == "Perdida":
                content += f" Motivo de pérdida: {opp.get('lostReason')}."
            elif target_stage == "Ganada" and opp.get("invoiceNumber"):
                content += f" Factura: {opp.get('invoiceNumber')}."
            if notes:
                content += f" Nota: {notes}."

            try:
                DatabaseService.save_client_interaction(owner_uid, contact_id, str(uuid.uuid4()), {
                    "type": "Seguimiento",
                    "title": interaction_title,
                    "content": content,
                    "date": _now_iso(),
                    "completed": True,
                    "createdBy": user_name or "Sistema CRM",
                }, sandbox=sandbox, company_id=company_id)
            except Exception:
                pass

        # Evaluación de automatizaciones CRM (Fase 4.2)
        try:
            from app.services.crm_automation_service import CRMAutomationService
            if target_stage == "Ganada":
                CRMAutomationService.evaluate_rules(
                    owner_uid=owner_uid,
                    event_type="opportunity_won",
                    payload={"opportunity": saved, "opportunity_id": opportunity_id, "to_stage": "Ganada", "invoice_id": invoice_id},
                    sandbox=sandbox,
                    company_id=company_id,
                )
            elif target_stage == "Perdida":
                CRMAutomationService.evaluate_rules(
                    owner_uid=owner_uid,
                    event_type="opportunity_lost",
                    payload={"opportunity": saved, "opportunity_id": opportunity_id, "to_stage": "Perdida", "lost_reason": opp.get("lostReason")},
                    sandbox=sandbox,
                    company_id=company_id,
                )

            CRMAutomationService.evaluate_rules(
                owner_uid=owner_uid,
                event_type="stage_change",
                payload={
                    "opportunity": saved,
                    "opportunity_id": opportunity_id,
                    "from_stage": current_stage,
                    "to_stage": target_stage,
                    "user_name": user_name,
                },
                sandbox=sandbox,
                company_id=company_id,
            )
        except Exception as auto_err:
            print(f"⚠️ Error al evaluar automatizaciones CRM para oportunidad {opportunity_id}: {auto_err}")

        return True, f"Oportunidad transicionada a {target_stage}.", saved

    @classmethod
    def delete_opportunity(cls, owner_uid, opportunity_id, sandbox=True, company_id=None, deleted_by=""):
        """Eliminación segura (Soft Delete CRM-08) y cancelación de actividades pendientes."""
        company_id = _require_company_id(company_id)
        opp = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
        if not opp:
            return False

        opp["isDeleted"] = True
        opp["deletedAt"] = _now_iso()
        opp["deletedBy"] = deleted_by or "Sistema"
        if firebase_initialized:
            try:
                _company_coll(company_id=company_id, coll_name=_opportunity_coll(sandbox)).document(opportunity_id).set(opp)
            except Exception as e:
                print(f"⚠️ Error al realizar soft delete de oportunidad CRM: {e}")
                return False

        # Cancelar actividades pendientes asociadas (no dejar huérfanos pendientes)
        activities = cls.get_activities(owner_uid, sandbox=sandbox, opportunity_id=opportunity_id, company_id=company_id, include_completed=True)
        for act in activities:
            if act.get("status") == "pendiente":
                act["status"] = "cancelada"
                cls.save_activity(owner_uid, act["id"], act, sandbox=sandbox, company_id=company_id)

        cls.invalidate_commitments_cache(company_id=company_id)
        return True

    @classmethod
    def close_opportunity(cls, owner_uid, opportunity_id, outcome, lost_reason="", invoice_id="", sandbox=True, company_id=None, user_name="Sistema"):
        target_stage = "Ganada" if outcome == "ganada" else "Perdida"
        ok, msg, _ = cls.transition_opportunity(
            owner_uid=owner_uid,
            opportunity_id=opportunity_id,
            target_stage=target_stage,
            sandbox=sandbox,
            company_id=company_id,
            user_name=user_name,
            lost_reason=lost_reason,
            invoice_id=invoice_id,
        )
        return ok, msg

    @classmethod
    def link_invoice_to_opportunity(
        cls,
        owner_uid,
        invoice_id,
        invoice_number="",
        opportunity_id=None,
        quotation_id=None,
        converted_from_quotation_id=None,
        sandbox=True,
        company_id=None,
        total_amount=0.0,
    ):
        """
        Vincula una factura emitida/cobrada a la oportunidad específica correspondiente.
        Si la factura no cuenta con opportunityId ni quotationId, no altera ninguna oportunidad.
        Registra la factura en el historial `invoices` de la oportunidad para soportar múltiples facturas.
        """
        company_id = _require_company_id(company_id)
        if not invoice_id:
            return 0

        target_opportunities = []
        if opportunity_id:
            opp = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
            if opp:
                target_opportunities.append(opp)
        elif quotation_id or converted_from_quotation_id:
            qid = quotation_id or converted_from_quotation_id
            all_opps = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, include_closed=True)
            for opp in all_opps:
                if opp.get("quotationId") == qid or (opp.get("quotationNumber") and opp.get("quotationNumber") == qid):
                    target_opportunities.append(opp)

        if not target_opportunities:
            return 0

        updated_count = 0
        for opp in target_opportunities:
            opp["stage"] = "Ganada"
            opp["status"] = "ganada"
            opp["invoiceId"] = invoice_id
            opp["invoiceNumber"] = invoice_number or opp.get("invoiceNumber", "")
            if not opp.get("closedAt"):
                opp["closedAt"] = _now_iso()

            invoices_list = opp.get("invoices") or []
            if not isinstance(invoices_list, list):
                invoices_list = []

            existing_entry = next((item for item in invoices_list if isinstance(item, dict) and item.get("id") == invoice_id), None)
            is_new_link = (existing_entry is None)
            if is_new_link:
                invoices_list.append({
                    "id": invoice_id,
                    "number": invoice_number or "",
                    "amount": _safe_float(total_amount),
                    "linkedAt": _now_iso(),
                })
            else:
                if invoice_number and not existing_entry.get("number"):
                    existing_entry["number"] = invoice_number
                if total_amount and not existing_entry.get("amount"):
                    existing_entry["amount"] = _safe_float(total_amount)
            opp["invoices"] = invoices_list

            saved = cls.save_opportunity(owner_uid, opp["id"], opp, sandbox=sandbox, company_id=company_id)
            if is_new_link:
                cls._record_opportunity_interaction(owner_uid, saved, sandbox=sandbox, company_id=company_id)
            updated_count += 1

        return updated_count

    @classmethod
    def link_quotation_to_opportunity(
        cls,
        owner_uid,
        quotation_id,
        quotation_number="",
        opportunity_id=None,
        amount=0.0,
        sandbox=True,
        company_id=None,
    ):
        """Sincroniza cotización creada o actualizada con la oportunidad correspondiente (CRM-18)."""
        company_id = _require_company_id(company_id)
        if not quotation_id:
            return None

        target_opps = []
        if opportunity_id:
            opp = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
            if opp:
                target_opps.append((opportunity_id, opp))
        else:
            all_opps = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id)
            for opp in all_opps:
                if opp.get("quotationId") == quotation_id:
                    target_opps.append((opp.get("id"), opp))

        saved_opps = []
        for opp_id, opp in target_opps:
            opp["quotationId"] = quotation_id
            if quotation_number:
                opp["quotationNumber"] = quotation_number
            if amount is not None and amount > 0:
                opp["amount"] = _safe_float(amount)
            saved = cls.save_opportunity(owner_uid, opp_id, opp, sandbox=sandbox, company_id=company_id)
            saved_opps.append(saved)

        return saved_opps[0] if saved_opps else None

    @classmethod
    def mark_contact_opportunities_won(cls, owner_uid, contact_id, invoice_id="", invoice_number="", sandbox=True, company_id=None):
        """DEPRECATED: Usar link_invoice_to_opportunity en su lugar."""
        return 0

    @classmethod
    def get_activity(cls, owner_uid, activity_id, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        if not firebase_initialized:
            return None
        try:
            doc = _company_coll(company_id=company_id, coll_name=_activity_coll(sandbox)).document(activity_id).get()
            if doc.exists:
                data = doc.to_dict() or {}
                if data.get("isDeleted", False):
                    return None
                data["id"] = doc.id
                data["companyId"] = data.get("companyId", company_id)
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                return _annotate_activity(cls._normalize_activity(data))
        except Exception as e:
            print(f"⚠️ Error al obtener actividad CRM {activity_id}: {e}")
        return None

    @classmethod
    def get_activities(cls, owner_uid, sandbox=True, include_completed=True, contact_id=None, opportunity_id=None, branch_id=None, project_id=None, company_id=None):
        company_id = _require_company_id(company_id)
        activities = []
        if firebase_initialized:
            try:
                docs = _company_coll(company_id=company_id, coll_name=_activity_coll(sandbox)).get()
                for doc in docs:
                    data = doc.to_dict() or {}
                    if data.get("isDeleted", False):
                        continue
                    data["id"] = doc.id
                    data["companyId"] = data.get("companyId", company_id)
                    data["branchId"] = data.get("branchId", "default-sucursal-principal")
                    data["projectId"] = data.get("projectId")
                    activity = _annotate_activity(cls._normalize_activity(data))
                    if contact_id and activity.get("contactId") != contact_id:
                        continue
                    if opportunity_id and activity.get("opportunityId") != opportunity_id:
                        continue
                    if not include_completed and activity.get("status") != "pendiente":
                        continue
                    activities.append(activity)
            except Exception as e:
                print(f"⚠️ Error al obtener actividades CRM: {e}")

        activities.sort(key=lambda a: (
            a.get("status") != "pendiente",
            not a.get("isOverdue"),
            _date_key(a.get("dueDate")) or "9999-12-31",
            a.get("priority", "media"),
        ))
        if branch_id:
            activities = [a for a in activities if a.get("branchId") == branch_id]
        if project_id == '__no_project__':
            activities = [a for a in activities if not a.get("projectId")]
        elif project_id:
            activities = [a for a in activities if a.get("projectId") == project_id]
        return activities

    @classmethod
    def save_activity(cls, owner_uid, activity_id, activity_dict, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        activity_id = activity_id or activity_dict.get("id") or str(uuid.uuid4())
        existing = cls.get_activity(owner_uid, activity_id, sandbox=sandbox, company_id=company_id) or {}

        contact_id = activity_dict.get("contactId") or existing.get("contactId", "")
        contact_name = activity_dict.get("contactName") or existing.get("contactName", "")
        contact = _resolve_contact(owner_uid, contact_id, sandbox=sandbox, company_id=company_id)
        if contact:
            contact_name = contact.get("razonSocial", contact_name)

        opportunity_id = activity_dict.get("opportunityId") or existing.get("opportunityId", "")
        opportunity_title = activity_dict.get("opportunityTitle") or existing.get("opportunityTitle", "")
        if opportunity_id:
            opportunity = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
            if opportunity:
                opportunity_title = opportunity.get("title", opportunity_title)
                if not contact_id:
                    contact_id = opportunity.get("contactId", "")
                    contact_name = opportunity.get("contactName", "")

        assigned_to = activity_dict.get("assignedTo") or existing.get("assignedTo", "")
        assigned_to_name = activity_dict.get("assignedToName") or _resolve_team_member_name(owner_uid, assigned_to, company_id=company_id)
        activity_type = _normalize_activity_type(activity_dict.get("type") or existing.get("type"))
        title = (activity_dict.get("title") or existing.get("title") or activity_type).strip()

        data = {
            **existing,
            **activity_dict,
            "id": activity_id,
            "ownerUID": owner_uid,
            "companyId": company_id,
            "branchId": activity_dict.get("branchId", existing.get("branchId", "default-sucursal-principal")),
            "projectId": activity_dict.get("projectId", existing.get("projectId")),
            "contactId": contact_id,
            "contactName": contact_name,
            "opportunityId": opportunity_id,
            "opportunityTitle": opportunity_title,
            "type": activity_type,
            "title": title,
            "description": activity_dict.get("description") or existing.get("description", ""),
            "dueDate": _date_key(activity_dict.get("dueDate") or existing.get("dueDate")),
            "priority": _normalize_priority(activity_dict.get("priority") or existing.get("priority")),
            "status": _normalize_status(activity_dict.get("status") or existing.get("status")),
            "assignedTo": assigned_to,
            "assignedToName": assigned_to_name,
            "completedAt": activity_dict.get("completedAt") or existing.get("completedAt", ""),
            "createdBy": activity_dict.get("createdBy") or existing.get("createdBy", ""),
            "createdAt": serialize_field(existing.get("createdAt") or activity_dict.get("createdAt") or _now_iso()),
            "updatedAt": _now_iso(),
        }
        data = cls._normalize_activity(data)

        if firebase_initialized:
            try:
                _company_coll(company_id=company_id, coll_name=_activity_coll(sandbox)).document(activity_id).set(data)
            except Exception as e:
                print(f"⚠️ Error al guardar actividad CRM: {e}")

        cls._sync_activity_to_contact(owner_uid, data, sandbox=sandbox, company_id=company_id)
        cls.invalidate_commitments_cache(company_id=company_id)
        return _annotate_activity(data)

    @classmethod
    def complete_activity(cls, owner_uid, activity_id, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        activity = cls.get_activity(owner_uid, activity_id, sandbox=sandbox, company_id=company_id)
        if not activity:
            return False, "Actividad no encontrada."
        activity["status"] = "completada"
        activity["completedAt"] = _now_iso()
        cls.save_activity(owner_uid, activity_id, activity, sandbox=sandbox, company_id=company_id)

        contact_id = activity.get("contactId")
        if contact_id:
            try:
                contact = ContactService.get_contact(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
                if contact and _date_key(contact.get("nextContactDate")) == _date_key(activity.get("dueDate")):
                    contact["nextContactDate"] = ""
                    ContactService.save_contact(owner_uid=owner_uid, contact_id=contact_id, contact_dict=contact, sandbox=sandbox, company_id=company_id)
            except Exception:
                pass

        cls.invalidate_commitments_cache(company_id=company_id)
        return True, "Actividad completada."

    @classmethod
    def delete_activity(cls, owner_uid, activity_id, sandbox=True, company_id=None, deleted_by=""):
        """Eliminación segura de actividades (CRM-08): preserva completadas, soft delete para pendientes."""
        company_id = _require_company_id(company_id)
        activity = cls.get_activity(owner_uid, activity_id, sandbox=sandbox, company_id=company_id)
        if not activity:
            return False

        activity["isDeleted"] = True
        activity["deletedAt"] = _now_iso()
        activity["deletedBy"] = deleted_by or "Sistema"

        if firebase_initialized:
            try:
                _company_coll(company_id=company_id, coll_name=_activity_coll(sandbox)).document(activity_id).set(activity)
            except Exception as e:
                print(f"⚠️ Error al eliminar actividad CRM: {e}")
                return False

        if activity.get("contactId") and activity.get("status") != "completada":
            try:
                DatabaseService.delete_client_interaction(owner_uid, activity["contactId"], activity_id, sandbox=sandbox, company_id=company_id)
            except Exception:
                pass

        cls.invalidate_commitments_cache(company_id=company_id)
        return True

    @classmethod
    def get_stale_opportunities(
        cls,
        owner_uid,
        sandbox=True,
        company_id=None,
        threshold_days=CRM_STALE_OPPORTUNITY_DAYS,
        branch_id=None,
        project_id=None,
        today_str=None,
    ):
        """
        Detecta oportunidades abiertas sin actividad comercial relevante durante threshold_days (F4.1).
        No incluye oportunidades Ganadas, Perdidas ni eliminadas (soft-deleted).
        Retorna lista de oportunidades enriquecidas con isStale, staleReason y días sin actividad.
        """
        company_id = _require_company_id(company_id)
        open_opps = cls.get_opportunities(
            owner_uid,
            sandbox=sandbox,
            company_id=company_id,
            include_closed=False,
            branch_id=branch_id,
            project_id=project_id,
        )

        all_activities = cls.get_activities(
            owner_uid,
            sandbox=sandbox,
            company_id=company_id,
            include_completed=True,
            branch_id=branch_id,
            project_id=project_id,
        )

        activities_by_opp = {}
        for act in all_activities:
            op_id = act.get("opportunityId")
            if op_id:
                activities_by_opp.setdefault(op_id, []).append(act)

        ref_today = _parse_date(today_str) if today_str else datetime.now(timezone.utc).date()
        stale_list = []

        for opp in open_opps:
            if opp.get("isDeleted") or opp.get("status") in ("ganada", "perdida") or opp.get("stage") in ("Ganada", "Perdida"):
                continue

            opp_id = opp["id"]
            opp_activities = activities_by_opp.get(opp_id, [])

            # 1. Verificar si tiene actividades pendientes vencidas
            has_overdue_activity = any(
                act.get("status") == "pendiente" and _parse_date(act.get("dueDate")) and _parse_date(act.get("dueDate")) < ref_today
                for act in opp_activities
            )

            # 2. Determinar la fecha de última actividad relevante
            activity_dates = []
            for act in opp_activities:
                for fld in ("completedAt", "updatedAt", "createdAt", "dueDate"):
                    d_parsed = _parse_date(act.get(fld))
                    if d_parsed:
                        activity_dates.append(d_parsed)

            stage_entry_date = None
            stage_hist = opp.get("stageHistory") or []
            if stage_hist:
                last_hist = stage_hist[-1]
                stage_entry_date = _parse_date(last_hist.get("timestamp"))

            opp_crt = _parse_date(opp.get("createdAt"))
            opp_upd = _parse_date(opp.get("updatedAt"))

            # Determinar fecha base comercial
            commercial_dates = [d for d in activity_dates if d is not None]
            if commercial_dates:
                last_activity_date = max(commercial_dates)
            elif stage_entry_date:
                last_activity_date = stage_entry_date
            elif opp_upd:
                last_activity_date = opp_upd
            elif opp_crt:
                last_activity_date = opp_crt
            else:
                last_activity_date = ref_today

            days_inactive = (ref_today - last_activity_date).days

            is_stale = False
            stale_reason = ""
            stale_detail = ""

            if has_overdue_activity:
                is_stale = True
                stale_reason = "overdue_activity"
                stale_detail = "Tiene actividades de seguimiento vencidas"
            elif days_inactive >= threshold_days:
                if stage_entry_date and (ref_today - stage_entry_date).days >= threshold_days:
                    is_stale = True
                    stale_reason = "stuck_in_stage"
                    stale_detail = f"Sin avance en la etapa '{opp.get('stage')}' durante {days_inactive} días"
                else:
                    is_stale = True
                    stale_reason = "no_activity"
                    stale_detail = f"Sin actividad comercial registrada durante {days_inactive} días"

            if is_stale:
                opp_copy = dict(opp)
                opp_copy["isStale"] = True
                opp_copy["staleReason"] = stale_reason
                opp_copy["staleDetail"] = stale_detail
                opp_copy["daysSinceLastActivity"] = max(0, days_inactive)
                opp_copy["lastActivityDate"] = last_activity_date.isoformat()
                stale_list.append(opp_copy)

        return stale_list

    @classmethod
    def compute_next_contact_date(cls, owner_uid, opportunity_id, sandbox=True, company_id=None, today_str=None):
        """Calcula la próxima fecha de contacto para una oportunidad basada en la actividad pendiente más cercana."""
        company_id = _require_company_id(company_id)
        opp = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox, company_id=company_id)
        if not opp or opp.get("isDeleted"):
            return ""

        ref_today = _parse_date(today_str) if today_str else datetime.now(timezone.utc).date()
        activities = cls.get_activities(owner_uid, sandbox=sandbox, company_id=company_id, include_completed=False)
        opp_acts = [a for a in activities if a.get("opportunityId") == opportunity_id and a.get("status") == "pendiente" and not a.get("isDeleted")]

        future_dates = []
        for a in opp_acts:
            d = _parse_date(a.get("dueDate"))
            if d and d >= ref_today:
                future_dates.append(d)

        if future_dates:
            earliest = min(future_dates)
            return earliest.isoformat()

        return _date_key(opp.get("nextContactDate"))

    @classmethod
    def get_pipeline(cls, owner_uid, sandbox=True, company_id=None, branch_id=None, project_id=None):
        company_id = _require_company_id(company_id)
        opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, include_closed=True, branch_id=branch_id, project_id=project_id)
        stale_opps = {o["id"]: o for o in cls.get_stale_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)}

        grouped = []
        for stage in CRM_OPPORTUNITY_STAGES:
            stage_items = []
            for o in opportunities:
                if o.get("stage") == stage:
                    item = dict(o)
                    if o.get("id") in stale_opps:
                        stale_data = stale_opps[o["id"]]
                        item["isStale"] = True
                        item["staleReason"] = stale_data.get("staleReason")
                        item["staleDetail"] = stale_data.get("staleDetail")
                        item["daysSinceLastActivity"] = stale_data.get("daysSinceLastActivity", 0)
                    else:
                        item["isStale"] = False
                    stage_items.append(item)

            amount = sum(_safe_float(o.get("amount")) for o in stage_items)
            weighted = sum(_safe_float(o.get("amount")) * (_safe_float(o.get("probability")) / 100.0) for o in stage_items)
            grouped.append({
                "stage": stage,
                "probability": CRM_STAGE_PROBABILITY.get(stage, 0),
                "opportunities": stage_items,
                "count": len(stage_items),
                "amount": round(amount, 2),
                "weighted": round(weighted, 2),
            })
        return grouped

    @classmethod
    def get_leads(cls, owner_uid, sandbox=True, company_id=None, branch_id=None, project_id=None):
        company_id = _require_company_id(company_id)
        contacts = [c for c in ContactService.get_contacts(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id) if "cliente" in c.get("types", [])]
        if branch_id:
            contacts = [c for c in contacts if c.get("branchId") == branch_id]
        if project_id == '__no_project__':
            contacts = [c for c in contacts if not c.get("projectId")]
        elif project_id:
            contacts = [c for c in contacts if c.get("projectId") == project_id]

        quotations = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=True, company_id=company_id, branch_id=branch_id, project_id=project_id)
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False, company_id=company_id, branch_id=branch_id, project_id=project_id)
        open_activities = cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False, company_id=company_id, branch_id=branch_id, project_id=project_id)

        quote_count_by_contact = {}
        sales_by_contact = {}
        activity_by_contact = {}
        for q in quotations:
            quote_count_by_contact[q.get("clientId", "")] = quote_count_by_contact.get(q.get("clientId", ""), 0) + 1
        for inv in invoices:
            if inv.get("status") not in ("Anulada", "Borrador") and not inv.get("isQuotation"):
                sales_by_contact[inv.get("clientId", "")] = sales_by_contact.get(inv.get("clientId", ""), 0.0) + _safe_float(inv.get("total"))
        for activity in open_activities:
            cid = activity.get("contactId", "")
            if cid:
                activity_by_contact[cid] = activity_by_contact.get(cid, 0) + 1

        leads = []
        all_opps = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, include_closed=True, branch_id=branch_id, project_id=project_id)
        all_activities = cls.get_activities(owner_uid, sandbox=sandbox, include_completed=True, company_id=company_id, branch_id=branch_id, project_id=project_id)

        for contact in contacts:
            score_data = cls.calculate_lead_score(
                owner_uid=owner_uid,
                contact=contact,
                opportunities=all_opps,
                activities=all_activities,
                quotations=quotations,
                invoices=invoices,
                sandbox=sandbox,
                company_id=company_id,
            )

            # Próxima acción sugerida
            next_action = "Registrar primer contacto"
            if quote_count_by_contact.get(contact["id"], 0) > 0:
                next_action = "Dar seguimiento a cotización"
            elif contact.get("pipelineStage") in ("Contactado", "En Negociación", "Propuesta"):
                next_action = "Avanzar propuesta u oportunidad"
            elif contact.get("nextContactDate"):
                next_action = "Cumplir seguimiento agendado"

            leads.append({
                "id": contact["id"],
                "razonSocial": contact.get("razonSocial", ""),
                "rnc": contact.get("rnc", ""),
                "email": contact.get("email", ""),
                "telefono": contact.get("telefono") or contact.get("celular", ""),
                "pipelineStage": contact.get("pipelineStage", "Prospecto"),
                "nextContactDate": _date_key(contact.get("nextContactDate")),
                "score": score_data["score"],
                "classification": score_data["classification"],
                "classificationLabel": score_data["classificationLabel"],
                "scoreBreakdown": score_data["scoreBreakdown"],
                "totalInvoiced": score_data["totalInvoiced"],
                "quotationCount": quote_count_by_contact.get(contact["id"], 0),
                "openActivities": activity_by_contact.get(contact["id"], 0),
                "nextAction": next_action,
            })

        leads.sort(key=lambda l: (-l["score"], l.get("nextContactDate") or "9999-12-31", l["razonSocial"].lower()))
        return leads

    @classmethod
    def calculate_lead_score(
        cls,
        owner_uid,
        contact,
        opportunities=None,
        activities=None,
        quotations=None,
        invoices=None,
        interactions=None,
        sandbox=True,
        company_id=None,
        today_date=None,
    ):
        """
        Calcula el lead score determinístico (0-100), clasificación y desglose explicativo (F4.4).
        Diferencia claramente clientes consolidados/activos de prospectos fríos.
        """
        company_id = _require_company_id(company_id)
        if not contact or not isinstance(contact, dict):
            return {"score": 0, "classification": "cold_lead", "classificationLabel": "Lead Frío", "scoreBreakdown": [], "totalInvoiced": 0.0}

        ref_today = today_date or datetime.now(timezone.utc).date()
        contact_id = contact.get("id")

        if opportunities is None:
            opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, contact_id=contact_id, include_closed=True)
        else:
            opportunities = [o for o in opportunities if o.get("contactId") == contact_id]

        if activities is None:
            activities = cls.get_activities(owner_uid, sandbox=sandbox, company_id=company_id, contact_id=contact_id, include_completed=True)
        else:
            activities = [a for a in activities if a.get("contactId") == contact_id]

        if quotations is None:
            quotations = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=True, company_id=company_id)
            quotations = [q for q in quotations if q.get("clientId") == contact_id]
        else:
            quotations = [q for q in quotations if q.get("clientId") == contact_id]

        if invoices is None:
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False, company_id=company_id)
            invoices = [i for i in invoices if i.get("clientId") == contact_id and not i.get("isQuotation")]
        else:
            invoices = [i for i in invoices if i.get("clientId") == contact_id and not i.get("isQuotation")]

        if interactions is None:
            try:
                interactions = DatabaseService.get_client_interactions(owner_uid, contact_id, sandbox=sandbox, company_id=company_id) or []
            except Exception:
                interactions = []

        real_invoices = [inv for inv in invoices if inv.get("status") not in ("Anulada", "Borrador")]
        total_invoiced = sum(_safe_float(inv.get("total")) for inv in real_invoices)

        all_action_dates = []
        for it in interactions:
            d = _parse_date(it.get("date") or it.get("createdAt"))
            if d:
                all_action_dates.append(d)
        for act in activities:
            for fld in ("completedAt", "updatedAt", "createdAt"):
                d = _parse_date(act.get(fld))
                if d:
                    all_action_dates.append(d)
        for inv in real_invoices:
            d = _parse_date(inv.get("date") or inv.get("createdAt"))
            if d:
                all_action_dates.append(d)

        last_action_date = max(all_action_dates) if all_action_dates else None
        days_since_last_action = (ref_today - last_action_date).days if last_action_date else 999

        raw_score = 0
        breakdown = []

        # Base
        raw_score += LEAD_SCORE_WEIGHTS["base"]
        breakdown.append({"factor": "base", "points": LEAD_SCORE_WEIGHTS["base"], "description": "Puntaje base de registro"})

        # Información de contacto
        if contact.get("email"):
            raw_score += LEAD_SCORE_WEIGHTS["has_email"]
            breakdown.append({"factor": "has_email", "points": LEAD_SCORE_WEIGHTS["has_email"], "description": "Email registrado"})
        if contact.get("telefono") or contact.get("celular"):
            raw_score += LEAD_SCORE_WEIGHTS["has_phone"]
            breakdown.append({"factor": "has_phone", "points": LEAD_SCORE_WEIGHTS["has_phone"], "description": "Teléfono registrado"})
        if contact.get("responsibleId"):
            raw_score += LEAD_SCORE_WEIGHTS["has_responsible"]
            breakdown.append({"factor": "has_responsible", "points": LEAD_SCORE_WEIGHTS["has_responsible"], "description": "Responsable comercial asignado"})

        # Recencia de interacción
        if days_since_last_action <= 7:
            raw_score += LEAD_SCORE_WEIGHTS["recent_interaction_7d"]
            breakdown.append({"factor": "recent_interaction_7d", "points": LEAD_SCORE_WEIGHTS["recent_interaction_7d"], "description": f"Interacción reciente hace {days_since_last_action}d (últimos 7 días)"})
        elif days_since_last_action <= 30:
            raw_score += LEAD_SCORE_WEIGHTS["recent_interaction_30d"]
            breakdown.append({"factor": "recent_interaction_30d", "points": LEAD_SCORE_WEIGHTS["recent_interaction_30d"], "description": f"Interacción reciente hace {days_since_last_action}d (últimos 30 días)"})

        # Oportunidades y etapa
        open_opps = [o for o in opportunities if o.get("status") == "abierta" and not o.get("isDeleted")]
        if open_opps:
            raw_score += LEAD_SCORE_WEIGHTS["open_opportunity"]
            breakdown.append({"factor": "open_opportunity", "points": LEAD_SCORE_WEIGHTS["open_opportunity"], "description": f"{len(open_opps)} oportunidad(es) abierta(s)"})

            highest_stage = None
            for opp in open_opps:
                st = opp.get("stage")
                if st in ("Propuesta", "Negociación"):
                    highest_stage = "advanced"
                    break
                elif st in ("Contactado", "Calificado") and highest_stage != "advanced":
                    highest_stage = "early"

            if highest_stage == "advanced":
                raw_score += LEAD_SCORE_WEIGHTS["stage_proposal_or_negotiation"]
                breakdown.append({"factor": "stage_proposal_or_negotiation", "points": LEAD_SCORE_WEIGHTS["stage_proposal_or_negotiation"], "description": "Oportunidad en etapa avanzada (Propuesta/Negociación)"})
            elif highest_stage == "early":
                raw_score += LEAD_SCORE_WEIGHTS["stage_contacted_or_qualified"]
                breakdown.append({"factor": "stage_contacted_or_qualified", "points": LEAD_SCORE_WEIGHTS["stage_contacted_or_qualified"], "description": "Oportunidad en etapa inicial (Contactado/Calificado)"})

        # Cotizaciones
        active_quotes = [q for q in quotations if q.get("status") not in ("Anulada", "Rechazada")]
        if active_quotes:
            raw_score += LEAD_SCORE_WEIGHTS["active_quotation"]
            breakdown.append({"factor": "active_quotation", "points": LEAD_SCORE_WEIGHTS["active_quotation"], "description": f"{len(active_quotes)} cotización(es) comercial(es)"})

        # Historial de facturación
        if total_invoiced > 0:
            raw_score += LEAD_SCORE_WEIGHTS["billing_history"]
            breakdown.append({"factor": "billing_history", "points": LEAD_SCORE_WEIGHTS["billing_history"], "description": f"Facturación histórica acumulada (RD$ {total_invoiced:,.2f})"})
            if total_invoiced >= 100000.0:
                raw_score += LEAD_SCORE_WEIGHTS["high_billing"]
                breakdown.append({"factor": "high_billing", "points": LEAD_SCORE_WEIGHTS["high_billing"], "description": "Cliente de alto volumen (>= RD$ 100k)"})

        score = max(0, min(100, raw_score))

        # Clasificación contextual (diferenciando cliente vs lead)
        is_client = "cliente" in contact.get("types", []) or total_invoiced > 0 or contact.get("pipelineStage") == "Cliente Activo"
        if is_client and total_invoiced > 0:
            if days_since_last_action <= 90:
                classification = "active_customer"
                classification_label = "Cliente Activo"
            else:
                classification = "dormant_customer"
                classification_label = "Cliente Inactivo/Dormido"
        else:
            if score >= 70:
                classification = "hot_lead"
                classification_label = "Lead Caliente"
            elif score >= 40:
                classification = "warm_lead"
                classification_label = "Lead Templado"
            else:
                classification = "cold_lead"
                classification_label = "Lead Frío"

        return {
            "score": score,
            "classification": classification,
            "classificationLabel": classification_label,
            "scoreBreakdown": breakdown,
            "totalInvoiced": round(total_invoiced, 2),
            "daysSinceLastAction": days_since_last_action if days_since_last_action != 999 else None,
        }

    @classmethod
    def get_sales_metrics(
        cls,
        owner_uid,
        sandbox=True,
        company_id=None,
        branch_id=None,
        project_id=None,
        assigned_to=None,
        date_from=None,
        date_to=None,
    ):
        """
        Calcula métricas comerciales avanzadas y conversión de embudo (F4.3).
        Soporta filtrado por sucursal, proyecto, vendedor y rango de fechas.
        """
        company_id = _require_company_id(company_id)
        all_opps = cls.get_opportunities(
            owner_uid,
            sandbox=sandbox,
            company_id=company_id,
            include_closed=True,
            branch_id=branch_id,
            project_id=project_id,
        )

        if assigned_to:
            all_opps = [o for o in all_opps if o.get("assignedTo") == assigned_to]

        df = _parse_date(date_from)
        dt = _parse_date(date_to)

        if df or dt:
            filtered_opps = []
            for o in all_opps:
                crt = _parse_date(o.get("createdAt"))
                cls_d = _parse_date(o.get("closedAt"))
                in_range = False
                if crt and (not df or crt >= df) and (not dt or crt <= dt):
                    in_range = True
                if cls_d and (not df or cls_d >= df) and (not dt or cls_d <= dt):
                    in_range = True
                if in_range:
                    filtered_opps.append(o)
            opps = filtered_opps
        else:
            opps = all_opps

        open_opps = [o for o in opps if o.get("status") == "abierta" and not o.get("isDeleted") and o.get("stage") not in ("Ganada", "Perdida")]
        won_opps = [o for o in opps if (o.get("status") == "ganada" or o.get("stage") == "Ganada") and not o.get("isDeleted")]
        lost_opps = [o for o in opps if (o.get("status") == "perdida" or o.get("stage") == "Perdida") and not o.get("isDeleted")]

        # 1. Pipeline nominal y ponderado
        pipeline_value = sum(_safe_float(o.get("amount")) for o in open_opps if _safe_float(o.get("amount")) > 0)
        weighted_pipeline = sum(
            _safe_float(o.get("amount")) * (max(0, min(100, _safe_int(o.get("probability"), 10))) / 100.0)
            for o in open_opps if _safe_float(o.get("amount")) > 0
        )

        # 2. Win rate
        closed_count = len(won_opps) + len(lost_opps)
        win_rate = round((len(won_opps) / closed_count * 100.0), 2) if closed_count > 0 else 0.0

        # 3. Ticket promedio (Average won amount)
        won_amounts = [_safe_float(o.get("amount")) for o in won_opps if _safe_float(o.get("amount")) > 0]
        avg_won_amount = round(sum(won_amounts) / len(won_amounts), 2) if won_amounts else 0.0

        # 4. Ciclo promedio de venta (días hasta ganar)
        sales_cycle_days = []
        for o in won_opps:
            crt_date = _parse_date(o.get("createdAt"))
            won_date = None

            for h in (o.get("stageHistory") or []):
                if h.get("to") == "Ganada":
                    won_date = _parse_date(h.get("timestamp"))
                    if won_date:
                        break

            if not won_date:
                won_date = _parse_date(o.get("closedAt")) or _parse_date(o.get("updatedAt"))

            if crt_date and won_date:
                days = (won_date - crt_date).days
                sales_cycle_days.append(max(0, days))

        avg_sales_cycle_days = round(sum(sales_cycle_days) / len(sales_cycle_days), 1) if sales_cycle_days else 0.0

        # 5. Funnel de conversión usando stageHistory + estado actual
        stages_order = ["Prospecto", "Contactado", "Calificado", "Propuesta", "Negociación", "Ganada"]
        stage_reached_counts = {st: 0 for st in stages_order}

        for o in opps:
            if o.get("isDeleted"):
                continue
            stages_touched = set()
            for h in (o.get("stageHistory") or []):
                if h.get("from"):
                    stages_touched.add(h["from"])
                if h.get("to"):
                    stages_touched.add(h["to"])
            curr = o.get("stage")
            if curr:
                stages_touched.add(curr)
            stages_touched.add("Prospecto")

            normalized_touched = set()
            for s in stages_touched:
                if s == "En Negociación":
                    normalized_touched.add("Negociación")
                elif s in stage_reached_counts:
                    normalized_touched.add(s)

            for st in normalized_touched:
                stage_reached_counts[st] += 1

        canonical_pairs = [
            ("prospect_to_contacted", "Prospecto", "Contactado"),
            ("contacted_to_qualified", "Contactado", "Calificado"),
            ("qualified_to_proposal", "Calificado", "Propuesta"),
            ("proposal_to_negotiation", "Propuesta", "Negociación"),
            ("negotiation_to_won", "Negociación", "Ganada"),
        ]
        conversion_rates = {}
        for key_name, s_from, s_to in canonical_pairs:
            denom = stage_reached_counts.get(s_from, 0)
            num = stage_reached_counts.get(s_to, 0)
            rate = round((num / denom * 100.0), 1) if denom > 0 else 0.0
            conversion_rates[key_name] = min(100.0, rate)
            # Spanish alias for template friendliness
            conversion_rates[f"{s_from.lower()}_to_{s_to.lower()}"] = min(100.0, rate)

        # 6. Desgloses por vendedor, sucursal y proyecto
        by_salesperson = {}
        by_branch = {}
        by_project = {}

        for o in opps:
            if o.get("isDeleted"):
                continue
            rep_id = o.get("assignedTo") or "unassigned"
            rep_name = o.get("assignedToName") or "Sin Asignar"
            br_id = o.get("branchId") or "default-sucursal-principal"
            pr_id = o.get("projectId") or "none"

            if rep_id not in by_salesperson:
                by_salesperson[rep_id] = {
                    "salespersonId": rep_id,
                    "salespersonName": rep_name,
                    "open": 0, "won": 0, "lost": 0,
                    "pipeline": 0.0, "weightedPipeline": 0.0, "wonAmount": 0.0,
                }
            if br_id not in by_branch:
                by_branch[br_id] = {"branchId": br_id, "open": 0, "won": 0, "lost": 0, "pipeline": 0.0, "wonAmount": 0.0}
            if pr_id not in by_project:
                by_project[pr_id] = {"projectId": pr_id, "open": 0, "won": 0, "lost": 0, "pipeline": 0.0, "wonAmount": 0.0}

            amt = _safe_float(o.get("amount"))
            prob = max(0, min(100, _safe_int(o.get("probability"), 10))) / 100.0
            st_status = o.get("status")

            if st_status == "abierta" and o.get("stage") not in ("Ganada", "Perdida"):
                by_salesperson[rep_id]["open"] += 1
                by_salesperson[rep_id]["pipeline"] += amt
                by_salesperson[rep_id]["weightedPipeline"] += (amt * prob)
                by_branch[br_id]["open"] += 1
                by_branch[br_id]["pipeline"] += amt
                by_project[pr_id]["open"] += 1
                by_project[pr_id]["pipeline"] += amt
            elif st_status == "ganada" or o.get("stage") == "Ganada":
                by_salesperson[rep_id]["won"] += 1
                by_salesperson[rep_id]["wonAmount"] += amt
                by_branch[br_id]["won"] += 1
                by_branch[br_id]["wonAmount"] += amt
                by_project[pr_id]["won"] += 1
                by_project[pr_id]["wonAmount"] += amt
            elif st_status == "perdida" or o.get("stage") == "Perdida":
                by_salesperson[rep_id]["lost"] += 1
                by_branch[br_id]["lost"] += 1
                by_project[pr_id]["lost"] += 1

        for rep in by_salesperson.values():
            cl = rep["won"] + rep["lost"]
            rep["winRate"] = round((rep["won"] / cl * 100.0), 1) if cl > 0 else 0.0
            rep["pipeline"] = round(rep["pipeline"], 2)
            rep["weightedPipeline"] = round(rep["weightedPipeline"], 2)
            rep["wonAmount"] = round(rep["wonAmount"], 2)

        return {
            "openOpportunities": len(open_opps),
            "wonOpportunities": len(won_opps),
            "lostOpportunities": len(lost_opps),
            "pipelineValue": round(pipeline_value, 2),
            "weightedPipelineValue": round(weighted_pipeline, 2),
            "winRate": win_rate,
            "avgWonAmount": avg_won_amount,
            "avgSalesCycleDays": avg_sales_cycle_days,
            "funnel": stage_reached_counts,
            "conversionRates": conversion_rates,
            "bySalesperson": list(by_salesperson.values()),
            "byBranch": list(by_branch.values()),
            "byProject": list(by_project.values()),
        }

    @classmethod
    def _snapshot_coll(cls, sandbox=True):
        return "sandbox_crm_metric_snapshots" if sandbox else "crm_metric_snapshots"

    @classmethod
    def create_metric_snapshot(
        cls,
        owner_uid,
        sandbox=True,
        company_id=None,
        branch_id=None,
        project_id=None,
        period="daily",
        period_start=None,
        period_end=None,
    ):
        """
        Calcula y persiste de forma idempotente un snapshot histórico de métricas comerciales (F4.5).
        """
        company_id = _require_company_id(company_id)
        ref_today = datetime.now(timezone.utc).date()
        p_start = _date_key(period_start) or ref_today.strftime("%Y-%m-%d")
        p_end = _date_key(period_end) or p_start

        # Clave lógica de unicidad
        b_key = branch_id or "all"
        p_key = project_id or "all"
        snapshot_id = f"snap_{company_id}_{b_key}_{p_key}_{period}_{p_start}".replace("/", "_")

        metrics = cls.get_sales_metrics(
            owner_uid,
            sandbox=sandbox,
            company_id=company_id,
            branch_id=branch_id,
            project_id=project_id,
            date_from=p_start if period != "daily" else None,
            date_to=p_end if period != "daily" else None,
        )

        activities = cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False, company_id=company_id, branch_id=branch_id, project_id=project_id)
        leads = cls.get_leads(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)

        snapshot_data = {
            "id": snapshot_id,
            "ownerUID": owner_uid,
            "companyId": company_id,
            "branchId": branch_id,
            "projectId": project_id,
            "period": period,
            "periodStart": p_start,
            "periodEnd": p_end,
            "snapshotDate": p_start,
            "openOpportunities": metrics["openOpportunities"],
            "wonOpportunities": metrics["wonOpportunities"],
            "lostOpportunities": metrics["lostOpportunities"],
            "pipelineValue": metrics["pipelineValue"],
            "weightedPipelineValue": metrics["weightedPipelineValue"],
            "overdueActivities": len([a for a in activities if a.get("isOverdue")]),
            "todayActivities": len([a for a in activities if a.get("isDueToday")]),
            "leadCount": len(leads),
            "winRate": metrics["winRate"],
            "avgDealSize": metrics["avgWonAmount"],
            "avgSalesCycleDays": metrics["avgSalesCycleDays"],
            "conversionRates": metrics["conversionRates"],
            "byStage": metrics["funnel"],
            "byRep": metrics["bySalesperson"],
            "createdAt": _now_iso(),
        }

        if firebase_initialized:
            try:
                _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._snapshot_coll(sandbox)).document(snapshot_id).set(snapshot_data)
            except Exception as e:
                print(f"⚠️ Error al guardar snapshot de métricas CRM {snapshot_id}: {e}")

        return snapshot_data

    @classmethod
    def get_metric_snapshots(
        cls,
        owner_uid,
        sandbox=True,
        company_id=None,
        branch_id=None,
        project_id=None,
        period=None,
        limit=30,
    ):
        """Recupera la evolución histórica de snapshots para el tenant."""
        company_id = _require_company_id(company_id)
        if not firebase_initialized:
            return []
        try:
            docs = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._snapshot_coll(sandbox)).get()
            snapshots = []
            for doc in docs:
                d = doc.to_dict() or {}
                if d.get("companyId") != company_id:
                    continue
                if branch_id and d.get("branchId") != branch_id:
                    continue
                if project_id and d.get("projectId") != project_id:
                    continue
                if period and d.get("period") != period:
                    continue
                d["id"] = doc.id
                snapshots.append(d)

            snapshots.sort(key=lambda s: s.get("periodStart") or s.get("createdAt") or "", reverse=True)
            return snapshots[:limit]
        except Exception as e:
            print(f"⚠️ Error al obtener snapshots de métricas CRM: {e}")
            return []

    @classmethod
    def get_dashboard(cls, owner_uid, sandbox=True, company_id=None, branch_id=None, project_id=None, date_range=None):
        company_id = _require_company_id(company_id)
        today = datetime.now(timezone.utc).date()
        date_from = None
        date_to = None
        if date_range == "30d":
            date_from = (today - timedelta(days=30)).isoformat()
        elif date_range == "90d":
            date_from = (today - timedelta(days=90)).isoformat()
        elif date_range == "year":
            date_from = f"{today.year}-01-01"

        sales_metrics = cls.get_sales_metrics(
            owner_uid,
            sandbox=sandbox,
            company_id=company_id,
            branch_id=branch_id,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
        )

        opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, include_closed=True, branch_id=branch_id, project_id=project_id)
        activities = cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False, company_id=company_id, branch_id=branch_id, project_id=project_id)
        leads = cls.get_leads(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
        pipeline = cls.get_pipeline(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
        stale_opps = cls.get_stale_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)

        overdue = [a for a in activities if a.get("isOverdue")]
        today_acts = [a for a in activities if a.get("isDueToday")]
        upcoming = [a for a in activities if a.get("isUpcoming")]

        suggestions = cls.get_next_action_suggestions(owner_uid, sandbox=sandbox, company_id=company_id, opportunities=[o for o in opportunities if o.get("status") == "abierta"], leads=leads, activities=activities)

        return {
            "metrics": {
                **sales_metrics,
                "staleOpportunities": len(stale_opps),
                "overdueActivities": len(overdue),
                "todayActivities": len(today_acts),
                "upcomingActivities": len(upcoming),
                "leadCount": len(leads),
            },
            "salesMetrics": sales_metrics,
            "pipeline": pipeline,
            "activitiesToday": today_acts[:8],
            "activitiesOverdue": overdue[:8],
            "staleOpportunities": stale_opps[:8],
            "topLeads": leads[:8],
            "suggestions": suggestions[:8],
            "recentOpportunities": opportunities[:8],
            "selectedDateRange": date_range or "all",
        }

    @classmethod
    def get_next_action_suggestions(cls, owner_uid, sandbox=True, company_id=None, opportunities=None, leads=None, activities=None):
        company_id = _require_company_id(company_id)
        opportunities = opportunities if opportunities is not None else cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, include_closed=False)
        leads = leads if leads is not None else cls.get_leads(owner_uid, sandbox=sandbox, company_id=company_id)
        activities = activities if activities is not None else cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False, company_id=company_id)

        today = datetime.now(timezone.utc).date()
        activities_by_contact = {}
        for activity in activities:
            cid = activity.get("contactId")
            if cid:
                activities_by_contact[cid] = activities_by_contact.get(cid, 0) + 1

        suggestions = []
        for opportunity in opportunities:
            due = _parse_date(opportunity.get("expectedCloseDate"))
            if due and due < today:
                suggestions.append({
                    "type": "opportunity",
                    "priority": "alta",
                    "text": f"Revisar cierre vencido: {opportunity.get('title')}",
                    "contactId": opportunity.get("contactId"),
                    "opportunityId": opportunity.get("id"),
                })
            elif opportunity.get("probability", 0) >= 70 and not activities_by_contact.get(opportunity.get("contactId")):
                suggestions.append({
                    "type": "opportunity",
                    "priority": "media",
                    "text": f"Agendar seguimiento para oportunidad caliente: {opportunity.get('title')}",
                    "contactId": opportunity.get("contactId"),
                    "opportunityId": opportunity.get("id"),
                })

        for lead in leads:
            if lead.get("score", 0) >= 70 and not activities_by_contact.get(lead["id"]):
                suggestions.append({
                    "type": "lead",
                    "priority": "media",
                    "text": f"{lead['razonSocial']}: {lead['nextAction']}",
                    "contactId": lead["id"],
                    "opportunityId": "",
                })

        priority_order = {"alta": 0, "media": 1, "baja": 2}
        suggestions.sort(key=lambda s: priority_order.get(s.get("priority", "media"), 1))
        return suggestions

    _commitments_cache = {}
    _CACHE_TTL_SECONDS = 60

    @classmethod
    def invalidate_commitments_cache(cls, company_id=None):
        """Invalida el caché de compromisos globales para la empresa dada o todas."""
        if company_id:
            prefix = f"{company_id}:"
            keys_to_del = [k for k in cls._commitments_cache if k.startswith(prefix)]
            for k in keys_to_del:
                cls._commitments_cache.pop(k, None)
        else:
            cls._commitments_cache.clear()

    @classmethod
    def get_global_commitments(cls, owner_uid, sandbox=True, company_id=None):
        """
        Retorna compromisos CRM (actividades para hoy o vencidas) para la empresa activa.
        Optimizado: no escanea contactos ni facturas completas, y cachea el resultado durante 60 segundos.
        """
        import time
        company_id = _require_company_id(company_id)
        today = _today_str()
        cache_key = f"{company_id}:{bool(sandbox)}:{today}"

        cached = cls._commitments_cache.get(cache_key)
        if cached:
            ts, data = cached
            if time.time() - ts < cls._CACHE_TTL_SECONDS:
                return [dict(d) for d in data]

        # Consultar únicamente actividades pendientes de la empresa
        pending_activities = cls.get_activities(
            owner_uid=owner_uid,
            sandbox=sandbox,
            include_completed=False,
            company_id=company_id,
        )

        commitments = []
        activity_contact_ids = set()
        for activity in pending_activities:
            if not activity.get("isOverdue") and not activity.get("isDueToday"):
                continue
            cid = activity.get("contactId")
            if cid:
                activity_contact_ids.add(cid)
            commitments.append({
                "id": cid or activity["id"],
                "activityId": activity["id"],
                "razonSocial": activity.get("contactName") or activity.get("title", ""),
                "telefono": "",
                "crmNotes": activity.get("description") or activity.get("title", ""),
                "total_cxc": 0.0,
                "nextContactDate": activity.get("dueDate"),
                "commitmentType": "activity",
                "activityType": activity.get("type"),
                "isOverdue": activity.get("isOverdue", False),
            })

        # Incluir contactos con nextContactDate agendado para hoy/vencido sin actividad duplicada
        try:
            contacts = ContactService.get_contacts(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
            for contact in contacts:
                if "cliente" not in contact.get("types", []):
                    continue
                if contact.get("id") in activity_contact_ids:
                    continue
                next_date = _date_key(contact.get("nextContactDate"))
                if next_date and next_date <= today:
                    commitments.append({
                        "id": contact["id"],
                        "activityId": "",
                        "razonSocial": contact.get("razonSocial", ""),
                        "telefono": contact.get("telefono") or contact.get("celular", ""),
                        "crmNotes": contact.get("crmNotes") or contact.get("notes", ""),
                        "total_cxc": 0.0,
                        "nextContactDate": next_date,
                        "commitmentType": "contact",
                        "activityType": "Seguimiento",
                        "isOverdue": next_date < today,
                    })
        except Exception:
            pass

        commitments.sort(key=lambda c: (
            not c.get("isOverdue", False),
            _date_key(c.get("nextContactDate")) or today,
            c.get("razonSocial", "").lower(),
        ))
        result = commitments[:20]
        cls._commitments_cache[cache_key] = (time.time(), result)
        return [dict(d) for d in result]

    @classmethod
    def get_contact_360(cls, owner_uid, contact_id, sandbox=True, company_id=None):
        """
        Retorna la ficha consolidada 360 del contacto/cliente para CRM (CRM-05/CRM-06):
        - Datos generales
        - Oportunidades asociadas
        - Actividades asociadas (pendientes y completadas)
        - Interacciones históricas
        - Facturas y cotizaciones
        - Timeline unificado
        - Métricas comerciales consolidadas
        """
        company_id = _require_company_id(company_id)
        contact = _resolve_contact(owner_uid, contact_id, sandbox=sandbox, company_id=company_id)
        if not contact:
            return None

        opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, contact_id=contact_id, include_closed=True)
        activities = cls.get_activities(owner_uid, sandbox=sandbox, company_id=company_id, contact_id=contact_id, include_completed=True)
        interactions = DatabaseService.get_client_interactions(owner_uid, contact_id, sandbox=sandbox, company_id=company_id)
        all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
        invoices = [inv for inv in all_invoices if inv.get("clientId") == contact_id and not inv.get("isQuotation")]
        quotations = [inv for inv in all_invoices if inv.get("clientId") == contact_id and inv.get("isQuotation")]

        timeline = []
        for inter in interactions:
            timeline.append({
                "type": "interaction",
                "subtype": inter.get("type", "Nota"),
                "title": inter.get("title", "Interacción"),
                "content": inter.get("content", ""),
                "date": inter.get("date") or inter.get("createdAt") or "",
                "user": inter.get("createdBy", "Sistema"),
            })

        for act in activities:
            if act.get("status") == "completada":
                timeline.append({
                    "type": "activity_completed",
                    "subtype": act.get("type", "Tarea"),
                    "title": f"Actividad completada: {act.get('title')}",
                    "content": act.get("description", ""),
                    "date": act.get("completedAt") or act.get("updatedAt") or "",
                    "user": act.get("assignedToName") or "Equipo Comercial",
                })

        for inv in invoices:
            if inv.get("status") not in ("Anulada", "Borrador"):
                timeline.append({
                    "type": "invoice",
                    "subtype": inv.get("ecfType", "Factura"),
                    "title": f"Factura emitida: {inv.get('invoiceNumber') or inv.get('rnc', '')}",
                    "content": f"Monto: RD$ {_safe_float(inv.get('total')):,.2f} - Estado: {inv.get('status')}",
                    "date": inv.get("date") or inv.get("createdAt") or "",
                    "user": "Facturación",
                })

        timeline.sort(key=lambda item: item.get("date") or "", reverse=True)

        return {
            "contact": contact,
            "opportunities": opportunities,
            "activities": activities,
            "interactions": interactions,
            "invoices": invoices,
            "quotations": quotations,
            "timeline": timeline,
            "metrics": {
                "totalInvoiced": sum(_safe_float(inv.get("total")) for inv in invoices if inv.get("status") not in ("Anulada", "Borrador")),
                "totalCxc": sum(_safe_float(inv.get("netPayable")) for inv in invoices if inv.get("status") in ("Emitida", "Vencida", "Revisión de Pago")),
                "openOpportunities": len([o for o in opportunities if o.get("status") == "abierta"]),
                "wonOpportunities": len([o for o in opportunities if o.get("status") == "ganada"]),
                "pendingActivities": len([a for a in activities if a.get("status") == "pendiente"]),
            }
        }

    @classmethod
    def _normalize_opportunity(cls, data):
        stage = _normalize_stage(data.get("stage"))
        status = data.get("status", "abierta")
        if stage == "Ganada":
            status = "ganada"
        elif stage == "Perdida":
            status = "perdida"
        elif status not in ("ganada", "perdida"):
            status = "abierta"
        data["companyId"] = data.get("companyId", "")
        data["branchId"] = data.get("branchId", "default-sucursal-principal")
        data["projectId"] = data.get("projectId")
        data["stage"] = stage
        data["status"] = status
        data["amount"] = _safe_float(data.get("amount"))
        data["probability"] = _safe_int(data.get("probability"), CRM_STAGE_PROBABILITY.get(stage, 10))
        data["expectedCloseDate"] = _date_key(data.get("expectedCloseDate"))
        data["nextContactDate"] = _date_key(data.get("nextContactDate"))
        data["isStale"] = bool(data.get("isStale", False))
        data["staleReason"] = data.get("staleReason", "")
        data["invoices"] = data.get("invoices") or []
        data["lostReason"] = data.get("lostReason", "")
        data["stageHistory"] = data.get("stageHistory") or []
        data["isDeleted"] = bool(data.get("isDeleted", False))
        data["deletedAt"] = data.get("deletedAt", "")
        data["deletedBy"] = data.get("deletedBy", "")
        data["createdAt"] = serialize_field(data.get("createdAt"))
        data["updatedAt"] = serialize_field(data.get("updatedAt"))
        data["closedAt"] = serialize_field(data.get("closedAt"))
        data["weightedAmount"] = round(data["amount"] * (data["probability"] / 100.0), 2)
        return data

    @classmethod
    def _normalize_activity(cls, data):
        data["companyId"] = data.get("companyId", "")
        data["branchId"] = data.get("branchId", "default-sucursal-principal")
        data["projectId"] = data.get("projectId")
        data["type"] = _normalize_activity_type(data.get("type"))
        data["priority"] = _normalize_priority(data.get("priority"))
        data["status"] = _normalize_status(data.get("status"))
        data["dueDate"] = _date_key(data.get("dueDate"))
        data["originRuleId"] = data.get("originRuleId", "")
        data["idempotencyKey"] = data.get("idempotencyKey", "")
        data["autoGenerated"] = bool(data.get("autoGenerated", False))
        data["isDeleted"] = bool(data.get("isDeleted", False))
        data["deletedAt"] = data.get("deletedAt", "")
        data["deletedBy"] = data.get("deletedBy", "")
        data["createdAt"] = serialize_field(data.get("createdAt"))
        data["updatedAt"] = serialize_field(data.get("updatedAt"))
        data["completedAt"] = serialize_field(data.get("completedAt"))
        return data

    @classmethod
    def _sync_activity_to_contact(cls, owner_uid, activity, sandbox=True, company_id=None):
        contact_id = activity.get("contactId")
        if not contact_id:
            return
        try:
            interaction_dict = {
                "type": activity.get("type", "Tarea"),
                "title": activity.get("title", ""),
                "content": activity.get("description") or activity.get("title", ""),
                "date": activity.get("createdAt") or _now_iso(),
                "nextContactDate": activity.get("dueDate") if activity.get("status") == "pendiente" else "",
                "completed": activity.get("status") == "completada",
                "createdBy": activity.get("createdBy", "Sistema CRM"),
            }
            DatabaseService.save_client_interaction(owner_uid, contact_id, activity["id"], interaction_dict, sandbox=sandbox, company_id=company_id)
        except Exception:
            pass

        if activity.get("dueDate") and activity.get("status") == "pendiente":
            try:
                contact = ContactService.get_contact(owner_uid=owner_uid, contact_id=contact_id, sandbox=sandbox, company_id=company_id)
                if contact:
                    current_due = _date_key(contact.get("nextContactDate"))
                    if not current_due or activity["dueDate"] <= current_due:
                        contact["nextContactDate"] = activity["dueDate"]
                        ContactService.save_contact(owner_uid=owner_uid, contact_id=contact_id, contact_dict=contact, sandbox=sandbox, company_id=company_id)
            except Exception:
                pass

    @classmethod
    def _record_opportunity_interaction(cls, owner_uid, opportunity, sandbox=True, company_id=None):
        contact_id = opportunity.get("contactId")
        if not contact_id:
            return
        status_label = "ganada" if opportunity.get("status") == "ganada" else "perdida"
        content = f"Oportunidad {status_label}: {opportunity.get('title', '')}. Valor: RD$ {_safe_float(opportunity.get('amount')):,.2f}."
        if opportunity.get("invoiceNumber"):
            content += f" Factura asociada: {opportunity['invoiceNumber']}."
        if opportunity.get("lostReason"):
            content += f" Motivo: {opportunity['lostReason']}."
        try:
            DatabaseService.save_client_interaction(owner_uid, contact_id, str(uuid.uuid4()), {
                "type": "Seguimiento",
                "title": f"Oportunidad {status_label}",
                "content": content,
                "date": _now_iso(),
                "completed": True,
                "createdBy": "Sistema CRM",
            }, sandbox=sandbox, company_id=company_id)
        except Exception:
            pass
