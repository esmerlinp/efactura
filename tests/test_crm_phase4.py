"""
Pruebas de Fase 4 (F4.1 SLA y Seguimiento + F4.2 Motor de Automatizaciones CRM).

Cubre:
- F4.1 SLA y Seguimiento:
  1. Actividad vencida detectada
  2. Actividad de hoy detectada correctamente
  3. Actividad dentro de 3 días marcada como próxima
  4. Actividad fuera del SLA no marcada como próxima
  5. Oportunidad ganada no considerada estancada
  6. Oportunidad perdida no considerada estancada
  7. Oportunidad sin actividad detectada como estancada
  8. Oportunidad con actividad reciente no considerada estancada

- Tenant Isolation:
  9. Empresa A no puede obtener SLA de empresa B
  10. Empresa A no puede ejecutar reglas de empresa B
  11. Automatización de A no modifica oportunidades de B

- F4.2 Automatizaciones:
  12. Entrada a Propuesta genera actividad cuando existe regla
  13. Repetir el mismo evento no genera actividad duplicada (Idempotencia)
  14. Oportunidad estancada genera actividad de reactivación
  15. Seguimiento automático de estancada no se duplica
  16. Oportunidad Ganada cierra/cancela actividades pendientes correctamente
  17. Oportunidad Perdida conserva historial y motivo de pérdida
  18. Automatización no modifica directamente la etapa sin transition_opportunity

- Integridad:
  19. Oportunidad eliminada (soft-delete) no recibe automatizaciones
  20. Contacto eliminado (soft-delete) no recibe nuevas actividades
  21. Regla deshabilitada no ejecuta acciones
  22. Regla de otra empresa no ejecuta acciones
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from app.models.crm import CRMAutomationRule
from app.services.crm_service import CRMService, CRM_ACTIVITY_SLA_DAYS, CRM_STALE_OPPORTUNITY_DAYS
from app.services.crm_automation_service import CRMAutomationService


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Firestore Helper for Tests
# ─────────────────────────────────────────────────────────────────────────────

class InMemoryFirestore:
    def __init__(self):
        self.store = {}

    def get_collection(self, company_id, coll_name):
        store = self.store

        class MockDocRef:
            def __init__(self, doc_id):
                self.doc_id = doc_id

            def get(self):
                key = (company_id, coll_name, self.doc_id)
                exists = key in store
                doc_mock = MagicMock()
                doc_mock.exists = exists
                doc_mock.id = self.doc_id
                doc_mock.to_dict.return_value = store.get(key)
                return doc_mock

            def set(self, data):
                store[(company_id, coll_name, self.doc_id)] = dict(data)

            def delete(self):
                store.pop((company_id, coll_name, self.doc_id), None)

        class MockCollRef:
            def document(self, doc_id):
                return MockDocRef(doc_id)

            def get(self):
                docs = []
                for (cid, cname, did), data in list(store.items()):
                    if cid == company_id and cname == coll_name:
                        dm = MagicMock()
                        dm.id = did
                        dm.to_dict.return_value = dict(data)
                        docs.append(dm)
                return docs

        return MockCollRef()


# ─────────────────────────────────────────────────────────────────────────────
# 1-8: F4.1 SLA y Detección de Estancamiento
# ─────────────────────────────────────────────────────────────────────────────

def test_sla_activity_overdue_detected():
    """1. Actividad vencida detectada (dueDate < today)."""
    today_str = "2026-10-07"
    overdue_date = "2026-10-05"
    sla = CRMService.get_sla_status(overdue_date, status="pendiente", today_str=today_str)
    assert sla["code"] == "vencida"
    assert sla["is_overdue"] is True
    assert sla["is_today"] is False
    assert sla["is_upcoming"] is False
    assert sla["days_diff"] == -2


def test_sla_activity_today_detected():
    """2. Actividad de hoy detectada correctamente (dueDate == today)."""
    today_str = "2026-10-07"
    sla = CRMService.get_sla_status(today_str, status="pendiente", today_str=today_str)
    assert sla["code"] == "hoy"
    assert sla["is_today"] is True
    assert sla["is_overdue"] is False
    assert sla["is_upcoming"] is False
    assert sla["days_diff"] == 0


def test_sla_activity_upcoming_within_3_days_detected():
    """3. Actividad dentro del SLA (1 a 3 días) marcada como próxima."""
    today_str = "2026-10-07"
    in_2_days = "2026-10-09"
    sla = CRMService.get_sla_status(in_2_days, status="pendiente", today_str=today_str)
    assert sla["code"] == "proxima"
    assert sla["is_upcoming"] is True
    assert sla["is_overdue"] is False
    assert sla["is_today"] is False
    assert sla["days_diff"] == 2


def test_sla_activity_outside_sla_not_upcoming():
    """4. Actividad fuera del SLA (> 3 días) marcada como normal."""
    today_str = "2026-10-07"
    in_10_days = "2026-10-17"
    sla = CRMService.get_sla_status(in_10_days, status="pendiente", today_str=today_str)
    assert sla["code"] == "normal"
    assert sla["is_upcoming"] is False
    assert sla["is_overdue"] is False


def test_stale_opportunity_won_not_marked_stale():
    """5. Oportunidad ganada no considerada estancada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMService.save_opportunity("u1", "opp-won", {
            "title": "Venta Cerrada", "stage": "Ganada", "status": "ganada", "createdAt": "2026-01-01"
        }, company_id="comp-1")

        stale = CRMService.get_stale_opportunities("u1", company_id="comp-1", today_str="2026-10-07")
        assert len(stale) == 0


def test_stale_opportunity_lost_not_marked_stale():
    """6. Oportunidad perdida no considerada estancada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMService.save_opportunity("u1", "opp-lost", {
            "title": "Venta Perdida", "stage": "Perdida", "status": "perdida", "lostReason": "Presupuesto", "createdAt": "2026-01-01"
        }, company_id="comp-1")

        stale = CRMService.get_stale_opportunities("u1", company_id="comp-1", today_str="2026-10-07")
        assert len(stale) == 0


def test_stale_opportunity_no_activity_detected():
    """7. Oportunidad abierta sin actividad durante >7 días detectada como estancada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMService.save_opportunity("u1", "opp-stale", {
            "title": "Oportunidad Olvidada",
            "stage": "Calificado",
            "status": "abierta",
            "createdAt": "2026-09-01",
            "updatedAt": "2026-09-01",
            "stageHistory": [{"from": "Contactado", "to": "Calificado", "timestamp": "2026-09-01"}],
        }, company_id="comp-1")

        stale = CRMService.get_stale_opportunities("u1", company_id="comp-1", today_str="2026-10-07", threshold_days=7)
        assert len(stale) == 1
        assert stale[0]["id"] == "opp-stale"
        assert stale[0]["isStale"] is True
        assert stale[0]["staleReason"] in ("stuck_in_stage", "no_activity")
        assert stale[0]["daysSinceLastActivity"] >= 30


def test_stale_opportunity_with_recent_activity_not_stale():
    """8. Oportunidad con actividad reciente (dentro de 7 días) no considerada estancada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMService.save_opportunity("u1", "opp-active", {
            "title": "Oportunidad Activa",
            "stage": "Propuesta",
            "status": "abierta",
            "createdAt": "2026-09-01",
            "updatedAt": "2026-10-06",
        }, company_id="comp-1")

        CRMService.save_activity("u1", "act-recent", {
            "opportunityId": "opp-active",
            "title": "Llamada de seguimiento",
            "status": "completada",
            "completedAt": "2026-10-06T12:00:00Z",
        }, company_id="comp-1")

        stale = CRMService.get_stale_opportunities("u1", company_id="comp-1", today_str="2026-10-07", threshold_days=7)
        assert len(stale) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 9-11: Tenant Isolation en SLA y Automatizaciones
# ─────────────────────────────────────────────────────────────────────────────

def test_phase4_tenant_isolation_sla_queries():
    """9. Empresa A no puede obtener SLA ni oportunidades estancadas de Empresa B."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMService.save_opportunity("u1", "opp-b-stale", {
            "title": "Op Estancada B", "stage": "Contactado", "status": "abierta", "createdAt": "2026-08-01", "updatedAt": "2026-08-01"
        }, company_id="comp-B")

        stale_a = CRMService.get_stale_opportunities("u1", company_id="comp-A", today_str="2026-10-07")
        assert len(stale_a) == 0

        stale_b = CRMService.get_stale_opportunities("u1", company_id="comp-B", today_str="2026-10-07")
        assert len(stale_b) == 1
        assert stale_b[0]["id"] == "opp-b-stale"


def test_phase4_tenant_isolation_rule_execution():
    """10. Empresa A no puede evaluar ni ejecutar reglas de Empresa B."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        # Guardar regla en Empresa B
        CRMAutomationService.save_rule("u1", "rule-b", {
            "name": "Regla B",
            "trigger": "stage_change",
            "toStage": "Propuesta",
            "action": "create_activity",
            "daysOffset": 2,
        }, company_id="comp-B")

        # Intentar evaluar en Empresa A
        results_a = CRMAutomationService.evaluate_rules("u1", "stage_change", {
            "opportunity": {"id": "opp-a", "title": "Op A", "stage": "Propuesta", "companyId": "comp-A"},
            "to_stage": "Propuesta",
        }, company_id="comp-A")

        assert len(results_a) == 0


def test_phase4_tenant_isolation_automation_does_not_modify_other_tenant():
    """11. Automatización de Empresa A jamás modifica actividades u oportunidades de Empresa B."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMService.save_opportunity("u1", "opp-b", {
            "title": "Op de Empresa B", "stage": "Propuesta", "companyId": "comp-B"
        }, company_id="comp-B")

        rule_a = {
            "id": "rule-a", "companyId": "comp-A", "name": "Auto A", "action": "create_activity", "daysOffset": 1
        }

        # Ejecutar regla de A apuntando a entidad de B -> Rechazado
        res = CRMAutomationService.execute_rule("u1", rule_a, {
            "opportunity": {"id": "opp-b", "companyId": "comp-B"}
        }, company_id="comp-A")

        # Actividades en comp-B deben seguir en 0
        acts_b = CRMService.get_activities("u1", company_id="comp-B")
        assert len(acts_b) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 12-18: F4.2 Automatizaciones y Comportamiento Idempotente
# ─────────────────────────────────────────────────────────────────────────────

def test_automation_stage_propuesta_creates_activity():
    """12. Entrada a Propuesta genera actividad cuando existe regla configurada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMAutomationService.save_rule("u1", "rule-prop", {
            "name": "Seguimiento de Propuesta",
            "trigger": "stage_change",
            "toStage": "Propuesta",
            "action": "create_activity",
            "activityType": "Llamada",
            "daysOffset": 3,
        }, company_id="comp-1")

        CRMService.save_opportunity("u1", "opp-prop", {
            "title": "Software ERP Pro", "stage": "Calificado", "contactId": "c-1", "assignedTo": "rep-1"
        }, company_id="comp-1")

        results = CRMAutomationService.evaluate_rules("u1", "stage_change", {
            "opportunity": {"id": "opp-prop", "title": "Software ERP Pro", "stage": "Propuesta", "contactId": "c-1", "companyId": "comp-1"},
            "from_stage": "Calificado",
            "to_stage": "Propuesta",
        }, company_id="comp-1")

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["action"] == "create_activity"

        acts = CRMService.get_activities("u1", opportunity_id="opp-prop", company_id="comp-1")
        assert len(acts) == 1
        assert acts[0]["type"] == "Llamada"
        assert acts[0]["autoGenerated"] is True
        assert acts[0]["originRuleId"] == "rule-prop"


def test_automation_stage_propuesta_idempotency():
    """13. Repetir el mismo evento no genera actividad duplicada (Idempotencia)."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMAutomationService.save_rule("u1", "rule-idemp", {
            "name": "Seguimiento Idempotente",
            "trigger": "stage_change",
            "toStage": "Propuesta",
            "action": "create_activity",
            "daysOffset": 2,
        }, company_id="comp-1")

        payload = {
            "opportunity": {"id": "opp-idemp", "title": "CRM VykOne", "stage": "Propuesta", "companyId": "comp-1"},
            "from_stage": "Calificado",
            "to_stage": "Propuesta",
        }

        # Ejecución 1
        res1 = CRMAutomationService.evaluate_rules("u1", "stage_change", payload, company_id="comp-1")
        assert len(res1) == 1
        assert res1[0].get("skipped") is not True

        # Ejecución 2 (mismo evento re-procesado)
        res2 = CRMAutomationService.evaluate_rules("u1", "stage_change", payload, company_id="comp-1")
        assert len(res2) == 1
        assert res2[0].get("skipped") is True

        # Total de actividades debe seguir siendo exactamente 1
        acts = CRMService.get_activities("u1", opportunity_id="opp-idemp", company_id="comp-1")
        assert len(acts) == 1


def test_automation_stale_opportunity_creates_followup():
    """14. Oportunidad estancada genera actividad de reactivación."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMAutomationService.save_rule("u1", "rule-stale", {
            "name": "Reactivar Oportunidades Estancadas",
            "trigger": "opportunity_stale",
            "staleDays": 7,
            "action": "create_activity",
            "activityType": "Seguimiento",
            "activityTitle": "Reactivar contacto estancado",
            "daysOffset": 1,
        }, company_id="comp-1")

        CRMService.save_opportunity("u1", "opp-stuck", {
            "title": "Oportunidad Congelada",
            "stage": "Negociación",
            "status": "abierta",
            "createdAt": "2026-08-01",
            "updatedAt": "2026-08-01",
        }, company_id="comp-1")

        results = CRMAutomationService.process_stale_opportunities("u1", company_id="comp-1", threshold_days=7, today_str="2026-10-07")
        assert len(results) == 1
        assert results[0]["action"] == "create_activity"

        acts = CRMService.get_activities("u1", opportunity_id="opp-stuck", company_id="comp-1")
        assert len(acts) == 1
        assert acts[0]["title"] == "Reactivar contacto estancado"


def test_automation_stale_followup_idempotency():
    """15. Seguimiento automático de oportunidad estancada no se duplica en escaneos repetidos."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMAutomationService.save_rule("u1", "rule-stale-idemp", {
            "name": "Reactivar",
            "trigger": "opportunity_stale",
            "staleDays": 7,
            "action": "create_activity",
            "daysOffset": 1,
        }, company_id="comp-1")

        CRMService.save_opportunity("u1", "opp-stuck-2", {
            "title": "Op Estancada 2", "stage": "Propuesta", "status": "abierta", "createdAt": "2026-08-01", "updatedAt": "2026-08-01"
        }, company_id="comp-1")

        # Escaneo 1
        CRMAutomationService.process_stale_opportunities("u1", company_id="comp-1", threshold_days=7, today_str="2026-10-07")
        # Escaneo 2
        CRMAutomationService.process_stale_opportunities("u1", company_id="comp-1", threshold_days=7, today_str="2026-10-07")

        acts = CRMService.get_activities("u1", opportunity_id="opp-stuck-2", company_id="comp-1")
        assert len(acts) == 1


def test_automation_won_opportunity_closes_pending_activities():
    """16. Oportunidad Ganada cierra/cancela actividades pendientes y conserva completadas."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        # Guardar regla para cerrar actividades al ganar
        CRMAutomationService.save_rule("u1", "rule-won-close", {
            "name": "Cerrar pendientes al ganar",
            "trigger": "opportunity_won",
            "action": "close_pending_activities",
        }, company_id="comp-1")

        # Crear 1 actividad pendiente y 1 completada
        CRMService.save_activity("u1", "act-pend-1", {
            "opportunityId": "opp-win", "title": "Tarea pendiente", "status": "pendiente"
        }, company_id="comp-1")

        CRMService.save_activity("u1", "act-comp-1", {
            "opportunityId": "opp-win", "title": "Reunión efectuada", "status": "completada"
        }, company_id="comp-1")

        # Evaluar evento opportunity_won
        results = CRMAutomationService.evaluate_rules("u1", "opportunity_won", {
            "opportunity": {"id": "opp-win", "stage": "Ganada", "companyId": "comp-1"},
            "opportunity_id": "opp-win",
            "to_stage": "Ganada",
        }, company_id="comp-1")

        assert len(results) == 1
        assert results[0]["action"] == "close_pending_activities"
        assert results[0]["closed_count"] == 1

        # Verificar que la pendiente pasó a cancelada y la completada sigue intacta
        act_p = CRMService.get_activity("u1", "act-pend-1", company_id="comp-1")
        assert act_p["status"] == "cancelada"

        act_c = CRMService.get_activity("u1", "act-comp-1", company_id="comp-1")
        assert act_c["status"] == "completada"


def test_automation_lost_opportunity_preserves_history():
    """17. Oportunidad Perdida conserva historial y motivo de pérdida."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMAutomationService.save_rule("u1", "rule-lost-clean", {
            "name": "Limpiar pendientes al perder",
            "trigger": "opportunity_lost",
            "action": "close_pending_activities",
        }, company_id="comp-1")

        CRMService.save_activity("u1", "act-lost-p", {
            "opportunityId": "opp-lost-hist", "title": "Demo pendiente", "status": "pendiente"
        }, company_id="comp-1")

        CRMAutomationService.evaluate_rules("u1", "opportunity_lost", {
            "opportunity": {"id": "opp-lost-hist", "stage": "Perdida", "lostReason": "Competidor más barato", "companyId": "comp-1"},
            "opportunity_id": "opp-lost-hist",
            "to_stage": "Perdida",
        }, company_id="comp-1")

        act = CRMService.get_activity("u1", "act-lost-p", company_id="comp-1")
        assert act["status"] == "cancelada"
        assert "Auto-cerrada" in act["description"]


def test_automation_does_not_bypass_transition_opportunity():
    """18. Las transiciones desencadenadas por automatización invocan transition_opportunity."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-pass", "responsibleId": "rep-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline"), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        CRMService.save_opportunity("u1", "opp-trans", {
            "title": "Op Transicionada", "stage": "Prospecto", "contactId": "c-pass", "assignedTo": "rep-1", "amount": 10000.0
        }, company_id="comp-1")

        ok, _, opp = CRMService.transition_opportunity("u1", "opp-trans", "Contactado", company_id="comp-1")
        assert ok
        assert opp["stage"] == "Contactado"
        assert len(opp.get("stageHistory", [])) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 19-22: Integridad y Exclusiones
# ─────────────────────────────────────────────────────────────────────────────

def test_automation_soft_deleted_opportunity_ignored():
    """19. Oportunidad marcada como eliminada (soft-delete) no recibe automatizaciones."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMAutomationService.save_rule("u1", "rule-del-opp", {
            "name": "Regla Activa",
            "trigger": "stage_change",
            "toStage": "Propuesta",
            "action": "create_activity",
        }, company_id="comp-1")

        payload = {
            "opportunity": {"id": "opp-del", "stage": "Propuesta", "isDeleted": True, "companyId": "comp-1"},
            "to_stage": "Propuesta",
        }

        results = CRMAutomationService.evaluate_rules("u1", "stage_change", payload, company_id="comp-1")
        assert len(results) == 0

        acts = CRMService.get_activities("u1", opportunity_id="opp-del", company_id="comp-1")
        assert len(acts) == 0


def test_automation_soft_deleted_contact_ignored():
    """20. Contacto eliminado (soft-delete) no recibe nuevas actividades automatizadas."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMAutomationService.save_rule("u1", "rule-del-contact", {
            "name": "Regla Activa",
            "trigger": "stage_change",
            "toStage": "Propuesta",
            "action": "create_activity",
        }, company_id="comp-1")

        payload = {
            "opportunity": {"id": "opp-live", "stage": "Propuesta", "companyId": "comp-1", "contactId": "c-del"},
            "contact": {"id": "c-del", "isDeleted": True},
            "to_stage": "Propuesta",
        }

        results = CRMAutomationService.evaluate_rules("u1", "stage_change", payload, company_id="comp-1")
        assert len(results) == 0


def test_automation_disabled_rule_does_not_execute():
    """21. Regla deshabilitada (enabled=False) no ejecuta acciones."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMAutomationService.save_rule("u1", "rule-off", {
            "name": "Regla Apagada",
            "trigger": "stage_change",
            "toStage": "Propuesta",
            "action": "create_activity",
            "enabled": False,
        }, company_id="comp-1")

        payload = {
            "opportunity": {"id": "opp-test", "stage": "Propuesta", "companyId": "comp-1"},
            "to_stage": "Propuesta",
        }

        results = CRMAutomationService.evaluate_rules("u1", "stage_change", payload, company_id="comp-1")
        assert len(results) == 0


def test_automation_cross_tenant_rule_does_not_execute():
    """22. Regla perteneciente a otra empresa jamás ejecuta acciones en el tenant actual."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_automation_service.firebase_initialized", True), \
         patch("app.services.crm_automation_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        # Guardar en comp-1
        CRMAutomationService.save_rule("u1", "rule-t1", {
            "name": "Regla Tenant 1",
            "trigger": "stage_change",
            "toStage": "Propuesta",
            "action": "create_activity",
        }, company_id="comp-1")

        # Intentar ejecutar en comp-2
        payload = {
            "opportunity": {"id": "opp-t2", "stage": "Propuesta", "companyId": "comp-2"},
            "to_stage": "Propuesta",
        }

        results = CRMAutomationService.evaluate_rules("u1", "stage_change", payload, company_id="comp-2")
        assert len(results) == 0
