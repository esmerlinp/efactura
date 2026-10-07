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


def _annotate_activity(activity):
    if not isinstance(activity, dict):
        return activity
    due_date = _parse_date(activity.get("dueDate"))
    today = datetime.now(timezone.utc).date()
    is_pending = activity.get("status", "pendiente") == "pendiente"
    activity["dueDate"] = _date_key(activity.get("dueDate"))
    activity["isOverdue"] = bool(is_pending and due_date and due_date < today)
    activity["isDueToday"] = bool(is_pending and due_date and due_date == today)
    activity["daysLate"] = (today - due_date).days if (activity["isOverdue"] and due_date) else 0
    return activity


class CRMService:
    """Operaciones de alto nivel para el módulo CRM con aislamiento multiempresa estricto."""

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
            "updatedAt": _now_iso(),
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
    def get_pipeline(cls, owner_uid, sandbox=True, company_id=None, branch_id=None, project_id=None):
        company_id = _require_company_id(company_id)
        opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, include_closed=True, branch_id=branch_id, project_id=project_id)
        grouped = []
        for stage in CRM_OPPORTUNITY_STAGES:
            stage_items = [o for o in opportunities if o.get("stage") == stage]
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
        for contact in contacts:
            stage = contact.get("pipelineStage", "Prospecto")
            if stage == "Cliente Activo" and sales_by_contact.get(contact["id"], 0.0) > 0:
                continue

            score = 10
            if contact.get("email"):
                score += 12
            if contact.get("telefono") or contact.get("celular"):
                score += 12
            if contact.get("responsibleId"):
                score += 10
            if quote_count_by_contact.get(contact["id"], 0) > 0:
                score += min(25, quote_count_by_contact[contact["id"]] * 10)
            if stage in ("En Negociación", "Propuesta", "Contactado"):
                score += 20
            if contact.get("nextContactDate"):
                due = _parse_date(contact.get("nextContactDate"))
                if due and due <= datetime.now(timezone.utc).date() + timedelta(days=7):
                    score += 15
            if activity_by_contact.get(contact["id"], 0) > 0:
                score += 10

            next_action = "Registrar primer contacto"
            if quote_count_by_contact.get(contact["id"], 0) > 0:
                next_action = "Dar seguimiento a cotización"
            elif stage in ("Contactado", "En Negociación"):
                next_action = "Crear propuesta u oportunidad"
            elif contact.get("nextContactDate"):
                next_action = "Cumplir seguimiento agendado"

            leads.append({
                "id": contact["id"],
                "razonSocial": contact.get("razonSocial", ""),
                "rnc": contact.get("rnc", ""),
                "email": contact.get("email", ""),
                "telefono": contact.get("telefono") or contact.get("celular", ""),
                "pipelineStage": stage,
                "nextContactDate": _date_key(contact.get("nextContactDate")),
                "score": min(100, score),
                "quotationCount": quote_count_by_contact.get(contact["id"], 0),
                "openActivities": activity_by_contact.get(contact["id"], 0),
                "nextAction": next_action,
            })

        leads.sort(key=lambda l: (-l["score"], l.get("nextContactDate") or "9999-12-31", l["razonSocial"].lower()))
        return leads

    @classmethod
    def get_dashboard(cls, owner_uid, sandbox=True, company_id=None, branch_id=None, project_id=None):
        company_id = _require_company_id(company_id)
        opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, company_id=company_id, include_closed=True, branch_id=branch_id, project_id=project_id)
        open_opps = [o for o in opportunities if o.get("status") == "abierta"]
        won_opps = [o for o in opportunities if o.get("status") == "ganada"]
        lost_opps = [o for o in opportunities if o.get("status") == "perdida"]
        activities = cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False, company_id=company_id, branch_id=branch_id, project_id=project_id)
        leads = cls.get_leads(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)
        pipeline = cls.get_pipeline(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=branch_id, project_id=project_id)

        closed_total = len(won_opps) + len(lost_opps)
        win_rate = (len(won_opps) / closed_total * 100.0) if closed_total else 0.0
        pipeline_value = sum(_safe_float(o.get("amount")) for o in open_opps)
        weighted_value = sum(_safe_float(o.get("amount")) * (_safe_float(o.get("probability")) / 100.0) for o in open_opps)
        overdue = [a for a in activities if a.get("isOverdue")]
        today = [a for a in activities if a.get("isDueToday")]

        suggestions = cls.get_next_action_suggestions(owner_uid, sandbox=sandbox, company_id=company_id, opportunities=open_opps, leads=leads, activities=activities)

        return {
            "metrics": {
                "openOpportunities": len(open_opps),
                "wonOpportunities": len(won_opps),
                "lostOpportunities": len(lost_opps),
                "pipelineValue": round(pipeline_value, 2),
                "weightedPipelineValue": round(weighted_value, 2),
                "overdueActivities": len(overdue),
                "todayActivities": len(today),
                "leadCount": len(leads),
                "winRate": round(win_rate, 1),
            },
            "pipeline": pipeline,
            "activitiesToday": today[:8],
            "activitiesOverdue": overdue[:8],
            "topLeads": leads[:8],
            "suggestions": suggestions[:8],
            "recentOpportunities": opportunities[:8],
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
