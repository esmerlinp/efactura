"""
Pruebas de Fase 2 para el módulo CRM de VykOne.

Cubre:
1. CRM-16: Máquina de estados formal de Oportunidades y sincronización de Contact.pipelineStage.
2. CRM-09: Validación obligatoria de lostReason en etapa Perdida.
3. CRM-08: Eliminación segura (Soft Delete) de Contactos, Oportunidades y Actividades.
4. CRM-07: Separación de permisos RBAC granulares y compatibilidad retroactiva con canClients.
5. CRM-05 / CRM-06: Ficha canónica 360° del Contacto con timeline consolidado y métricas.
6. CRM-04: Sincronización explícita con clientes legacy (_sync_to_legacy_clients).
7. Aislamiento Multi-Tenant en todas las operaciones de la Fase 2.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.models.crm import (
    VALID_OPPORTUNITY_TRANSITIONS,
    CONTACT_PIPELINE_MAP,
    CRMOpportunity,
    CRMActivity,
)
from app.services.crm_service import CRMService
from app.services.contact_service import ContactService
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission


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
# 1. CRM-16 & CRM-09: Máquina de Estados y Lost Reason
# ─────────────────────────────────────────────────────────────────────────────

def test_transition_prospecto_to_contactado_requires_contact():
    """Prospecto -> Contactado requiere contacto asignado y actualiza Contact.pipelineStage."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    contact_updated = {}

    def fake_update_pipeline(owner_uid, contact_id, pipeline_stage, sandbox=True, company_id=None):
        contact_updated["contact_id"] = contact_id
        contact_updated["pipeline_stage"] = pipeline_stage

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-100", "name": "Acme"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", side_effect=fake_update_pipeline), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction") as mock_interaction:

        # 1. Oportunidad sin contacto asignado
        CRMService.save_opportunity("u1", "opp-1", {"title": "Deal 1", "stage": "Prospecto"}, company_id="comp-1")
        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-1", "Contactado", company_id="comp-1")
        assert not ok
        assert "contacto asignado" in msg

        # 2. Oportunidad con contacto asignado -> exitoso
        CRMService.save_opportunity("u1", "opp-1", {"title": "Deal 1", "stage": "Prospecto", "contactId": "c-100"}, company_id="comp-1")
        ok, msg, opp = CRMService.transition_opportunity("u1", "opp-1", "Contactado", company_id="comp-1")
        assert ok
        assert opp["stage"] == "Contactado"
        assert contact_updated.get("pipeline_stage") == "Contactado"
        mock_interaction.assert_called()


def test_transition_contactado_to_calificado_requires_responsible():
    """Contactado -> Calificado requiere responsable comercial asignado."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1", "responsibleId": ""}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        CRMService.save_opportunity("u1", "opp-2", {
            "title": "Deal 2", "stage": "Contactado", "contactId": "c-1", "assignedTo": ""
        }, company_id="comp-1")

        # Sin responsable comercial
        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-2", "Calificado", company_id="comp-1")
        assert not ok
        assert "responsable comercial" in msg

        # Con responsable asignado
        CRMService.save_opportunity("u1", "opp-2", {
            "title": "Deal 2", "stage": "Contactado", "contactId": "c-1", "assignedTo": "rep-42", "assignedToName": "Carlos Rep"
        }, company_id="comp-1")

        ok, msg, opp = CRMService.transition_opportunity("u1", "opp-2", "Calificado", company_id="comp-1")
        assert ok
        assert opp["stage"] == "Calificado"


def test_transition_calificado_to_propuesta_requires_amount_or_quote():
    """Calificado -> Propuesta requiere monto > 0 o cotización asociada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        # Sin monto ni cotización
        CRMService.save_opportunity("u1", "opp-3", {
            "title": "Deal 3", "stage": "Calificado", "contactId": "c-1", "amount": 0.0
        }, company_id="comp-1")

        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-3", "Propuesta", company_id="comp-1")
        assert not ok
        assert "monto estimado o una cotización" in msg

        # Con cotización asociada
        CRMService.save_opportunity("u1", "opp-3", {
            "title": "Deal 3", "stage": "Calificado", "contactId": "c-1", "amount": 0.0, "quotationNumber": "COT-2026-001"
        }, company_id="comp-1")

        ok, msg, opp = CRMService.transition_opportunity("u1", "opp-3", "Propuesta", company_id="comp-1")
        assert ok
        assert opp["stage"] == "Propuesta"


def test_transition_propuesta_to_negociacion_sets_expected_close_date():
    """Propuesta -> Negociación valida o asigna expectedCloseDate."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        CRMService.save_opportunity("u1", "opp-4", {
            "title": "Deal 4", "stage": "Propuesta", "contactId": "c-1", "amount": 50000.0, "expectedCloseDate": ""
        }, company_id="comp-1")

        ok, msg, opp = CRMService.transition_opportunity("u1", "opp-4", "Negociación", company_id="comp-1")
        assert ok
        assert opp["stage"] == "Negociación"
        assert opp["expectedCloseDate"] != ""


def test_transition_to_ganada_records_invoice_and_100_probability():
    """Negociación -> Ganada establece probabilidad 100%, status 'ganada', closedAt y registro de factura."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        CRMService.save_opportunity("u1", "opp-5", {
            "title": "Deal 5", "stage": "Negociación", "contactId": "c-1", "amount": 100000.0
        }, company_id="comp-1")

        ok, msg, opp = CRMService.transition_opportunity(
            "u1",
            "opp-5",
            "Ganada",
            company_id="comp-1",
            invoice_id="inv-999",
            invoice_number="E3100000001",
            total_amount=100000.0,
        )
        assert ok
        assert opp["stage"] == "Ganada"
        assert opp["status"] == "ganada"
        assert opp["probability"] == 100
        assert opp["closedAt"] != ""
        assert opp["invoiceId"] == "inv-999"
        assert any(i.get("id") == "inv-999" for i in opp.get("invoices", []))


def test_transition_to_perdida_requires_lost_reason_crm_09():
    """Perdida requiere obligatoriamente lostReason no vacío (CRM-09)."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        CRMService.save_opportunity("u1", "opp-6", {
            "title": "Deal 6", "stage": "Negociación", "contactId": "c-1", "amount": 20000.0
        }, company_id="comp-1")

        # Sin lostReason
        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-6", "Perdida", company_id="comp-1", lost_reason="")
        assert not ok
        assert "motivo de pérdida (lostReason) es obligatorio" in msg

        # Con espacios en blanco
        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-6", "Perdida", company_id="comp-1", lost_reason="   ")
        assert not ok
        assert "motivo de pérdida (lostReason) es obligatorio" in msg

        # Con motivo válido
        ok, msg, opp = CRMService.transition_opportunity(
            "u1", "opp-6", "Perdida", company_id="comp-1", lost_reason="Presupuesto insuficiente del cliente"
        )
        assert ok
        assert opp["stage"] == "Perdida"
        assert opp["status"] == "perdida"
        assert opp["probability"] == 0
        assert opp["lostReason"] == "Presupuesto insuficiente del cliente"
        assert opp["closedAt"] != ""


def test_invalid_transitions_rejected():
    """Transiciones no permitidas por la máquina de estados son rechazadas."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}):

        # Prospecto -> Ganada directamente (no permitido)
        CRMService.save_opportunity("u1", "opp-invalid", {
            "title": "Deal Invalid", "stage": "Prospecto", "contactId": "c-1"
        }, company_id="comp-1")

        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-invalid", "Ganada", company_id="comp-1")
        assert not ok
        assert "Transición no permitida" in msg

        # Calificado -> Ganada directamente (no permitido)
        CRMService.save_opportunity("u1", "opp-invalid2", {
            "title": "Deal Invalid 2", "stage": "Calificado", "contactId": "c-1", "assignedTo": "rep-1"
        }, company_id="comp-1")

        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-invalid2", "Ganada", company_id="comp-1")
        assert not ok
        assert "Transición no permitida" in msg


def test_controlled_reopening_from_won_or_lost():
    """Ganada o Perdida pueden reabrirse a Propuesta o Negociación limpiando flags de cierre."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        # 1. Reabrir Perdida -> Negociación
        CRMService.save_opportunity("u1", "opp-reopen", {
            "title": "Deal Reopen",
            "stage": "Perdida",
            "status": "perdida",
            "lostReason": "Competencia más barata",
            "closedAt": "2026-05-01T00:00:00Z",
            "amount": 50000.0,
            "contactId": "c-1",
        }, company_id="comp-1")

        ok, msg, opp = CRMService.transition_opportunity("u1", "opp-reopen", "Negociación", company_id="comp-1")
        assert ok
        assert opp["stage"] == "Negociación"
        assert opp["status"] == "abierta"
        assert opp["closedAt"] == ""
        assert opp["lostReason"] == ""

        # 2. Reabrir Ganada -> Propuesta
        CRMService.save_opportunity("u1", "opp-reopen-won", {
            "title": "Deal Reopen Won",
            "stage": "Ganada",
            "status": "ganada",
            "closedAt": "2026-05-01T00:00:00Z",
            "amount": 50000.0,
            "contactId": "c-1",
        }, company_id="comp-1")

        ok, msg, opp = CRMService.transition_opportunity("u1", "opp-reopen-won", "Propuesta", company_id="comp-1")
        assert ok
        assert opp["stage"] == "Propuesta"
        assert opp["status"] == "abierta"
        assert opp["closedAt"] == ""


def test_transition_idempotency():
    """Transicionar a la misma etapa actual es idempotente y exitoso."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll):

        CRMService.save_opportunity("u1", "opp-idem", {
            "title": "Deal Idem", "stage": "Propuesta", "contactId": "c-1"
        }, company_id="comp-1")

        ok, msg, opp = CRMService.transition_opportunity("u1", "opp-idem", "Propuesta", company_id="comp-1")
        assert ok
        assert "ya se encuentra en la etapa Propuesta" in msg
        assert opp["stage"] == "Propuesta"


# ─────────────────────────────────────────────────────────────────────────────
# 2. CRM-08: Eliminación Segura (Soft Delete) e Integridad Referencial
# ─────────────────────────────────────────────────────────────────────────────

def test_opportunity_soft_delete_and_exclusion_from_pipeline():
    """Oportunidad eliminada mediante soft delete no aparece en consultas ni pipeline."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None):

        CRMService.save_opportunity("u1", "opp-del", {
            "title": "Oportunidad Borrable", "stage": "Propuesta", "amount": 10000.0, "contactId": "c-1"
        }, company_id="comp-1")

        assert CRMService.get_opportunity("u1", "opp-del", company_id="comp-1") is not None

        # Ejecutar Soft Delete
        res = CRMService.delete_opportunity("u1", "opp-del", company_id="comp-1", deleted_by="Admin Test")
        assert res is True

        # Ya no debe retornar en get_opportunity
        assert CRMService.get_opportunity("u1", "opp-del", company_id="comp-1") is None

        # Ya no debe aparecer en listado get_opportunities
        opps = CRMService.get_opportunities("u1", company_id="comp-1")
        assert not any(o["id"] == "opp-del" for o in opps)

        # En la persistencia cruda, debe conservar flags de auditoría
        raw_doc = fake_fs.get_collection("comp-1", "sandbox_crm_opportunities").document("opp-del").get()
        data = raw_doc.to_dict()
        assert data.get("isDeleted") is True
        assert data.get("deletedBy") == "Admin Test"
        assert data.get("deletedAt") != ""


def test_opportunity_deletion_cancels_pending_activities_and_preserves_completed():
    """Al eliminar una oportunidad, sus actividades pendientes se cancelan y las completadas se preservan."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None):

        CRMService.save_opportunity("u1", "opp-with-acts", {"title": "Deal Acts", "stage": "Propuesta"}, company_id="comp-1")

        # Actividad pendiente
        CRMService.save_activity("u1", "act-pend", {
            "title": "Llamada pendiente", "opportunityId": "opp-with-acts", "status": "pendiente"
        }, company_id="comp-1")

        # Actividad completada
        CRMService.save_activity("u1", "act-comp", {
            "title": "Reunión completada", "opportunityId": "opp-with-acts", "status": "completada"
        }, company_id="comp-1")

        # Eliminar oportunidad
        CRMService.delete_opportunity("u1", "opp-with-acts", company_id="comp-1")

        # Verificar estados de actividades
        act_p = CRMService.get_activity("u1", "act-pend", company_id="comp-1")
        assert act_p["status"] == "cancelada"

        act_c = CRMService.get_activity("u1", "act-comp", company_id="comp-1")
        assert act_c["status"] == "completada"


def test_activity_soft_delete_preserves_completed_interaction():
    """Eliminar actividad pendiente limpia la interacción; actividad completada mantiene trazabilidad."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.DatabaseService.delete_client_interaction") as mock_del_inter:

        # 1. Pendiente
        CRMService.save_activity("u1", "act-del-p", {
            "title": "Tarea 1", "status": "pendiente", "contactId": "c-1"
        }, company_id="comp-1")

        CRMService.delete_activity("u1", "act-del-p", company_id="comp-1")
        assert CRMService.get_activity("u1", "act-del-p", company_id="comp-1") is None
        mock_del_inter.assert_called_with("u1", "c-1", "act-del-p", sandbox=True, company_id="comp-1")

        mock_del_inter.reset_mock()

        # 2. Completada
        CRMService.save_activity("u1", "act-del-c", {
            "title": "Tarea 2", "status": "completada", "contactId": "c-1"
        }, company_id="comp-1")

        CRMService.delete_activity("u1", "act-del-c", company_id="comp-1")
        # No se borra interacción de actividad completada para auditoría
        mock_del_inter.assert_not_called()


def test_contact_soft_delete_and_exclusion():
    """ContactService.delete_contact realiza soft delete y excluye de búsquedas."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll):

        ContactService.save_contact("u1", "c-del", {
            "razonSocial": "Cliente A Borrar", "rnc": "101000000", "estado": "Activo"
        }, company_id="comp-1")

        assert ContactService.get_contact("u1", "c-del", company_id="comp-1") is not None

        # Eliminar
        res = ContactService.delete_contact("u1", "c-del", company_id="comp-1")
        assert res is True

        # Ya no debe retornar en get_contact
        assert ContactService.get_contact("u1", "c-del", company_id="comp-1") is None

        # Excluido de get_contacts
        contacts = ContactService.get_contacts("u1", company_id="comp-1")
        assert not any(c["id"] == "c-del" for c in contacts)


def test_database_service_delete_client_soft_deletes_when_invoices_exist():
    """DatabaseService.delete_client hace soft delete si existen facturas para no romper integridad fiscal."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.db_service.DatabaseService.get_invoices", return_value=[{"id": "inv-1", "clientId": "c-tax"}]):

        # Guardar cliente
        DatabaseService.save_client("u1", "c-tax", {"name": "Empresa con Facturas", "rnc": "131000000"}, company_id="comp-1")

        # Intentar eliminar cliente con facturas
        res = DatabaseService.delete_client("u1", "c-tax", company_id="comp-1")
        assert res is True

        # Debe haber quedado marcado como isDeleted y no eliminado físicamente
        doc = fake_fs.get_collection("comp-1", "sandbox_contacts").document("c-tax").get()
        assert doc.exists
        assert doc.to_dict().get("isDeleted") is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. CRM-07: Permisos RBAC Granulares y Compatibilidad
# ─────────────────────────────────────────────────────────────────────────────

def test_crm_rbac_permissions_granular():
    """Verifica que los permisos granulares canCRM* protegen los módulos y soportan fallback."""

    # 1. Usuario con permisos CRM explícitos activos
    user_with_crm = {
        "id": "u-crm",
        "role": "vendedor",
        "permissions": {
            "canCRM": True,
            "canCRMContacts": True,
            "canCRMOpportunities": True,
            "canCRMActivities": True,
            "canCRMReports": False,
        }
    }
    with patch("app.utils.decorators.session", {"user": user_with_crm}):
        assert check_permission("canCRM") is True
        assert check_permission("canCRMOpportunities") is True
        assert check_permission("canCRMActivities") is True
        assert check_permission("canCRMReports") is False

    # 2. Usuario con permiso explícito falso (denegado)
    user_denied_crm = {
        "id": "u-no-crm",
        "role": "almacen",
        "permissions": {
            "canClients": True,
            "canCRM": False,
            "canCRMOpportunities": False,
        }
    }
    with patch("app.utils.decorators.session", {"user": user_denied_crm}):
        assert check_permission("canCRM") is False
        assert check_permission("canCRMOpportunities") is False

    # 3. Usuario legacy sin permisos canCRM* pero con canClients activo -> Fallback activo
    user_legacy_active = {
        "id": "u-legacy",
        "role": "usuario",
        "permissions": {
            "canClients": True,
        }
    }
    with patch("app.utils.decorators.session", {"user": user_legacy_active}):
        assert check_permission("canCRM") is True
        assert check_permission("canCRMOpportunities") is True
        assert check_permission("canCRMActivities") is True

    # 4. Usuario legacy sin canClients -> Denegado
    user_legacy_no_clients = {
        "id": "u-legacy-none",
        "role": "usuario",
        "permissions": {
            "canClients": False,
        }
    }
    with patch("app.utils.decorators.session", {"user": user_legacy_no_clients}):
        assert check_permission("canCRM") is False
        assert check_permission("canCRMOpportunities") is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. CRM-05 / CRM-06: Ficha Canónica 360° del Contacto
# ─────────────────────────────────────────────────────────────────────────────

def test_contact_360_consolidated_data_and_timeline():
    """get_contact_360 consolida contacto, oportunidades, actividades, facturas, interacciones y timeline."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    mock_contact = {"id": "c-360", "name": "Corporacion Alfa", "rnc": "131880681"}
    mock_invoices = [
        {"id": "inv-1", "clientId": "c-360", "invoiceNumber": "E31001", "total": 11800.0, "netPayable": 11800.0, "status": "Emitida", "date": "2026-05-10", "isQuotation": False},
        {"id": "cot-1", "clientId": "c-360", "invoiceNumber": "COT001", "total": 25000.0, "status": "Borrador", "date": "2026-05-01", "isQuotation": True},
    ]
    mock_interactions = [
        {"id": "int-1", "type": "Llamada", "title": "Primer contacto", "content": "Cliente interesado", "date": "2026-05-02"}
    ]

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service._resolve_contact", return_value=mock_contact), \
         patch("app.services.crm_service.DatabaseService.get_invoices", return_value=mock_invoices), \
         patch("app.services.crm_service.DatabaseService.get_client_interactions", return_value=mock_interactions):

        # Guardar oportunidad y actividad para este contacto
        CRMService.save_opportunity("u1", "opp-360", {
            "title": "Venta ERP Alfa", "contactId": "c-360", "stage": "Propuesta", "status": "abierta", "amount": 50000.0
        }, company_id="comp-1")

        CRMService.save_activity("u1", "act-360", {
            "title": "Presentación Demo", "contactId": "c-360", "status": "completada", "completedAt": "2026-05-05T10:00:00Z"
        }, company_id="comp-1")

        res_360 = CRMService.get_contact_360("u1", "c-360", company_id="comp-1")
        assert res_360 is not None
        assert res_360["contact"]["name"] == "Corporacion Alfa"
        assert len(res_360["opportunities"]) == 1
        assert len(res_360["activities"]) == 1
        assert len(res_360["invoices"]) == 1
        assert len(res_360["quotations"]) == 1
        assert len(res_360["interactions"]) == 1

        # Verificar cálculo de métricas
        assert res_360["metrics"]["totalInvoiced"] == 11800.0
        assert res_360["metrics"]["totalCxc"] == 11800.0
        assert res_360["metrics"]["openOpportunities"] == 1

        # Verificar timeline unificado y ordenado
        timeline = res_360["timeline"]
        assert len(timeline) >= 3  # factura + actividad completada + interacción


# ─────────────────────────────────────────────────────────────────────────────
# 5. CRM-04: Sincronización Explícita con Clientes Legacy
# ─────────────────────────────────────────────────────────────────────────────

def test_legacy_clients_sync_on_save_contact():
    """ContactService.save_contact ejecuta sincronización explícita con clients legacy."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.contact_service.firebase_initialized", True), \
         patch("app.services.contact_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.contact_service.DatabaseService.save_client") as mock_save_client:

        contact_data = {
            "razonSocial": "Cliente Sync Legacy",
            "rnc": "101999999",
            "email": "sync@acme.com",
            "telefono": "8095550000",
            "direccion": "Av. Winston Churchill",
            "types": ["cliente"],
            "pipelineStage": "Propuesta",
        }

        ContactService.save_contact("u1", "c-sync-1", contact_data, company_id="comp-1")

        # Verificar que save_client fue invocado con los campos mapeados
        mock_save_client.assert_called_once()
        call_args = mock_save_client.call_args
        assert call_args[0][0] == "u1"
        assert call_args[0][1] == "c-sync-1"
        saved_dict = call_args[0][2]
        assert saved_dict["razonSocial"] == "Cliente Sync Legacy"
        assert saved_dict["rnc"] == "101999999"
        assert saved_dict["email"] == "sync@acme.com"
        assert saved_dict["pipelineStage"] == "Propuesta"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Multi-tenancy en Fase 2
# ─────────────────────────────────────────────────────────────────────────────

def test_phase2_multi_tenant_isolation_on_transitions_and_deletes():
    """Empresa A no puede transicionar ni eliminar oportunidades de Empresa B."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None):

        # Guardar oportunidad en Empresa B
        CRMService.save_opportunity("u1", "opp-B", {
            "title": "Oportunidad de B", "stage": "Prospecto", "contactId": "c-B"
        }, company_id="comp-B")

        # Intentar transicionar desde Empresa A -> debe fallar (no encontrada en comp-A)
        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-B", "Contactado", company_id="comp-A")
        assert not ok
        assert "no encontrada" in msg

        # Intentar eliminar desde Empresa A -> debe retornar False y no afectarla en comp-B
        res = CRMService.delete_opportunity("u1", "opp-B", company_id="comp-A")
        assert res is False

        # La oportunidad de comp-B sigue intacta
        opp_b = CRMService.get_opportunity("u1", "opp-B", company_id="comp-B")
        assert opp_b is not None
        assert opp_b["stage"] == "Prospecto"
