"""Servicios de CRM: oportunidades, actividades, pipeline y métricas comerciales."""

import uuid
from datetime import datetime, timedelta, timezone

from app.models.crm import (
    CRM_ACTIVITY_PRIORITIES,
    CRM_ACTIVITY_STATUSES,
    CRM_ACTIVITY_TYPES,
    CRM_OPPORTUNITY_STAGES,
    CRM_STAGE_PROBABILITY,
    CRMActivity,
    CRMOpportunity,
)
from app.services.contact_service import ContactService
from app.services.db_service import DatabaseService, db_firestore, firebase_initialized, serialize_field


CONTACT_PIPELINE_MAP = {
    "Prospecto": "Prospecto",
    "Contactado": "Contactado",
    "Calificado": "Contactado",
    "Propuesta": "En Negociación",
    "Negociación": "En Negociación",
    "Ganada": "Cliente Activo",
    "Perdida": "Expirado",
}


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
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


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


def _resolve_contact(owner_uid, contact_id, sandbox=True):
    if not contact_id:
        return None
    try:
        return ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
    except Exception:
        return None


def _resolve_team_member_name(owner_uid, member_uid):
    if not member_uid:
        return ""
    try:
        members = DatabaseService.get_team_members(owner_uid) or []
        member = next((m for m in members if m.get("uid") == member_uid), None)
        if member:
            return member.get("name") or member.get("email", "")
    except Exception:
        pass
    return ""


def _annotate_activity(activity):
    due_date = _parse_date(activity.get("dueDate"))
    today = datetime.now(timezone.utc).date()
    is_pending = activity.get("status", "pendiente") == "pendiente"
    activity["dueDate"] = _date_key(activity.get("dueDate"))
    activity["isOverdue"] = bool(is_pending and due_date and due_date < today)
    activity["isDueToday"] = bool(is_pending and due_date and due_date == today)
    activity["daysLate"] = (today - due_date).days if activity["isOverdue"] else 0
    return activity


class CRMService:
    """Operaciones de alto nivel para el módulo CRM."""

    @classmethod
    def get_opportunity(cls, owner_uid, opportunity_id, sandbox=True):
        if not firebase_initialized:
            return None
        try:
            doc = db_firestore.collection("users").document(owner_uid).collection(_opportunity_coll(sandbox)).document(opportunity_id).get()
            if doc.exists:
                data = doc.to_dict() or {}
                data["id"] = doc.id
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                return cls._normalize_opportunity(data)
        except Exception as e:
            print(f"⚠️ Error al obtener oportunidad CRM {opportunity_id}: {e}")
        return None

    @classmethod
    def get_opportunities(cls, owner_uid, sandbox=True, include_closed=True, contact_id=None, branch_id=None, project_id=None):
        opportunities = []
        if firebase_initialized:
            try:
                docs = db_firestore.collection("users").document(owner_uid).collection(_opportunity_coll(sandbox)).get()
                for doc in docs:
                    data = doc.to_dict() or {}
                    data["id"] = doc.id
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
    def save_opportunity(cls, owner_uid, opportunity_id, opportunity_dict, sandbox=True):
        opportunity_id = opportunity_id or opportunity_dict.get("id") or str(uuid.uuid4())
        existing = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox) or {}

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
        contact = _resolve_contact(owner_uid, contact_id, sandbox=sandbox)
        if contact:
            contact_name = contact.get("razonSocial", contact_name)

        assigned_to = opportunity_dict.get("assignedTo") or existing.get("assignedTo", "")
        assigned_to_name = opportunity_dict.get("assignedToName") or _resolve_team_member_name(owner_uid, assigned_to)

        data = {
            **existing,
            **opportunity_dict,
            "id": opportunity_id,
            "ownerUID": owner_uid,
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
            "lostReason": opportunity_dict.get("lostReason") or existing.get("lostReason", ""),
            "notes": opportunity_dict.get("notes") or existing.get("notes", ""),
            "createdBy": opportunity_dict.get("createdBy") or existing.get("createdBy", ""),
            "createdAt": serialize_field(existing.get("createdAt") or opportunity_dict.get("createdAt") or _now_iso()),
            "updatedAt": _now_iso(),
            "closedAt": existing.get("closedAt", ""),
        }

        if data["quotationId"] and not data["quotationNumber"]:
            try:
                quotation = DatabaseService.get_invoice(owner_uid, data["quotationId"], sandbox=sandbox)
                if quotation:
                    data["quotationNumber"] = quotation.get("invoiceNumber", "")
                    if data["amount"] <= 0:
                        data["amount"] = _safe_float(quotation.get("total") or quotation.get("netPayable"))
            except Exception:
                pass

        if data["invoiceId"] and not data["invoiceNumber"]:
            try:
                invoice = DatabaseService.get_invoice(owner_uid, data["invoiceId"], sandbox=sandbox)
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

        data = _model_dump(CRMOpportunity(**data))

        if firebase_initialized:
            try:
                db_firestore.collection("users").document(owner_uid).collection(_opportunity_coll(sandbox)).document(opportunity_id).set(data)
            except Exception as e:
                print(f"⚠️ Error al guardar oportunidad CRM: {e}")

        if contact_id:
            mapped_stage = CONTACT_PIPELINE_MAP.get(stage)
            if mapped_stage:
                try:
                    ContactService.update_pipeline(owner_uid, contact_id, mapped_stage, sandbox=sandbox)
                except Exception:
                    pass

        return data

    @classmethod
    def delete_opportunity(cls, owner_uid, opportunity_id, sandbox=True):
        if firebase_initialized:
            try:
                db_firestore.collection("users").document(owner_uid).collection(_opportunity_coll(sandbox)).document(opportunity_id).delete()
                return True
            except Exception as e:
                print(f"⚠️ Error al eliminar oportunidad CRM: {e}")
        return False

    @classmethod
    def close_opportunity(cls, owner_uid, opportunity_id, outcome, lost_reason="", invoice_id="", sandbox=True):
        opportunity = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox)
        if not opportunity:
            return False, "Oportunidad no encontrada."

        stage = "Ganada" if outcome == "ganada" else "Perdida"
        updates = {
            **opportunity,
            "stage": stage,
            "status": outcome,
            "lostReason": lost_reason if outcome == "perdida" else "",
            "invoiceId": invoice_id or opportunity.get("invoiceId", ""),
            "closedAt": _now_iso(),
        }
        saved = cls.save_opportunity(owner_uid, opportunity_id, updates, sandbox=sandbox)
        cls._record_opportunity_interaction(owner_uid, saved, sandbox=sandbox)
        return True, "Oportunidad cerrada correctamente."

    @classmethod
    def mark_contact_opportunities_won(cls, owner_uid, contact_id, invoice_id="", invoice_number="", sandbox=True):
        if not contact_id:
            return 0
        open_opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, include_closed=False, contact_id=contact_id)
        updated = 0
        for opportunity in open_opportunities:
            if opportunity.get("stage") == "Perdida":
                continue
            opportunity["stage"] = "Ganada"
            opportunity["status"] = "ganada"
            opportunity["invoiceId"] = invoice_id or opportunity.get("invoiceId", "")
            opportunity["invoiceNumber"] = invoice_number or opportunity.get("invoiceNumber", "")
            opportunity["closedAt"] = _now_iso()
            cls.save_opportunity(owner_uid, opportunity["id"], opportunity, sandbox=sandbox)
            cls._record_opportunity_interaction(owner_uid, opportunity, sandbox=sandbox)
            updated += 1
        return updated

    @classmethod
    def get_activity(cls, owner_uid, activity_id, sandbox=True):
        if not firebase_initialized:
            return None
        try:
            doc = db_firestore.collection("users").document(owner_uid).collection(_activity_coll(sandbox)).document(activity_id).get()
            if doc.exists:
                data = doc.to_dict() or {}
                data["id"] = doc.id
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                return _annotate_activity(cls._normalize_activity(data))
        except Exception as e:
            print(f"⚠️ Error al obtener actividad CRM {activity_id}: {e}")
        return None

    @classmethod
    def get_activities(cls, owner_uid, sandbox=True, include_completed=True, contact_id=None, opportunity_id=None, branch_id=None, project_id=None):
        activities = []
        if firebase_initialized:
            try:
                docs = db_firestore.collection("users").document(owner_uid).collection(_activity_coll(sandbox)).get()
                for doc in docs:
                    data = doc.to_dict() or {}
                    data["id"] = doc.id
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
    def save_activity(cls, owner_uid, activity_id, activity_dict, sandbox=True):
        activity_id = activity_id or activity_dict.get("id") or str(uuid.uuid4())
        existing = cls.get_activity(owner_uid, activity_id, sandbox=sandbox) or {}

        contact_id = activity_dict.get("contactId") or existing.get("contactId", "")
        contact_name = activity_dict.get("contactName") or existing.get("contactName", "")
        contact = _resolve_contact(owner_uid, contact_id, sandbox=sandbox)
        if contact:
            contact_name = contact.get("razonSocial", contact_name)

        opportunity_id = activity_dict.get("opportunityId") or existing.get("opportunityId", "")
        opportunity_title = activity_dict.get("opportunityTitle") or existing.get("opportunityTitle", "")
        if opportunity_id:
            opportunity = cls.get_opportunity(owner_uid, opportunity_id, sandbox=sandbox)
            if opportunity:
                opportunity_title = opportunity.get("title", opportunity_title)
                if not contact_id:
                    contact_id = opportunity.get("contactId", "")
                    contact_name = opportunity.get("contactName", "")

        assigned_to = activity_dict.get("assignedTo") or existing.get("assignedTo", "")
        assigned_to_name = activity_dict.get("assignedToName") or _resolve_team_member_name(owner_uid, assigned_to)
        activity_type = _normalize_activity_type(activity_dict.get("type") or existing.get("type"))
        title = (activity_dict.get("title") or existing.get("title") or activity_type).strip()

        data = {
            **existing,
            **activity_dict,
            "id": activity_id,
            "ownerUID": owner_uid,
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
        data = _model_dump(CRMActivity(**data))

        if firebase_initialized:
            try:
                db_firestore.collection("users").document(owner_uid).collection(_activity_coll(sandbox)).document(activity_id).set(data)
            except Exception as e:
                print(f"⚠️ Error al guardar actividad CRM: {e}")

        cls._sync_activity_to_contact(owner_uid, data, sandbox=sandbox)
        return _annotate_activity(data)

    @classmethod
    def complete_activity(cls, owner_uid, activity_id, sandbox=True):
        activity = cls.get_activity(owner_uid, activity_id, sandbox=sandbox)
        if not activity:
            return False, "Actividad no encontrada."
        activity["status"] = "completada"
        activity["completedAt"] = _now_iso()
        cls.save_activity(owner_uid, activity_id, activity, sandbox=sandbox)

        contact_id = activity.get("contactId")
        if contact_id:
            try:
                contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
                if contact and _date_key(contact.get("nextContactDate")) == _date_key(activity.get("dueDate")):
                    contact["nextContactDate"] = ""
                    ContactService.save_contact(owner_uid, contact_id, contact, sandbox=sandbox)
            except Exception:
                pass

        return True, "Actividad completada."

    @classmethod
    def delete_activity(cls, owner_uid, activity_id, sandbox=True):
        activity = cls.get_activity(owner_uid, activity_id, sandbox=sandbox)
        if firebase_initialized:
            try:
                db_firestore.collection("users").document(owner_uid).collection(_activity_coll(sandbox)).document(activity_id).delete()
            except Exception as e:
                print(f"⚠️ Error al eliminar actividad CRM: {e}")
                return False
        if activity and activity.get("contactId"):
            try:
                DatabaseService.delete_client_interaction(owner_uid, activity["contactId"], activity_id, sandbox=sandbox)
            except Exception:
                pass
        return True

    @classmethod
    def get_pipeline(cls, owner_uid, sandbox=True):
        opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, include_closed=True)
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
    def get_leads(cls, owner_uid, sandbox=True):
        contacts = [c for c in ContactService.get_contacts(owner_uid, sandbox=sandbox) if "cliente" in c.get("types", [])]
        quotations = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=True)
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
        open_activities = cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False)

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
    def get_dashboard(cls, owner_uid, sandbox=True):
        opportunities = cls.get_opportunities(owner_uid, sandbox=sandbox, include_closed=True)
        open_opps = [o for o in opportunities if o.get("status") == "abierta"]
        won_opps = [o for o in opportunities if o.get("status") == "ganada"]
        lost_opps = [o for o in opportunities if o.get("status") == "perdida"]
        activities = cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False)
        leads = cls.get_leads(owner_uid, sandbox=sandbox)
        pipeline = cls.get_pipeline(owner_uid, sandbox=sandbox)

        closed_total = len(won_opps) + len(lost_opps)
        win_rate = (len(won_opps) / closed_total * 100.0) if closed_total else 0.0
        pipeline_value = sum(_safe_float(o.get("amount")) for o in open_opps)
        weighted_value = sum(_safe_float(o.get("amount")) * (_safe_float(o.get("probability")) / 100.0) for o in open_opps)
        overdue = [a for a in activities if a.get("isOverdue")]
        today = [a for a in activities if a.get("isDueToday")]

        suggestions = cls.get_next_action_suggestions(owner_uid, sandbox=sandbox, opportunities=open_opps, leads=leads, activities=activities)

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
    def get_next_action_suggestions(cls, owner_uid, sandbox=True, opportunities=None, leads=None, activities=None):
        opportunities = opportunities if opportunities is not None else cls.get_opportunities(owner_uid, sandbox=sandbox, include_closed=False)
        leads = leads if leads is not None else cls.get_leads(owner_uid, sandbox=sandbox)
        activities = activities if activities is not None else cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False)

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

    @classmethod
    def get_global_commitments(cls, owner_uid, sandbox=True):
        contacts = [c for c in ContactService.get_contacts(owner_uid, sandbox=sandbox) if "cliente" in c.get("types", [])]
        contact_map = {c["id"]: c for c in contacts}
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
        real_invoices = [inv for inv in invoices if not inv.get("isQuotation") and inv.get("status") not in ["Anulada", "Borrador", "Pagado pero no emitido"]]
        today = _today_str()
        commitments = []

        for contact in contacts:
            c_sales = [inv for inv in real_invoices if inv.get("clientId") == contact["id"]]
            total_cxc = sum(_safe_float(inv.get("netPayable")) for inv in c_sales if inv.get("status") in ["Emitida", "Vencida", "Parcialmente Cobrada"])
            if (_date_key(contact.get("nextContactDate")) == today) or total_cxc > 0.0:
                item = contact.copy()
                item["total_cxc"] = round(total_cxc, 2)
                item["crmNotes"] = item.get("crmNotes") or item.get("notes", "")
                item["commitmentType"] = "contact"
                commitments.append(item)

        for activity in cls.get_activities(owner_uid, sandbox=sandbox, include_completed=False):
            if not activity.get("isOverdue") and not activity.get("isDueToday"):
                continue
            contact = contact_map.get(activity.get("contactId"), {})
            commitments.append({
                "id": activity.get("contactId") or activity["id"],
                "activityId": activity["id"],
                "razonSocial": activity.get("contactName") or contact.get("razonSocial") or activity.get("title"),
                "telefono": contact.get("telefono") or contact.get("celular", ""),
                "crmNotes": activity.get("description") or activity.get("title"),
                "total_cxc": 0.0,
                "nextContactDate": activity.get("dueDate"),
                "commitmentType": "activity",
                "activityType": activity.get("type"),
                "isOverdue": activity.get("isOverdue", False),
            })

        commitments.sort(key=lambda c: (not c.get("isOverdue", False), _date_key(c.get("nextContactDate")) or today, c.get("razonSocial", "").lower()))
        return commitments[:20]

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
        data["stage"] = stage
        data["status"] = status
        data["amount"] = _safe_float(data.get("amount"))
        data["probability"] = _safe_int(data.get("probability"), CRM_STAGE_PROBABILITY.get(stage, 10))
        data["expectedCloseDate"] = _date_key(data.get("expectedCloseDate"))
        data["createdAt"] = serialize_field(data.get("createdAt"))
        data["updatedAt"] = serialize_field(data.get("updatedAt"))
        data["closedAt"] = serialize_field(data.get("closedAt"))
        data["weightedAmount"] = round(data["amount"] * (data["probability"] / 100.0), 2)
        return data

    @classmethod
    def _normalize_activity(cls, data):
        data["type"] = _normalize_activity_type(data.get("type"))
        data["priority"] = _normalize_priority(data.get("priority"))
        data["status"] = _normalize_status(data.get("status"))
        data["dueDate"] = _date_key(data.get("dueDate"))
        data["createdAt"] = serialize_field(data.get("createdAt"))
        data["updatedAt"] = serialize_field(data.get("updatedAt"))
        data["completedAt"] = serialize_field(data.get("completedAt"))
        return data

    @classmethod
    def _sync_activity_to_contact(cls, owner_uid, activity, sandbox=True):
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
            DatabaseService.save_client_interaction(owner_uid, contact_id, activity["id"], interaction_dict, sandbox=sandbox)
        except Exception:
            pass

        if activity.get("dueDate") and activity.get("status") == "pendiente":
            try:
                contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
                if contact:
                    current_due = _date_key(contact.get("nextContactDate"))
                    if not current_due or activity["dueDate"] <= current_due:
                        contact["nextContactDate"] = activity["dueDate"]
                        ContactService.save_contact(owner_uid, contact_id, contact, sandbox=sandbox)
            except Exception:
                pass

    @classmethod
    def _record_opportunity_interaction(cls, owner_uid, opportunity, sandbox=True):
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
            }, sandbox=sandbox)
        except Exception:
            pass
