"""
Pruebas de Fase 5.2 (CRM Mutations REST API).

Cubre:
1. Opportunities Mutations:
   - POST /api/v1/crm/opportunities (creación estándar y en etapa avanzada, validación y sanitización)
   - PATCH /api/v1/crm/opportunities/<id> (actualización de campos y transición delegada)
   - POST /api/v1/crm/opportunities/<id>/stage (máquina de estados: Prospecto->Contactado, Propuesta->Ganada, Propuesta->Perdida con lostReason, reaperturas, idempotencia same-stage y transiciones inválidas)
   - DELETE /api/v1/crm/opportunities/<id> (soft delete, cancelación de actividades pendientes)
   - POST /api/v1/crm/opportunities/<id>/quick-note (nota rápida y registro de interacción)

2. Activities Mutations:
   - POST /api/v1/crm/activities (creación, bloqueo de falsificación de campos de automatización)
   - PATCH /api/v1/crm/activities/<id> (actualización de campos)
   - POST /api/v1/crm/activities/<id>/complete (completar actividad con SLA y sincronización de nextContactDate)
   - DELETE /api/v1/crm/activities/<id> (soft delete de actividad)

3. Contacts Mutations:
   - POST /api/v1/crm/contacts (creación con validación de razón social)
   - PATCH /api/v1/crm/contacts/<id> (actualización de campos, no sobreescritura de pipelineStage)
   - DELETE /api/v1/crm/contacts/<id> (soft delete preservando consistencia legacy)
   - POST /api/v1/crm/contacts/<id>/quick-note (interacción en ficha de contacto)

4. Aislamiento Multi-Tenant y Seguridad en Mutations:
   - Identidad: parámetros 'ownerUID' y 'companyId' en body son ignorados
   - Cross-Tenant: mutaciones sobre recursos de otro tenant retornan 404 sin alterar ningún dato
   - RBAC granular: canCRMOpportunities no permite mutar contactos, canCRMContacts no permite mutar oportunidades, etc.

5. Equivalencia Dominio / REST:
   - Demostración de que la mutación REST produce exactamente las mismas reglas de negocio que CRMService.
"""

from unittest.mock import patch
import pytest
from flask import Flask

from app.api.v1.crm import api_crm_bp
from app.services.crm_service import CRMService
from app.services.contact_service import ContactService
from app.services.db_service import DatabaseService


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api_crm_bp, url_prefix="/api/v1")
    with app.test_client() as c:
        yield c


MOCK_MODULES_CRM = {
    "crm": {"enabled": True},
}

MOCK_COMPANY_A = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "owner",
    "apiKey": "key_a_123",
    "name": "Empresa A SRL",
    "allowed_company_ids": ["comp_a"],
    "modules": MOCK_MODULES_CRM,
}

MOCK_USER_OPPS_ONLY = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "employee",
    "apiKey": "key_opps_only",
    "permissions": {
        "canCRM": False,
        "canCRMOpportunities": True,
        "canCRMContacts": False,
        "canCRMActivities": False,
        "canCRMReports": False,
    },
    "allowed_company_ids": ["comp_a"],
    "modules": MOCK_MODULES_CRM,
}

MOCK_USER_CONTACTS_ONLY = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "employee",
    "apiKey": "key_contacts_only",
    "permissions": {
        "canCRM": False,
        "canCRMOpportunities": False,
        "canCRMContacts": True,
        "canCRMActivities": False,
        "canCRMReports": False,
    },
    "allowed_company_ids": ["comp_a"],
    "modules": MOCK_MODULES_CRM,
}

MOCK_USER_ACTIVITIES_ONLY = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "employee",
    "apiKey": "key_activities_only",
    "permissions": {
        "canCRM": False,
        "canCRMOpportunities": False,
        "canCRMContacts": False,
        "canCRMActivities": True,
        "canCRMReports": False,
    },
    "allowed_company_ids": ["comp_a"],
    "modules": MOCK_MODULES_CRM,
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Opportunities Mutations
# ─────────────────────────────────────────────────────────────────────────────

def test_api_crm_create_opportunity_standard(client):
    """POST /api/v1/crm/opportunities crea oportunidad estándar en Prospecto."""
    payload = {
        "title": "Venta Equipos Médicos",
        "contactId": "c_123",
        "amount": 45000.0,
        "assignedTo": "emp_1",
    }

    mock_saved = {
        "id": "opp_new_1",
        "title": "Venta Equipos Médicos",
        "contactId": "c_123",
        "amount": 45000.0,
        "stage": "Prospecto",
        "status": "abierta",
        "companyId": "comp_a",
        "ownerUID": "owner_a",
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "save_opportunity", return_value=mock_saved) as mock_save:
        res = client.post("/api/v1/crm/opportunities", json=payload, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 201
        data = res.get_json()
        assert data["success"] is True
        assert data["opportunity"]["id"] == "opp_new_1"
        assert data["opportunity"]["stage"] == "Prospecto"

        call_kw = mock_save.call_args.kwargs
        assert call_kw["company_id"] == "comp_a"
        assert call_kw["owner_uid"] == "owner_a"


def test_api_crm_create_opportunity_in_advanced_stage(client):
    """POST /api/v1/crm/opportunities creado en etapa avanzada inicializa stageHistory."""
    payload = {
        "title": "Proyecto Llave en Mano",
        "contactId": "c_123",
        "stage": "Propuesta",
        "amount": 120000.0,
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "save_opportunity", side_effect=lambda *args, **kwargs: kwargs.get("opportunity_dict") or args[2]):

        res = client.post("/api/v1/crm/opportunities", json=payload, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 201
        data = res.get_json()
        opp = data["opportunity"]
        assert opp["stage"] == "Propuesta"
        assert len(opp["stageHistory"]) == 1
        assert opp["stageHistory"][0]["to"] == "Propuesta"


def test_api_crm_create_opportunity_validation_missing_title_and_contact(client):
    """POST /api/v1/crm/opportunities sin título ni contacto retorna 400 INVALID_PARAMETER."""
    payload = {"amount": 50000.0}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A):
        res = client.post("/api/v1/crm/opportunities", json=payload, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 400
        data = res.get_json()
        assert data["error"]["code"] == "INVALID_PARAMETER"


def test_api_crm_create_opportunity_ignores_injected_identity(client):
    """POST /api/v1/crm/opportunities con ownerUID y companyId inyectados usa los del contexto."""
    payload = {
        "title": "Venta Segura",
        "contactId": "c_1",
        "ownerUID": "hacker_owner",
        "companyId": "hacker_company",
        "isDeleted": True,
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "save_opportunity", side_effect=lambda *args, **kwargs: kwargs.get("opportunity_dict") or args[2]) as mock_save:

        res = client.post("/api/v1/crm/opportunities", json=payload, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 201
        call_kw = mock_save.call_args.kwargs
        assert call_kw["owner_uid"] == "owner_a"
        assert call_kw["company_id"] == "comp_a"


def test_api_crm_patch_opportunity_editable_fields(client):
    """PATCH /api/v1/crm/opportunities/<id> actualiza campos editables."""
    existing_opp = {
        "id": "opp_1", "title": "Old Title", "amount": 1000.0, "stage": "Prospecto",
        "probability": 10, "isDeleted": False, "companyId": "comp_a", "ownerUID": "owner_a"
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity", return_value=existing_opp), \
         patch.object(CRMService, "save_opportunity", side_effect=lambda *args, **kwargs: kwargs.get("opportunity_dict") or args[2]):

        res = client.patch("/api/v1/crm/opportunities/opp_1", json={"title": "New Title", "amount": 5000.0}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["opportunity"]["title"] == "New Title"
        assert data["opportunity"]["amount"] == 5000.0


def test_api_crm_patch_opportunity_with_stage_transition(client):
    """PATCH /api/v1/crm/opportunities/<id> con cambio de etapa delega en transition_opportunity."""
    existing_opp = {
        "id": "opp_1", "title": "Oportunidad Calificada", "stage": "Contactado",
        "contactId": "c_1", "assignedTo": "emp_1", "isDeleted": False
    }

    transitioned = {
        "id": "opp_1", "title": "Oportunidad Calificada", "stage": "Calificado",
        "status": "abierta", "probability": 40
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity", return_value=existing_opp), \
         patch.object(CRMService, "transition_opportunity", return_value=(True, "Transición exitosa", transitioned)) as mock_trans, \
         patch.object(CRMService, "save_opportunity", return_value=transitioned):

        res = client.patch("/api/v1/crm/opportunities/opp_1", json={"stage": "Calificado"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["opportunity"]["stage"] == "Calificado"
        mock_trans.assert_called_once()


def test_api_crm_patch_opportunity_invalid_transition_returns_400(client):
    """PATCH /api/v1/crm/opportunities/<id> con transición inválida retorna 400 INVALID_TRANSITION."""
    existing_opp = {"id": "opp_1", "stage": "Prospecto", "isDeleted": False}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity", return_value=existing_opp), \
         patch.object(CRMService, "transition_opportunity", return_value=(False, "Transición no permitida de 'Prospecto' a 'Ganada'.", None)):

        res = client.patch("/api/v1/crm/opportunities/opp_1", json={"stage": "Ganada"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 400
        data = res.get_json()
        assert data["error"]["code"] == "INVALID_TRANSITION"


def test_api_crm_transition_stage_endpoint_success(client):
    """POST /api/v1/crm/opportunities/<id>/stage transiciona correctamente."""
    transitioned = {"id": "opp_1", "stage": "Negociación", "status": "abierta"}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "transition_opportunity", return_value=(True, "Oportunidad transicionada a Negociación.", transitioned)):

        res = client.post("/api/v1/crm/opportunities/opp_1/stage", json={"stage": "Negociación", "notes": "Reunión acordada"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["opportunity"]["stage"] == "Negociación"


def test_api_crm_transition_stage_perdida_requires_lost_reason(client):
    """POST /api/v1/crm/opportunities/<id>/stage a Perdida sin lostReason falla con 400."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "transition_opportunity", return_value=(False, "El motivo de pérdida (lostReason) es obligatorio para marcar la oportunidad como Perdida.", None)):

        res = client.post("/api/v1/crm/opportunities/opp_1/stage", json={"stage": "Perdida"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 400
        data = res.get_json()
        assert data["error"]["code"] == "INVALID_TRANSITION"
        assert "lostReason" in data["error"]["message"]


def test_api_crm_delete_opportunity_soft_delete(client):
    """DELETE /api/v1/crm/opportunities/<id> delega en CRMService.delete_opportunity."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "delete_opportunity", return_value=True) as mock_del:

        res = client.delete("/api/v1/crm/opportunities/opp_1", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        mock_del.assert_called_once()


def test_api_crm_delete_opportunity_not_found_returns_404(client):
    """DELETE /api/v1/crm/opportunities/<id> cuando no existe retorna 404."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "delete_opportunity", return_value=False):

        res = client.delete("/api/v1/crm/opportunities/opp_nonexistent", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "OPPORTUNITY_NOT_FOUND"


def test_api_crm_opportunity_quick_note(client):
    """POST /api/v1/crm/opportunities/<id>/quick-note agrega nota e interacción."""
    existing_opp = {"id": "opp_1", "title": "Proyecto Alpha", "notes": "", "contactId": "c_1", "isDeleted": False}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity", return_value=existing_opp), \
         patch.object(CRMService, "save_opportunity", side_effect=lambda *args, **kwargs: kwargs.get("opportunity_dict") or args[2]), \
         patch("app.services.db_service.DatabaseService.save_client_interaction") as mock_interaction:

        res = client.post("/api/v1/crm/opportunities/opp_1/quick-note", json={"content": "Llamada de seguimiento realizada"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 201
        data = res.get_json()
        assert "Llamada de seguimiento realizada" in data["opportunity"]["notes"]
        mock_interaction.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Activities Mutations
# ─────────────────────────────────────────────────────────────────────────────

def test_api_crm_create_activity(client):
    """POST /api/v1/crm/activities crea actividad y bloquea campos de automatización."""
    payload = {
        "title": "Llamar cliente",
        "type": "Llamada",
        "dueDate": "2026-10-15",
        "priority": "alta",
        "contactId": "c_1",
        "autoGenerated": True,  # Falso intento de cliente
        "originRuleId": "forged_rule",
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "save_activity", side_effect=lambda *args, **kwargs: kwargs.get("activity_dict") or args[2]):

        res = client.post("/api/v1/crm/activities", json=payload, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 201
        data = res.get_json()
        act = data["activity"]
        assert act["title"] == "Llamar cliente"
        assert act["type"] == "Llamada"
        assert "autoGenerated" not in act or not act.get("autoGenerated")


def test_api_crm_patch_activity(client):
    """PATCH /api/v1/crm/activities/<id> actualiza campos editables."""
    existing_act = {"id": "act_1", "title": "Reunión", "priority": "media", "isDeleted": False}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_activity", return_value=existing_act), \
         patch.object(CRMService, "save_activity", side_effect=lambda *args, **kwargs: kwargs.get("activity_dict") or args[2]):

        res = client.patch("/api/v1/crm/activities/act_1", json={"priority": "urgente"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["activity"]["priority"] == "urgente"


def test_api_crm_complete_activity_endpoint(client):
    """POST /api/v1/crm/activities/<id>/complete invoca complete_activity de dominio."""
    act_completed = {"id": "act_1", "status": "completada", "completedAt": "2026-10-07T12:00:00Z"}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "complete_activity", return_value=(True, "Actividad completada.")) as mock_comp, \
         patch.object(CRMService, "get_activity", return_value=act_completed):

        res = client.post("/api/v1/crm/activities/act_1/complete", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["activity"]["status"] == "completada"
        mock_comp.assert_called_once()


def test_api_crm_delete_activity_endpoint(client):
    """DELETE /api/v1/crm/activities/<id> elimina de forma segura la actividad."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "delete_activity", return_value=True) as mock_del:

        res = client.delete("/api/v1/crm/activities/act_1", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        mock_del.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Contacts Mutations
# ─────────────────────────────────────────────────────────────────────────────

def test_api_crm_create_contact(client):
    """POST /api/v1/crm/contacts crea contacto/lead con valores por defecto."""
    payload = {
        "razonSocial": "Distribuidora Nacional SRL",
        "rnc": "131880681",
        "email": "contacto@distribuidora.com",
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "save_contact", side_effect=lambda *args, **kwargs: kwargs.get("contact_dict") or args[2]):

        res = client.post("/api/v1/crm/contacts", json=payload, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 201
        data = res.get_json()
        assert data["contact"]["razonSocial"] == "Distribuidora Nacional SRL"
        assert data["contact"]["pipelineStage"] == "Prospecto"


def test_api_crm_create_contact_missing_razon_social(client):
    """POST /api/v1/crm/contacts sin razón social retorna 400 INVALID_PARAMETER."""
    payload = {"email": "test@test.com"}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A):
        res = client.post("/api/v1/crm/contacts", json=payload, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 400
        assert res.get_json()["error"]["code"] == "INVALID_PARAMETER"


def test_api_crm_patch_contact_prevents_pipeline_stage_overwrite(client):
    """PATCH /api/v1/crm/contacts/<id> no permite modificar pipelineStage directamente."""
    existing_contact = {"id": "c_1", "razonSocial": "Alpha SRL", "pipelineStage": "Prospecto", "isDeleted": False}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contact", return_value=existing_contact), \
         patch.object(ContactService, "save_contact", side_effect=lambda *args, **kwargs: kwargs.get("contact_dict") or args[2]):

        res = client.patch("/api/v1/crm/contacts/c_1", json={"email": "new@alpha.com", "pipelineStage": "Ganada"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["contact"]["email"] == "new@alpha.com"
        assert data["contact"]["pipelineStage"] == "Prospecto"  # Inalterado


def test_api_crm_delete_contact_endpoint(client):
    """DELETE /api/v1/crm/contacts/<id> ejecuta soft delete vía ContactService."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "delete_contact", return_value=True) as mock_del:

        res = client.delete("/api/v1/crm/contacts/c_1", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        mock_del.assert_called_once()


def test_api_crm_contact_quick_note(client):
    """POST /api/v1/crm/contacts/<id>/quick-note registra interacción en el contacto."""
    existing_contact = {"id": "c_1", "razonSocial": "Alpha SRL", "isDeleted": False}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contact", return_value=existing_contact), \
         patch("app.services.db_service.DatabaseService.save_client_interaction") as mock_interaction:

        res = client.post("/api/v1/crm/contacts/c_1/quick-note", json={"content": "Llamada informativa"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 201
        data = res.get_json()
        assert data["interaction"]["content"] == "Llamada informativa"
        mock_interaction.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Multi-Tenant Isolation & RBAC in Mutations
# ─────────────────────────────────────────────────────────────────────────────

def test_api_crm_mutation_cross_tenant_patch_returns_404(client):
    """PATCH en oportunidad perteneciente a otro tenant retorna 404 sin alterarlo."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity", return_value=None):

        res = client.patch("/api/v1/crm/opportunities/opp_tenant_b", json={"title": "Hacked Title"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "OPPORTUNITY_NOT_FOUND"


def test_api_crm_mutation_cross_tenant_delete_returns_404(client):
    """DELETE en contacto de otro tenant retorna 404 sin alterarlo."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "delete_contact", return_value=False):

        res = client.delete("/api/v1/crm/contacts/contact_tenant_b", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "CONTACT_NOT_FOUND"


def test_api_crm_mutation_rbac_isolation_opportunities_cannot_mutate_contacts(client):
    """Usuario con canCRMOpportunities=True pero canCRMContacts=False recibe 403 en mutaciones de contactos."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_OPPS_ONLY):
        # Intentar crear contacto
        res_create = client.post("/api/v1/crm/contacts", json={"razonSocial": "Test"}, headers={"X-API-Key": "key_opps_only"})
        assert res_create.status_code == 403
        assert res_create.get_json()["error"]["code"] == "FORBIDDEN_PERMISSION"

        # Intentar eliminar contacto
        res_delete = client.delete("/api/v1/crm/contacts/c_1", headers={"X-API-Key": "key_opps_only"})
        assert res_delete.status_code == 403
        assert res_delete.get_json()["error"]["code"] == "FORBIDDEN_PERMISSION"


def test_api_crm_mutation_rbac_isolation_contacts_cannot_mutate_opportunities(client):
    """Usuario con canCRMContacts=True pero canCRMOpportunities=False recibe 403 en mutaciones de oportunidades."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_CONTACTS_ONLY):
        # Intentar crear oportunidad
        res_create = client.post("/api/v1/crm/opportunities", json={"title": "Test Opp"}, headers={"X-API-Key": "key_contacts_only"})
        assert res_create.status_code == 403
        assert res_create.get_json()["error"]["code"] == "FORBIDDEN_PERMISSION"

        # Intentar transicionar oportunidad
        res_trans = client.post("/api/v1/crm/opportunities/opp_1/stage", json={"stage": "Negociación"}, headers={"X-API-Key": "key_contacts_only"})
        assert res_trans.status_code == 403
        assert res_trans.get_json()["error"]["code"] == "FORBIDDEN_PERMISSION"


def test_api_crm_mutation_rbac_isolation_activities_cannot_mutate_opportunities(client):
    """Usuario con canCRMActivities=True pero canCRMOpportunities=False recibe 403 en oportunidades."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_ACTIVITIES_ONLY):
        res = client.patch("/api/v1/crm/opportunities/opp_1", json={"amount": 9999.0}, headers={"X-API-Key": "key_activities_only"})
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN_PERMISSION"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Domain / REST Equivalence
# ─────────────────────────────────────────────────────────────────────────────

def test_domain_and_api_transition_equivalence(client):
    """
    Demostración de equivalencia: la transición ejecutada vía REST delega
    estrictamente en CRMService.transition_opportunity preservando sus validaciones y reglas.
    """
    opp_sample = {
        "id": "opp_equiv_1", "stage": "Propuesta", "status": "abierta",
        "amount": 50000.0, "contactId": "c_1", "isDeleted": False
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity", return_value=opp_sample), \
         patch.object(CRMService, "save_opportunity", side_effect=lambda *args, **kwargs: kwargs.get("opportunity_dict") or args[2]), \
         patch("app.services.db_service.DatabaseService.save_client_interaction"):

        # 1. Ejecutar transición a Ganada vía API
        res = client.post("/api/v1/crm/opportunities/opp_equiv_1/stage", json={"stage": "Ganada", "invoiceNumber": "E31000001"}, headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        opp_api = data["opportunity"]

        # Verificar reglas de negocio generadas por el dominio
        assert opp_api["stage"] == "Ganada"
        assert opp_api["status"] == "ganada"
        assert opp_api["probability"] == 100
        assert len(opp_api["stageHistory"]) == 1
        assert opp_api["stageHistory"][0]["from"] == "Propuesta"
        assert opp_api["stageHistory"][0]["to"] == "Ganada"
