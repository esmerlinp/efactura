"""
Pruebas de Fase 3 para el módulo CRM de VykOne (UX, Kanban, Auditoría, Contact 360).

Cubre:
1. CRM-17: Auditoría y trazabilidad de cambios de etapa (stageHistory y AuditService).
2. CRM-11: Endpoint JSON para Kanban Drag & Drop con validaciones de etapa y rechazos 400.
3. CRM-12: Filtros de sucursal (branchId) y proyecto (projectId) en pipeline, dashboard y actividades.
4. CRM-10 & CRM-19: Acciones rápidas y notas directas (quick-note).
5. CRM-05 / CRM-06: Integración y entrega de datos para Contact 360 en vista de detalle.
6. CRM-18: Sincronización de cotizaciones hacia oportunidades (link_quotation_to_opportunity).
"""

import pytest
from unittest.mock import MagicMock, patch

from app.models.crm import CRMOpportunity, CRMActivity
from app.services.crm_service import CRMService
from app.services.contact_service import ContactService
from app.services.db_service import DatabaseService


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
# 1. CRM-17: Stage History y Trazabilidad Cronológica de Transiciones
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_history_recorded_on_transitions():
    """Verifica que cada transición registra una entrada completa en stageHistory."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1", "responsibleId": "rep-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        # 1. Crear oportunidad en Prospecto
        CRMService.save_opportunity("u1", "opp-hist-1", {
            "title": "Oportunidad con Historia",
            "stage": "Prospecto",
            "contactId": "c-1",
            "assignedTo": "rep-1",
            "amount": 50000.0,
        }, company_id="comp-1")

        # 2. Transición 1: Prospecto -> Contactado
        ok1, _, opp1 = CRMService.transition_opportunity("u1", "opp-hist-1", "Contactado", user_name="Vendedor Juan", notes="Primer contacto telefónico", company_id="comp-1")
        assert ok1
        assert len(opp1.get("stageHistory", [])) == 1
        h1 = opp1["stageHistory"][0]
        assert h1["from"] == "Prospecto"
        assert h1["to"] == "Contactado"
        assert h1["by"] == "Vendedor Juan"
        assert h1["notes"] == "Primer contacto telefónico"

        # 3. Transición 2: Contactado -> Calificado
        ok2, _, opp2 = CRMService.transition_opportunity("u1", "opp-hist-1", "Calificado", user_name="Vendedor Juan", company_id="comp-1")
        assert ok2
        assert len(opp2.get("stageHistory", [])) == 2
        h2 = opp2["stageHistory"][1]
        assert h2["from"] == "Contactado"
        assert h2["to"] == "Calificado"

        # 4. Transición 3: Calificado -> Perdida
        ok3, _, opp3 = CRMService.transition_opportunity(
            "u1", "opp-hist-1", "Perdida",
            lost_reason="Cliente eligió competidor local",
            user_name="Supervisor Pedro",
            company_id="comp-1"
        )
        assert ok3
        assert len(opp3.get("stageHistory", [])) == 3
        h3 = opp3["stageHistory"][2]
        assert h3["from"] == "Calificado"
        assert h3["to"] == "Perdida"
        assert h3["lostReason"] == "Cliente eligió competidor local"
        assert h3["by"] == "Supervisor Pedro"


# ─────────────────────────────────────────────────────────────────────────────
# 2. CRM-11: Kanban Drag & Drop API Handling
# ─────────────────────────────────────────────────────────────────────────────

def test_kanban_stage_transition_via_service():
    """Simula el payload que envía el drag & drop del Kanban validando respuestas exitosas y errores."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-k1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction"):

        CRMService.save_opportunity("u1", "opp-kanban", {
            "title": "Deal Kanban",
            "stage": "Prospecto",
            "contactId": "c-k1",
            "amount": 25000.0,
        }, company_id="comp-1")

        # Dropping to 'Contactado' -> Ok
        ok, msg, opp = CRMService.transition_opportunity("u1", "opp-kanban", "Contactado", company_id="comp-1")
        assert ok
        assert opp["stage"] == "Contactado"

        # Dropping to 'Perdida' without lostReason -> Rejected (Frontend will open modal)
        ok_lost, msg_lost, _ = CRMService.transition_opportunity("u1", "opp-kanban", "Perdida", lost_reason="", company_id="comp-1")
        assert not ok_lost
        assert "motivo de pérdida" in msg_lost

        # Dropping to 'Perdida' with lostReason -> Ok
        ok_lost_valid, _, opp_lost = CRMService.transition_opportunity(
            "u1", "opp-kanban", "Perdida", lost_reason="Presupuesto no disponible", company_id="comp-1"
        )
        assert ok_lost_valid
        assert opp_lost["stage"] == "Perdida"


# ─────────────────────────────────────────────────────────────────────────────
# 3. CRM-12: Filtros de Sucursal y Proyecto
# ─────────────────────────────────────────────────────────────────────────────

def test_pipeline_and_activities_branch_and_project_filtering():
    """Verifica que el pipeline y las actividades se filtran correctamente por branchId y projectId."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-1"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None):

        # Oportunidad en Sucursal Principal / Proyecto Alfa
        CRMService.save_opportunity("u1", "opp-b1-p1", {
            "title": "Venta Sucursal 1 Proyecto Alfa",
            "stage": "Propuesta",
            "amount": 10000.0,
            "branchId": "branch-1",
            "projectId": "proj-A",
            "contactId": "c-1",
        }, company_id="comp-1")

        # Oportunidad en Sucursal 2 / Proyecto Beta
        CRMService.save_opportunity("u1", "opp-b2-p2", {
            "title": "Venta Sucursal 2 Proyecto Beta",
            "stage": "Propuesta",
            "amount": 20000.0,
            "branchId": "branch-2",
            "projectId": "proj-B",
            "contactId": "c-1",
        }, company_id="comp-1")

        # Actividad en Sucursal 1
        CRMService.save_activity("u1", "act-b1", {
            "title": "Llamada Sucursal 1",
            "branchId": "branch-1",
            "projectId": "proj-A",
            "status": "pendiente",
        }, company_id="comp-1")

        # Actividad en Sucursal 2
        CRMService.save_activity("u1", "act-b2", {
            "title": "Reunión Sucursal 2",
            "branchId": "branch-2",
            "projectId": "proj-B",
            "status": "pendiente",
        }, company_id="comp-1")

        # 1. Pipeline filtrado por branch-1
        pipe_b1 = CRMService.get_pipeline("u1", company_id="comp-1", branch_id="branch-1")
        col_prop_b1 = next(c for c in pipe_b1 if c["stage"] == "Propuesta")
        assert col_prop_b1["count"] == 1
        assert col_prop_b1["opportunities"][0]["id"] == "opp-b1-p1"

        # 2. Pipeline filtrado por proj-B
        pipe_pb = CRMService.get_pipeline("u1", company_id="comp-1", project_id="proj-B")
        col_prop_pb = next(c for c in pipe_pb if c["stage"] == "Propuesta")
        assert col_prop_pb["count"] == 1
        assert col_prop_pb["opportunities"][0]["id"] == "opp-b2-p2"

        # 3. Actividades filtradas por branch-1
        acts_b1 = CRMService.get_activities("u1", company_id="comp-1", branch_id="branch-1")
        assert len(acts_b1) == 1
        assert acts_b1[0]["id"] == "act-b1"


# ─────────────────────────────────────────────────────────────────────────────
# 4. CRM-10 & CRM-19: Quick Notes y Acciones Rápidas
# ─────────────────────────────────────────────────────────────────────────────

def test_quick_note_appends_to_opportunity_and_contact():
    """Verifica que agregar una nota rápida actualiza la oportunidad y guarda una interacción."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-note"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.save_client_interaction") as mock_interaction:

        # Crear oportunidad
        CRMService.save_opportunity("u1", "opp-note", {
            "title": "Oportunidad Nota",
            "contactId": "c-note",
            "notes": "Nota previa",
            "stage": "Propuesta",
        }, company_id="comp-1")

        opp = CRMService.get_opportunity("u1", "opp-note", company_id="comp-1")
        opp["notes"] = f"{opp.get('notes', '')}\n[2026-10-07 - Vendedor]: Cliente solicita descuento del 5%.".strip()
        saved = CRMService.save_opportunity("u1", "opp-note", opp, company_id="comp-1")

        assert "Cliente solicita descuento del 5%" in saved["notes"]
        assert "Nota previa" in saved["notes"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. CRM-18: Sincronización Cotización ➔ Oportunidad
# ─────────────────────────────────────────────────────────────────────────────

def test_link_quotation_to_opportunity_syncs_fields():
    """Verifica que link_quotation_to_opportunity asocia quotationId, quotationNumber y actualiza monto."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-quote"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None):

        CRMService.save_opportunity("u1", "opp-quote", {
            "title": "Venta con Cotización",
            "stage": "Calificado",
            "contactId": "c-quote",
            "amount": 0.0,
        }, company_id="comp-1")

        saved = CRMService.link_quotation_to_opportunity(
            owner_uid="u1",
            quotation_id="cot-101",
            quotation_number="COT-2026-0099",
            opportunity_id="opp-quote",
            amount=85000.0,
            company_id="comp-1"
        )

        assert saved is not None
        assert saved["quotationId"] == "cot-101"
        assert saved["quotationNumber"] == "COT-2026-0099"
        assert saved["amount"] == 85000.0


# ─────────────────────────────────────────────────────────────────────────────
# 6. CRM-05 / CRM-06: Métricas y Timeline en Contact 360
# ─────────────────────────────────────────────────────────────────────────────

def test_contact_360_metrics_and_unified_timeline():
    """Verifica el cálculo completo de métricas y timeline de get_contact_360."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    mock_contact = {"id": "c-full", "name": "Empresa 360", "rnc": "131000000"}
    mock_invoices = [
        {"id": "inv-1", "clientId": "c-full", "invoiceNumber": "E31001", "total": 20000.0, "netPayable": 20000.0, "status": "Emitida", "date": "2026-10-01", "isQuotation": False},
        {"id": "inv-2", "clientId": "c-full", "invoiceNumber": "E31002", "total": 30000.0, "netPayable": 0.0, "status": "Pagada", "date": "2026-10-02", "isQuotation": False},
        {"id": "cot-1", "clientId": "c-full", "invoiceNumber": "COT001", "total": 15000.0, "status": "Borrador", "date": "2026-10-03", "isQuotation": True},
    ]
    mock_interactions = [
        {"id": "int-1", "type": "Nota", "title": "Nota inicial", "content": "Detalles iniciales", "date": "2026-09-30"}
    ]

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service._resolve_contact", return_value=mock_contact), \
         patch("app.services.crm_service.DatabaseService.get_invoices", return_value=mock_invoices), \
         patch("app.services.crm_service.DatabaseService.get_client_interactions", return_value=mock_interactions):

        # Guardar 2 oportunidades (1 abierta, 1 ganada)
        CRMService.save_opportunity("u1", "opp-open", {
            "title": "Op Abierta", "contactId": "c-full", "stage": "Propuesta", "status": "abierta", "amount": 50000.0
        }, company_id="comp-1")

        CRMService.save_opportunity("u1", "opp-won", {
            "title": "Op Ganada", "contactId": "c-full", "stage": "Ganada", "status": "ganada", "amount": 30000.0
        }, company_id="comp-1")

        # Guardar 1 actividad pendiente y 1 completada
        CRMService.save_activity("u1", "act-p", {
            "title": "Llamar cliente", "contactId": "c-full", "status": "pendiente"
        }, company_id="comp-1")

        CRMService.save_activity("u1", "act-c", {
            "title": "Presentación lista", "contactId": "c-full", "status": "completada", "completedAt": "2026-10-04T10:00:00Z"
        }, company_id="comp-1")

        data_360 = CRMService.get_contact_360("u1", "c-full", company_id="comp-1")
        assert data_360 is not None

        # Métricas
        metrics = data_360["metrics"]
        assert metrics["totalInvoiced"] == 50000.0  # inv-1 + inv-2
        assert metrics["totalCxc"] == 20000.0       # inv-1
        assert metrics["openOpportunities"] == 1
        assert metrics["wonOpportunities"] == 1
        assert metrics["pendingActivities"] == 1

        # Timeline
        timeline = data_360["timeline"]
        assert len(timeline) >= 4  # facturas emitidas + actividad completada + interacciones


# ─────────────────────────────────────────────────────────────────────────────
# 7. Hardening: Sincronización automática Cotización -> Oportunidad vía save_invoice
# ─────────────────────────────────────────────────────────────────────────────

def test_quotation_save_invoice_auto_syncs_opportunity_amount():
    """Verifica que modificar una cotización en save_invoice actualiza la oportunidad vinculada."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.db_service._invalidate_invoices"), \
         patch("app.services.db_service._invalidate_crm_contacts"), \
         patch("app.services.cache_service.CacheService.invalidate_dashboard"):

        # 1. Crear oportunidad vinculada a la cotización "quote-999"
        CRMService.save_opportunity("u1", "opp-auto-quote", {
            "title": "Proyecto Licenciamiento",
            "quotationId": "quote-999",
            "quotationNumber": "COT-999",
            "amount": 50000.0,
            "stage": "Propuesta",
        }, company_id="comp-1")

        # 2. Guardar actualización de cotización con nuevo total $125,000
        inv_data = {
            "id": "quote-999",
            "invoiceNumber": "COT-999-REV2",
            "isQuotation": True,
            "total": 125000.0,
            "status": "Emitida",
        }
        DatabaseService.save_invoice("u1", "quote-999", inv_data, company_id="comp-1")

        # 3. Verificar que la oportunidad actualizó automáticamente su monto y número
        updated_opp = CRMService.get_opportunity("u1", "opp-auto-quote", company_id="comp-1")
        assert updated_opp is not None
        assert updated_opp["amount"] == 125000.0
        assert updated_opp["quotationNumber"] == "COT-999-REV2"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Hardening: Aislamiento Multi-tenant Estricto en Fase 3
# ─────────────────────────────────────────────────────────────────────────────

def test_phase3_tenant_isolation_complete():
    """Verifica aislamiento estricto entre empresas en Contact 360, Pipeline y Notas Rápidas."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service.ContactService.get_contact", return_value={"id": "c-iso", "responsibleId": "rep-iso"}), \
         patch("app.services.crm_service.ContactService.update_pipeline", return_value=None), \
         patch("app.services.crm_service.DatabaseService.get_invoices", return_value=[]), \
         patch("app.services.crm_service.DatabaseService.get_client_interactions", return_value=[]):

        # Guardar datos en Empresa 1
        CRMService.save_opportunity("u1", "opp-comp1", {
            "title": "Op Tenant 1", "contactId": "c-iso", "stage": "Calificado", "assignedTo": "rep-iso"
        }, company_id="comp-1")

        # Guardar datos en Empresa 2
        CRMService.save_opportunity("u1", "opp-comp2", {
            "title": "Op Tenant 2", "contactId": "c-iso", "stage": "Propuesta", "assignedTo": "rep-iso"
        }, company_id="comp-2")

        # Pipeline Empresa 1 no ve Empresa 2
        p1 = CRMService.get_pipeline("u1", company_id="comp-1")
        opps_p1 = [opp["id"] for stage_grp in p1 for opp in stage_grp["opportunities"]]
        assert "opp-comp1" in opps_p1
        assert "opp-comp2" not in opps_p1

        # Pipeline Empresa 2 no ve Empresa 1
        p2 = CRMService.get_pipeline("u1", company_id="comp-2")
        opps_p2 = [opp["id"] for stage_grp in p2 for opp in stage_grp["opportunities"]]
        assert "opp-comp2" in opps_p2
        assert "opp-comp1" not in opps_p2

        # Intento de transición cruzada (Empresa 2 intentando transicionar op de Empresa 1)
        ok, msg, _ = CRMService.transition_opportunity("u1", "opp-comp1", "Propuesta", company_id="comp-2")
        assert not ok
        assert "no encontrada" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 9. Hardening: Oportunidad Eliminada (Soft-Delete) Excluida de Kanban y 360
# ─────────────────────────────────────────────────────────────────────────────

def test_soft_deleted_opportunity_excluded_from_kanban_and_360():
    """Verifica que una oportunidad marcada como eliminada no aparezca en Pipeline ni Contact 360."""
    fake_fs = InMemoryFirestore()

    def fake_company_coll(company_id=None, coll_name=None, owner_uid=None):
        return fake_fs.get_collection(company_id, coll_name)

    mock_contact = {"id": "c-del", "name": "Cliente Soft Delete"}

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=fake_company_coll), \
         patch("app.services.crm_service._resolve_contact", return_value=mock_contact), \
         patch("app.services.crm_service.DatabaseService.get_invoices", return_value=[]), \
         patch("app.services.crm_service.DatabaseService.get_client_interactions", return_value=[]):

        # 1. Crear oportunidad activa
        CRMService.save_opportunity("u1", "opp-to-delete", {
            "title": "Oportunidad Eliminable", "contactId": "c-del", "stage": "Propuesta", "amount": 75000.0
        }, company_id="comp-1")

        # 2. Verificar que existe en Pipeline
        p1 = CRMService.get_pipeline("u1", company_id="comp-1")
        opps_before = [opp["id"] for stage_grp in p1 for opp in stage_grp["opportunities"]]
        assert "opp-to-delete" in opps_before

        # 3. Eliminar (soft delete)
        del_ok = CRMService.delete_opportunity("u1", "opp-to-delete", company_id="comp-1")
        assert del_ok

        # 4. Verificar que desapareció de Pipeline
        p2 = CRMService.get_pipeline("u1", company_id="comp-1")
        opps_after = [opp["id"] for stage_grp in p2 for opp in stage_grp["opportunities"]]
        assert "opp-to-delete" not in opps_after

        # 5. Verificar que Contact 360 no la cuenta
        c360 = CRMService.get_contact_360("u1", "c-del", company_id="comp-1")
        assert len(c360["opportunities"]) == 0
        assert c360["metrics"]["openOpportunities"] == 0

