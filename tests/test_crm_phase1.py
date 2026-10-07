"""
Pruebas de Fase 1 para el módulo CRM de VykOne.

Cubre:
1. CRM-01: Aislamiento Multi-Tenant estricto y company_id obligatorio.
2. CRM-02: Vinculación selectiva Factura -> Oportunidad y soporte multi-factura.
3. CRM-03: Optimización y caché de compromisos globales sin scans completos.
"""

import time
import pytest
from unittest.mock import MagicMock, patch

from app.models.crm import CRMOpportunity, CRMActivity
from app.services.crm_service import CRMService
from app.services.db_service import DatabaseService


# ─────────────────────────────────────────────────────────────────────────────
# 1. CRM-01: Validación de company_id obligatorio
# ─────────────────────────────────────────────────────────────────────────────

def test_crm_service_requires_company_id_on_all_methods():
    """Verifica que CRMService rechaza company_id=None o vacío en todas las operaciones."""
    owner_uid = "owner-123"

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_opportunity(owner_uid, "opp-1", company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_opportunities(owner_uid, company_id="")

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.save_opportunity(owner_uid, "opp-1", {"title": "Test"}, company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.delete_opportunity(owner_uid, "opp-1", company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.close_opportunity(owner_uid, "opp-1", "ganada", company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_activity(owner_uid, "act-1", company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_activities(owner_uid, company_id="")

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.save_activity(owner_uid, "act-1", {"title": "Tarea"}, company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.complete_activity(owner_uid, "act-1", company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.delete_activity(owner_uid, "act-1", company_id="")

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_pipeline(owner_uid, company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_leads(owner_uid, company_id="")

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_dashboard(owner_uid, company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_next_action_suggestions(owner_uid, company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_global_commitments(owner_uid, company_id=None)

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.link_invoice_to_opportunity(owner_uid, "inv-1", company_id=None)


# ─────────────────────────────────────────────────────────────────────────────
# 2. CRM-01: Aislamiento Multi-Tenant entre Empresa A y Empresa B
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
                store[(company_id, coll_name, self.doc_id)] = data

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
                        dm.to_dict.return_value = data
                        docs.append(dm)
                return docs

        return MockCollRef()


def test_crm_multi_tenant_isolation():
    """Verifica que los datos de la Empresa A no sean leídos ni alterados por la Empresa B."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]):

        # Guardar oportunidad para Empresa A
        opp_a = CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-A1",
            opportunity_dict={"title": "Venta Empresa A", "amount": 10000.0, "contactId": "c-1"},
            sandbox=True,
            company_id="company-A"
        )
        assert opp_a["companyId"] == "company-A"

        # Guardar oportunidad para Empresa B
        opp_b = CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-B1",
            opportunity_dict={"title": "Venta Empresa B", "amount": 25000.0, "contactId": "c-2"},
            sandbox=True,
            company_id="company-B"
        )
        assert opp_b["companyId"] == "company-B"

        # Consultar oportunidades de Empresa A -> Solo debe ver A
        opps_a = CRMService.get_opportunities("user-1", sandbox=True, company_id="company-A")
        assert len(opps_a) == 1
        assert opps_a[0]["id"] == "opp-A1"

        # Consultar oportunidades de Empresa B -> Solo debe ver B
        opps_b = CRMService.get_opportunities("user-1", sandbox=True, company_id="company-B")
        assert len(opps_b) == 1
        assert opps_b[0]["id"] == "opp-B1"

        # Intentar obtener opp-A1 desde el contexto de Empresa B -> Debe retornar None
        opp_cross = CRMService.get_opportunity("user-1", "opp-A1", sandbox=True, company_id="company-B")
        assert opp_cross is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. CRM-02: Factura -> Oportunidad selectiva y multi-factura
# ─────────────────────────────────────────────────────────────────────────────

def test_invoice_without_crm_link_leaves_opportunities_untouched():
    """Factura sin opportunityId ni quotationId no altera ninguna oportunidad."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]):

        # Crear oportunidad abierta
        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-open",
            opportunity_dict={"title": "Negocio en curso", "stage": "Propuesta", "contactId": "client-10"},
            sandbox=True,
            company_id="company-A"
        )

        # Intentar vincular factura genérica (sin link)
        updated = CRMService.link_invoice_to_opportunity(
            owner_uid="user-1",
            invoice_id="inv-unrelated",
            invoice_number="B0100000001",
            opportunity_id=None,
            quotation_id=None,
            sandbox=True,
            company_id="company-A",
            total_amount=5000.0,
        )
        assert updated == 0

        # Verificar que la oportunidad sigue abierta en 'Propuesta'
        opp = CRMService.get_opportunity("user-1", "opp-open", sandbox=True, company_id="company-A")
        assert opp["stage"] == "Propuesta"
        assert opp["status"] == "abierta"
        assert opp["invoiceId"] == ""
        assert len(opp["invoices"]) == 0


def test_invoice_with_opportunity_id_links_only_exact_opportunity():
    """Factura con opportunityId vincula y cierra únicamente la oportunidad indicada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction", return_value=None):

        # Crear 2 oportunidades para el mismo cliente
        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-target",
            opportunity_dict={"title": "Proyecto Alpha", "stage": "Negociación", "contactId": "client-10"},
            sandbox=True,
            company_id="company-A"
        )
        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-other",
            opportunity_dict={"title": "Proyecto Beta", "stage": "Prospecto", "contactId": "client-10"},
            sandbox=True,
            company_id="company-A"
        )

        # Emitir factura vinculada a opp-target
        updated = CRMService.link_invoice_to_opportunity(
            owner_uid="user-1",
            invoice_id="inv-alpha-1",
            invoice_number="B0100000010",
            opportunity_id="opp-target",
            sandbox=True,
            company_id="company-A",
            total_amount=150000.0,
        )
        assert updated == 1

        # Verificar opp-target -> Ganada
        opp_t = CRMService.get_opportunity("user-1", "opp-target", sandbox=True, company_id="company-A")
        assert opp_t["stage"] == "Ganada"
        assert opp_t["status"] == "ganada"
        assert opp_t["invoiceId"] == "inv-alpha-1"
        assert opp_t["invoiceNumber"] == "B0100000010"
        assert len(opp_t["invoices"]) == 1
        assert opp_t["invoices"][0]["id"] == "inv-alpha-1"
        assert opp_t["invoices"][0]["amount"] == 150000.0

        # Verificar opp-other -> Intacta en Prospecto
        opp_o = CRMService.get_opportunity("user-1", "opp-other", sandbox=True, company_id="company-A")
        assert opp_o["stage"] == "Prospecto"
        assert opp_o["status"] == "abierta"
        assert opp_o["invoiceId"] == ""
        assert len(opp_o["invoices"]) == 0


def test_opportunity_supports_multiple_invoices():
    """Verifica que una misma oportunidad acumula múltiples facturas en su lista `invoices`."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction", return_value=None):

        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-multi",
            opportunity_dict={"title": "Servicio Anual", "stage": "Negociación", "contactId": "client-5"},
            sandbox=True,
            company_id="company-A"
        )

        # Vincular Factura 1 (Adelanto)
        CRMService.link_invoice_to_opportunity(
            owner_uid="user-1",
            invoice_id="inv-p1",
            invoice_number="E3100000001",
            opportunity_id="opp-multi",
            sandbox=True,
            company_id="company-A",
            total_amount=50000.0,
        )

        # Vincular Factura 2 (Saldo)
        CRMService.link_invoice_to_opportunity(
            owner_uid="user-1",
            invoice_id="inv-p2",
            invoice_number="E3100000002",
            opportunity_id="opp-multi",
            sandbox=True,
            company_id="company-A",
            total_amount=50000.0,
        )

        opp = CRMService.get_opportunity("user-1", "opp-multi", sandbox=True, company_id="company-A")
        assert opp["stage"] == "Ganada"
        assert len(opp["invoices"]) == 2
        assert opp["invoices"][0]["id"] == "inv-p1"
        assert opp["invoices"][1]["id"] == "inv-p2"
        assert opp["invoices"][0]["amount"] == 50000.0
        assert opp["invoices"][1]["amount"] == 50000.0


def test_link_invoice_to_opportunity_is_idempotent():
    """Verifica que guardar/vincular la misma factura múltiples veces no duplica invoices ni genera interacciones repetidas."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    interactions_recorded = []

    def mock_save_interaction(owner_uid, contact_id, interaction_id, data, sandbox=True, company_id=None):
        interactions_recorded.append((contact_id, interaction_id, data))

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction", side_effect=mock_save_interaction):

        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-idempotent",
            opportunity_dict={"title": "Contrato Idempotente", "stage": "Propuesta", "contactId": "client-idem"},
            sandbox=True,
            company_id="company-A"
        )

        # 1era llamada: Vinculación inicial
        updated_1 = CRMService.link_invoice_to_opportunity(
            owner_uid="user-1",
            invoice_id="inv-idem-1",
            invoice_number="E3100000099",
            opportunity_id="opp-idempotent",
            sandbox=True,
            company_id="company-A",
            total_amount=25000.0,
        )
        assert updated_1 == 1
        assert len(interactions_recorded) == 1

        # 2da llamada con la misma factura (ej. re-guardado de factura)
        updated_2 = CRMService.link_invoice_to_opportunity(
            owner_uid="user-1",
            invoice_id="inv-idem-1",
            invoice_number="E3100000099",
            opportunity_id="opp-idempotent",
            sandbox=True,
            company_id="company-A",
            total_amount=25000.0,
        )
        assert updated_2 == 1
        # No debe haber generado una segunda interacción
        assert len(interactions_recorded) == 1

        # 3ra llamada con la misma factura
        updated_3 = CRMService.link_invoice_to_opportunity(
            owner_uid="user-1",
            invoice_id="inv-idem-1",
            invoice_number="E3100000099",
            opportunity_id="opp-idempotent",
            sandbox=True,
            company_id="company-A",
            total_amount=25000.0,
        )
        assert updated_3 == 1
        assert len(interactions_recorded) == 1

        opp = CRMService.get_opportunity("user-1", "opp-idempotent", sandbox=True, company_id="company-A")
        assert opp["stage"] == "Ganada"
        # La lista invoices debe tener exactamente 1 factura
        assert len(opp["invoices"]) == 1
        assert opp["invoices"][0]["id"] == "inv-idem-1"
        assert opp["invoices"][0]["amount"] == 25000.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. CRM-03: Performance y Caché de Compromisos Globales
# ─────────────────────────────────────────────────────────────────────────────

def test_commitments_query_and_cache_invalidation():
    """Verifica que get_global_commitments utiliza caché de 60s y se invalida ante cambios."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    CRMService.invalidate_commitments_cache()

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction", return_value=None):

        # 1. Guardar una actividad vencida
        CRMService.save_activity(
            owner_uid="user-1",
            activity_id="act-overdue-1",
            activity_dict={
                "title": "Llamada de cobro",
                "dueDate": "2020-01-01",  # Vencida
                "status": "pendiente",
                "contactName": "Cliente Moroso",
            },
            sandbox=True,
            company_id="company-A"
        )

        # 2. Primera consulta -> Debe leer de BD y cachear
        commitments_1 = CRMService.get_global_commitments("user-1", sandbox=True, company_id="company-A")
        assert len(commitments_1) == 1
        assert commitments_1[0]["activityId"] == "act-overdue-1"
        assert commitments_1[0]["isOverdue"] is True

        # 3. Inyectar directamente en Firestore sin pasar por save_activity para verificar que el caché responde
        fake_fs.store[("company-A", "sandbox_crm_activities", "act-ghost")] = {
            "id": "act-ghost",
            "title": "Ghost",
            "dueDate": "2020-01-01",
            "status": "pendiente",
        }
        # Segunda consulta dentro de 60s -> Debe seguir retornando 1 (desde caché)
        commitments_cached = CRMService.get_global_commitments("user-1", sandbox=True, company_id="company-A")
        assert len(commitments_cached) == 1

        # 4. Completar la actividad existente -> Debe invalidar el caché
        CRMService.complete_activity("user-1", "act-overdue-1", sandbox=True, company_id="company-A")

        # Ahora el caché está limpio, la consulta lee de nuevo y act-overdue-1 ya no está pendiente
        commitments_after_complete = CRMService.get_global_commitments("user-1", sandbox=True, company_id="company-A")
        ids = [c.get("activityId") for c in commitments_after_complete]
        assert "act-overdue-1" not in ids


def test_invoice_with_quotation_id_links_only_matching_opportunity():
    """Verifica que una factura convertida desde cotización busca y cierra únicamente la oportunidad con esa cotización."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction", return_value=None):

        # Oportunidad con cotización quote-100
        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-quote-match",
            opportunity_dict={
                "title": "Venta con Cotización",
                "stage": "Propuesta",
                "quotationId": "quote-100",
                "quotationNumber": "COT-001",
                "contactId": "c-10"
            },
            sandbox=True,
            company_id="company-A"
        )
        # Oportunidad distinta sin cotización
        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-other-lead",
            opportunity_dict={
                "title": "Otro Negocio",
                "stage": "Prospecto",
                "contactId": "c-10"
            },
            sandbox=True,
            company_id="company-A"
        )

        # Factura emitida a partir de la cotización quote-100
        updated = CRMService.link_invoice_to_opportunity(
            owner_uid="user-1",
            invoice_id="inv-from-quote",
            invoice_number="E3100000050",
            quotation_id="quote-100",
            sandbox=True,
            company_id="company-A",
            total_amount=75000.0,
        )
        assert updated == 1

        opp_match = CRMService.get_opportunity("user-1", "opp-quote-match", sandbox=True, company_id="company-A")
        assert opp_match["stage"] == "Ganada"
        assert opp_match["invoiceId"] == "inv-from-quote"
        assert len(opp_match["invoices"]) == 1

        opp_other = CRMService.get_opportunity("user-1", "opp-other-lead", sandbox=True, company_id="company-A")
        assert opp_other["stage"] == "Prospecto"
        assert opp_other["invoiceId"] == ""
        assert len(opp_other["invoices"]) == 0


def test_pipeline_and_dashboard_tenant_isolation():
    """Verifica que el Pipeline y Dashboard no mezclan métricas ni montos entre empresas."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contacts", return_value=[]), \
         patch("app.services.crm_service.ContactService.get_contact", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_invoices", return_value=[]), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]):

        # Empresa A: 1 opp de 10,000 en Negociación
        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-A",
            opportunity_dict={"title": "Opp A", "stage": "Negociación", "amount": 10000.0, "probability": 75},
            sandbox=True,
            company_id="company-A"
        )
        # Empresa B: 1 opp de 50,000 en Propuesta
        CRMService.save_opportunity(
            owner_uid="user-1",
            opportunity_id="opp-B",
            opportunity_dict={"title": "Opp B", "stage": "Propuesta", "amount": 50000.0, "probability": 55},
            sandbox=True,
            company_id="company-B"
        )

        pipeline_a = CRMService.get_pipeline("user-1", sandbox=True, company_id="company-A")
        pipeline_b = CRMService.get_pipeline("user-1", sandbox=True, company_id="company-B")

        neg_stage_a = next(s for s in pipeline_a if s["stage"] == "Negociación")
        neg_stage_b = next(s for s in pipeline_b if s["stage"] == "Negociación")

        assert neg_stage_a["amount"] == 10000.0
        assert neg_stage_a["count"] == 1
        assert neg_stage_b["amount"] == 0.0
        assert neg_stage_b["count"] == 0

        dashboard_a = CRMService.get_dashboard("user-1", sandbox=True, company_id="company-A")
        dashboard_b = CRMService.get_dashboard("user-1", sandbox=True, company_id="company-B")

        assert dashboard_a["metrics"]["pipelineValue"] == 10000.0
        assert dashboard_b["metrics"]["pipelineValue"] == 50000.0


def test_commitments_includes_due_contacts_without_invoice_scans():
    """Verifica que contactos con nextContactDate vencida/hoy se incluyan en compromisos si no tienen actividad duplicada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    CRMService.invalidate_commitments_cache()

    mock_contacts = [
        {
            "id": "c-due-today",
            "razonSocial": "Cliente con Fecha Hoy",
            "types": ["cliente"],
            "nextContactDate": "2020-01-01",  # Vencida / Pasada
            "notes": "Llamar para renovar contrato",
            "telefono": "8095551234",
        },
        {
            "id": "c-future",
            "razonSocial": "Cliente Futuro",
            "types": ["cliente"],
            "nextContactDate": "2099-12-31",
            "notes": "Seguimiento fin de siglo",
        },
        {
            "id": "c-supplier",
            "razonSocial": "Suplidor con Fecha",
            "types": ["proveedor"],  # No es cliente
            "nextContactDate": "2020-01-01",
        }
    ]

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contacts", return_value=mock_contacts), \
         patch("app.services.crm_service.DatabaseService.get_team_members", return_value=[]):

        commitments = CRMService.get_global_commitments("user-1", sandbox=True, company_id="company-A")

        # Debe incluir a c-due-today
        c_ids = [c["id"] for c in commitments]
        assert "c-due-today" in c_ids
        assert "c-future" not in c_ids
        assert "c-supplier" not in c_ids

        target_item = next(c for c in commitments if c["id"] == "c-due-today")
        assert target_item["razonSocial"] == "Cliente con Fecha Hoy"
        assert target_item["crmNotes"] == "Llamar para renovar contrato"
        assert target_item["commitmentType"] == "contact"
        assert target_item["isOverdue"] is True

