"""Motor de Automatizaciones CRM (Fase 4.2).

Gestiona reglas de automatización configurables, tenant-aware e idempotentes
para el ciclo de vida de oportunidades, actividades y seguimiento de SLA.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.models.crm import CRMAutomationRule
from app.services.db_service import (
    DatabaseService,
    _company_coll,
    firebase_initialized,
    serialize_field,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _require_company_id(company_id):
    if not company_id:
        raise ValueError("company_id es requerido para operaciones de automatización CRM.")
    return str(company_id)


def _rules_coll_name(sandbox=True):
    return "sandbox_crm_automation_rules" if sandbox else "crm_automation_rules"


class CRMAutomationService:
    """Servicio para persistencia, evaluación y ejecución de reglas de automatización CRM."""

    @classmethod
    def get_rule(cls, owner_uid, rule_id, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        if not firebase_initialized or not rule_id:
            return None
        try:
            doc = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=_rules_coll_name(sandbox)).document(rule_id).get()
            if doc.exists:
                data = doc.to_dict()
                if not data.get("isDeleted"):
                    data["id"] = doc.id
                    return data
        except Exception as e:
            print(f"⚠️ Error al obtener regla de automatización {rule_id}: {e}")
        return None

    @classmethod
    def get_rules(cls, owner_uid, sandbox=True, company_id=None, enabled_only=False):
        company_id = _require_company_id(company_id)
        if not firebase_initialized:
            return []
        try:
            docs = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=_rules_coll_name(sandbox)).get()
            rules = []
            for doc in docs:
                d = doc.to_dict() or {}
                if d.get("isDeleted"):
                    continue
                d["id"] = doc.id
                d["companyId"] = company_id
                if enabled_only and not d.get("enabled", True):
                    continue
                rules.append(d)
            return rules
        except Exception as e:
            print(f"⚠️ Error al listar reglas de automatización: {e}")
            return []

    @classmethod
    def save_rule(cls, owner_uid, rule_id, rule_dict, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        rule_id = rule_id or rule_dict.get("id") or str(uuid.uuid4())
        existing = cls.get_rule(owner_uid, rule_id, sandbox=sandbox, company_id=company_id) or {}

        data = {
            **existing,
            **rule_dict,
            "id": rule_id,
            "ownerUID": owner_uid,
            "companyId": company_id,
            "name": (rule_dict.get("name") or existing.get("name") or "Regla CRM").strip(),
            "description": rule_dict.get("description") or existing.get("description", ""),
            "trigger": rule_dict.get("trigger") or existing.get("trigger", "stage_change"),
            "fromStage": rule_dict.get("fromStage") or existing.get("fromStage", ""),
            "toStage": rule_dict.get("toStage") or existing.get("toStage", ""),
            "staleDays": int(rule_dict.get("staleDays") or existing.get("staleDays") or 7),
            "action": rule_dict.get("action") or existing.get("action", "create_activity"),
            "activityType": rule_dict.get("activityType") or existing.get("activityType", "Seguimiento"),
            "activityTitle": rule_dict.get("activityTitle") or existing.get("activityTitle", ""),
            "daysOffset": int(rule_dict.get("daysOffset") if rule_dict.get("daysOffset") is not None else existing.get("daysOffset", 1)),
            "enabled": bool(rule_dict.get("enabled", existing.get("enabled", True))),
            "isDeleted": bool(rule_dict.get("isDeleted", existing.get("isDeleted", False))),
            "createdAt": existing.get("createdAt") or _now_iso(),
            "updatedAt": _now_iso(),
        }

        if firebase_initialized:
            try:
                _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=_rules_coll_name(sandbox)).document(rule_id).set(data)
            except Exception as e:
                print(f"⚠️ Error al guardar regla de automatización {rule_id}: {e}")

        return data

    @classmethod
    def delete_rule(cls, owner_uid, rule_id, sandbox=True, company_id=None):
        company_id = _require_company_id(company_id)
        rule = cls.get_rule(owner_uid, rule_id, sandbox=sandbox, company_id=company_id)
        if not rule:
            return False
        rule["isDeleted"] = True
        rule["deletedAt"] = _now_iso()
        rule["enabled"] = False
        cls.save_rule(owner_uid, rule_id, rule, sandbox=sandbox, company_id=company_id)
        return True

    @classmethod
    def evaluate_rules(cls, owner_uid, event_type, payload, sandbox=True, company_id=None):
        """
        Evalúa y ejecuta de forma idempotente las reglas aplicables para un evento.
        Retorna la lista de resultados/acciones ejecutadas.
        """
        company_id = _require_company_id(company_id)
        results = []

        # Validaciones de integridad sobre el payload
        opp = payload.get("opportunity") or {}
        if opp.get("isDeleted"):
            return results

        contact = payload.get("contact") or {}
        if contact.get("isDeleted"):
            return results

        # Validar tenant de la entidad
        opp_cid = opp.get("companyId")
        if opp_cid and str(opp_cid) != str(company_id):
            return results

        # Obtener reglas activas del tenant
        rules = cls.get_rules(owner_uid, sandbox=sandbox, company_id=company_id, enabled_only=True)

        for rule in rules:
            if rule.get("companyId") != company_id:
                continue
            if not rule.get("enabled", True) or rule.get("isDeleted"):
                continue

            rule_trigger = rule.get("trigger")
            matches = False

            if event_type == "stage_change" and rule_trigger == "stage_change":
                to_stage = payload.get("to_stage", "")
                from_stage = payload.get("from_stage", "")
                rule_to = rule.get("toStage", "")
                rule_from = rule.get("fromStage", "")

                if (not rule_to or rule_to == to_stage) and (not rule_from or rule_from == from_stage):
                    matches = True

            elif event_type == "opportunity_won" and (rule_trigger in ("opportunity_won", "stage_change")):
                if rule_trigger == "opportunity_won" or rule.get("toStage") == "Ganada":
                    matches = True

            elif event_type == "opportunity_lost" and (rule_trigger in ("opportunity_lost", "stage_change")):
                if rule_trigger == "opportunity_lost" or rule.get("toStage") == "Perdida":
                    matches = True

            elif event_type == "opportunity_stale" and rule_trigger == "opportunity_stale":
                stale_days = payload.get("days_stale", 0)
                rule_stale_days = int(rule.get("staleDays", 7))
                if stale_days >= rule_stale_days:
                    matches = True

            elif event_type == "activity_overdue" and rule_trigger == "activity_overdue":
                matches = True

            if matches:
                res = cls.execute_rule(owner_uid, rule, payload, sandbox=sandbox, company_id=company_id)
                if res:
                    results.append(res)

        return results

    @classmethod
    def execute_rule(cls, owner_uid, rule, event_payload, sandbox=True, company_id=None):
        """Ejecuta una regla individual de manera idempotente y tenant-safe."""
        from app.services.crm_service import CRMService

        company_id = _require_company_id(company_id)
        rule_company = rule.get("companyId")
        if rule_company and str(rule_company) != str(company_id):
            return None

        if not rule.get("enabled", True) or rule.get("isDeleted"):
            return None

        action = rule.get("action", "create_activity")
        rule_id = rule.get("id", str(uuid.uuid4()))
        opp = event_payload.get("opportunity") or {}
        opp_id = opp.get("id") or event_payload.get("opportunity_id", "")
        contact_id = opp.get("contactId") or event_payload.get("contact_id", "")
        to_stage = event_payload.get("to_stage", opp.get("stage", ""))

        if action == "create_activity":
            days_offset = int(rule.get("daysOffset", 1))
            target_date = datetime.now(timezone.utc).date() + timedelta(days=days_offset)
            due_date_str = target_date.strftime("%Y-%m-%d")

            # Clave de idempotencia única por regla, oportunidad y etapa/fecha
            idempotency_key = f"auto_{rule_id}_{opp_id}_{to_stage}_{due_date_str}"

            # Verificar si ya existe una actividad pendiente idéntica para evitar duplicados
            existing_activities = CRMService.get_activities(owner_uid, sandbox=sandbox, company_id=company_id)
            for act in existing_activities:
                if act.get("opportunityId") == opp_id and act.get("status") == "pendiente":
                    if act.get("idempotencyKey") == idempotency_key or (
                        act.get("originRuleId") == rule_id and act.get("dueDate") == due_date_str
                    ):
                        # Idempotente: ya existe actividad generada por esta regla
                        return {"success": True, "action": "create_activity", "skipped": True, "activity": act, "reason": "already_exists"}

            act_type = rule.get("activityType", "Seguimiento")
            rule_name = rule.get("name") or "Regla CRM"
            title = rule.get("activityTitle") or f"Seguimiento: {opp.get('title') or 'Oportunidad'}"
            desc = f"Actividad creada automáticamente por la regla '{rule_name}'."

            new_activity = {
                "companyId": company_id,
                "opportunityId": opp_id,
                "opportunityTitle": opp.get("title", ""),
                "contactId": contact_id,
                "contactName": opp.get("contactName", ""),
                "assignedTo": opp.get("assignedTo", ""),
                "branchId": opp.get("branchId", "default-sucursal-principal"),
                "projectId": opp.get("projectId"),
                "type": act_type,
                "title": title,
                "description": desc,
                "dueDate": due_date_str,
                "priority": "media",
                "status": "pendiente",
                "originRuleId": rule_id,
                "idempotencyKey": idempotency_key,
                "autoGenerated": True,
            }

            saved_act = CRMService.save_activity(owner_uid, None, new_activity, sandbox=sandbox, company_id=company_id)
            return {"success": True, "action": "create_activity", "activity": saved_act, "idempotencyKey": idempotency_key}

        elif action == "close_pending_activities":
            # Cerrar actividades pendientes de la oportunidad preservando historial
            if not opp_id:
                return None

            all_acts = CRMService.get_activities(owner_uid, sandbox=sandbox, company_id=company_id)
            closed_count = 0
            for act in all_acts:
                if act.get("opportunityId") == opp_id and act.get("status") == "pendiente" and not act.get("isDeleted"):
                    act_id = act["id"]
                    act["status"] = "cancelada"
                    act["completedAt"] = _now_iso()
                    act["description"] = f"{act.get('description', '')}\n[Auto-cerrada: Oportunidad {to_stage}]".strip()
                    CRMService.save_activity(owner_uid, act_id, act, sandbox=sandbox, company_id=company_id)
                    closed_count += 1

            return {"success": True, "action": "close_pending_activities", "closed_count": closed_count}

        elif action == "generate_alert":
            # Alerta registrada en la oportunidad
            if opp_id:
                opp_full = CRMService.get_opportunity(owner_uid, opp_id, sandbox=sandbox, company_id=company_id)
                if opp_full:
                    alert_msg = f"[ALERTA AUTOMÁTICA]: {rule.get('name', 'SLA CRM')} - {event_payload.get('stale_reason', 'Revisión requerida')}"
                    opp_full["notes"] = f"{opp_full.get('notes', '')}\n[{_today_str()} - Sistema]: {alert_msg}".strip()
                    CRMService.save_opportunity(owner_uid, opp_id, opp_full, sandbox=sandbox, company_id=company_id)
            return {"success": True, "action": "generate_alert", "opportunityId": opp_id}

        return None

    @classmethod
    def process_stale_opportunities(cls, owner_uid, sandbox=True, company_id=None, threshold_days=7, today_str=None):
        """Escanea oportunidades estancadas y dispara las reglas de automatización correspondientes."""
        from app.services.crm_service import CRMService

        company_id = _require_company_id(company_id)
        stale_opps = CRMService.get_stale_opportunities(
            owner_uid,
            sandbox=sandbox,
            company_id=company_id,
            threshold_days=threshold_days,
            today_str=today_str,
        )

        results = []
        for opp in stale_opps:
            payload = {
                "opportunity": opp,
                "opportunity_id": opp.get("id"),
                "days_stale": opp.get("daysSinceLastActivity", threshold_days),
                "stale_reason": opp.get("staleReason", "no_activity"),
            }
            res = cls.evaluate_rules(owner_uid, "opportunity_stale", payload, sandbox=sandbox, company_id=company_id)
            results.extend(res)

        return results
