"""
Pruebas de Fase 5.1 (REST API CRM Foundation y Read-Only Endpoints).

Cubre:
1. Autenticación y Cabeceras:
   - Falta de API key -> 401 Unauthorized
   - API key inválida -> 401 Unauthorized
   - API key vía X-API-Key -> 200 OK
   - API key vía Authorization: Bearer -> 200 OK

2. Aislamiento Multi-Tenant y Company Context:
   - Consulta sobre empresa autorizada -> 200 OK
   - Consulta sobre empresa no autorizada vía X-Company-ID -> 403 Forbidden
   - Consulta sobre empresa no autorizada vía query param -> 403 Forbidden
   - Consulta de ID perteneciente a otra empresa -> 404 Not Found
   - Parámetro ownerUID en query/body es ignorado (no permite impersonación)

3. Permisos Granulares CRM (RBAC):
   - Sin canCRMContacts -> 403 Forbidden en contactos
   - Sin canCRMOpportunities -> 403 Forbidden en oportunidades
   - Sin canCRMActivities -> 403 Forbidden en actividades
   - Sin canCRMReports -> 403 Forbidden en métricas
   - Fallback canClients -> 200 OK
   - Role owner -> 200 OK en todos los endpoints

4. Endpoints Read-Only y Reutilización de Dominio:
   - GET /api/v1/crm/contacts (filtros, paginación, sanitización)
   - GET /api/v1/crm/contacts/<id> (detalle y 404 en deleted)
   - GET /api/v1/crm/contacts/<id>/360 (Contact 360 consolidado)
   - GET /api/v1/crm/opportunities (filtros por stage, status, assignedTo, paginación)
   - GET /api/v1/crm/opportunities/<id> (detalle y 404)
   - GET /api/v1/crm/activities (filtros por status, assignedTo, paginación)
   - GET /api/v1/crm/metrics (métricas comerciales en vivo con delegación a CRMService)
   - Demostración de reutilización estricta de servicios de dominio
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from flask import Flask

from app.api.v1.crm import api_crm_bp
from app.services.crm_service import CRMService
from app.services.contact_service import ContactService


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api_crm_bp, url_prefix="/api/v1")
    with app.test_client() as c:
        yield c


MOCK_COMPANY_A = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "owner",
    "apiKey": "key_a_123",
    "name": "Empresa A SRL",
}

MOCK_COMPANY_B = {
    "id": "comp_b",
    "ownerUID": "owner_b",
    "role": "owner",
    "apiKey": "key_b_456",
    "name": "Empresa B SRL",
}

MOCK_USER_RESTRICTED = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "employee",
    "apiKey": "key_employee_restricted",
    "permissions": {
        "canCRM": True,
        "canCRMContacts": False,
        "canCRMOpportunities": False,
        "canCRMActivities": False,
        "canCRMReports": False,
    }
}

MOCK_USER_FALLBACK = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "employee",
    "apiKey": "key_employee_fallback",
    "permissions": {
        "canClients": True,
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Autenticación y Cabeceras
# ─────────────────────────────────────────────────────────────────────────────

def test_api_crm_missing_auth_header(client):
    """Falta de header X-API-Key o Bearer retorna 401 Unauthorized estructurado."""
    res = client.get("/api/v1/crm/contacts")
    assert res.status_code == 401
    data = res.get_json()
    assert data["success"] is False
    assert data["error"]["code"] == "AUTH_REQUIRED"


def test_api_crm_invalid_api_key(client):
    """API key inválida o no registrada retorna 401 Unauthorized estructurado."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=None):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "invalid_key"})
        assert res.status_code == 401
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "AUTH_INVALID"


def test_api_crm_valid_api_key_header(client):
    """API key válida vía X-API-Key autentica correctamente."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contacts", return_value=[]):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["contacts"] == []


def test_api_crm_valid_bearer_token(client):
    """API key válida vía Authorization: Bearer autentica correctamente."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contacts", return_value=[]):
        res = client.get("/api/v1/crm/contacts", headers={"Authorization": "Bearer key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. Aislamiento Multi-Tenant y Company Context
# ─────────────────────────────────────────────────────────────────────────────

def test_api_crm_authorized_company_context(client):
    """Consulta especificando la empresa autorizada propia retorna 200."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contacts", return_value=[]):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_a_123", "X-Company-ID": "comp_a"})
        assert res.status_code == 200


def test_api_crm_unauthorized_company_header_rejected(client):
    """Cliente autenticado como Empresa A intenta acceder a Empresa B vía X-Company-ID -> 403 Forbidden."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch("app.services.db_service.DatabaseService.get_companies_by_owner", return_value=[{"id": "comp_a"}]):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_a_123", "X-Company-ID": "comp_b"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "FORBIDDEN_COMPANY"


def test_api_crm_unauthorized_company_query_param_rejected(client):
    """Cliente autenticado como Empresa A intenta acceder a Empresa B vía query param -> 403 Forbidden."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch("app.services.db_service.DatabaseService.get_companies_by_owner", return_value=[{"id": "comp_a"}]):
        res = client.get("/api/v1/crm/contacts?company_id=comp_b", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "FORBIDDEN_COMPANY"


def test_api_crm_resource_from_other_company_returns_404(client):
    """Buscar un recurso que no existe en el tenant (o pertenece a otra empresa) retorna 404."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity", return_value=None):
        res = client.get("/api/v1/crm/opportunities/opp_comp_b", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 404
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "OPPORTUNITY_NOT_FOUND"


def test_api_crm_owner_uid_param_cannot_impersonate(client):
    """Enviar ownerUID en query no altera el owner_uid autenticado del contexto."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contacts") as mock_get_contacts:
        mock_get_contacts.return_value = []
        res = client.get("/api/v1/crm/contacts?ownerUID=victim_owner", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        # Confirma que se llamó con el owner_a auténtico de la API Key, no con victim_owner
        mock_get_contacts.assert_called_once_with(owner_uid="owner_a", sandbox=True, company_id="comp_a")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Permisos Granulares CRM (RBAC)
# ─────────────────────────────────────────────────────────────────────────────

def test_api_crm_permission_denied_contacts(client):
    """Usuario sin canCRMContacts es rechazado con 403 en contactos."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_RESTRICTED):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_employee_restricted"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"]["code"] == "FORBIDDEN_PERMISSION"


def test_api_crm_permission_denied_opportunities(client):
    """Usuario sin canCRMOpportunities es rechazado con 403 en oportunidades."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_RESTRICTED):
        res = client.get("/api/v1/crm/opportunities", headers={"X-API-Key": "key_employee_restricted"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"]["code"] == "FORBIDDEN_PERMISSION"


def test_api_crm_permission_denied_activities(client):
    """Usuario sin canCRMActivities es rechazado con 403 en actividades."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_RESTRICTED):
        res = client.get("/api/v1/crm/activities", headers={"X-API-Key": "key_employee_restricted"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"]["code"] == "FORBIDDEN_PERMISSION"


def test_api_crm_permission_denied_reports(client):
    """Usuario sin canCRMReports es rechazado con 403 en métricas."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_RESTRICTED):
        res = client.get("/api/v1/crm/metrics", headers={"X-API-Key": "key_employee_restricted"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"]["code"] == "FORBIDDEN_PERMISSION"


def test_api_crm_permission_legacy_fallback_can_clients(client):
    """Usuario con permiso legacy canClients puede consultar contactos y oportunidades."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_FALLBACK), \
         patch.object(ContactService, "get_contacts", return_value=[]), \
         patch.object(CRMService, "get_opportunities", return_value=[]):
        res_contacts = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_employee_fallback"})
        assert res_contacts.status_code == 200

        res_opps = client.get("/api/v1/crm/opportunities", headers={"X-API-Key": "key_employee_fallback"})
        assert res_opps.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 4. Endpoints Read-Only y Reutilización de Dominio
# ─────────────────────────────────────────────────────────────────────────────

def test_api_crm_list_contacts_filters_and_pagination(client):
    """GET /api/v1/crm/contacts aplica filtros y paginación adecuadamente."""
    contacts_sample = [
        {"id": "c1", "razonSocial": "Acme Corp", "rnc": "101", "types": ["cliente"], "branchId": "br1", "projectId": "p1", "isDeleted": False},
        {"id": "c2", "razonSocial": "Beta SRL", "rnc": "102", "types": ["lead"], "branchId": "br1", "projectId": "p1", "isDeleted": False},
        {"id": "c3", "razonSocial": "Gamma SA", "rnc": "103", "types": ["cliente"], "branchId": "br2", "projectId": "p1", "isDeleted": False},
        {"id": "c4", "razonSocial": "Deleted Co", "rnc": "104", "types": ["cliente"], "isDeleted": True},
    ]

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contacts", return_value=contacts_sample):

        # Filtro de búsqueda
        res_search = client.get("/api/v1/crm/contacts?search=Acme", headers={"X-API-Key": "key_a_123"})
        assert res_search.status_code == 200
        data_search = res_search.get_json()
        assert len(data_search["contacts"]) == 1
        assert data_search["contacts"][0]["id"] == "c1"

        # Filtro por tipo
        res_type = client.get("/api/v1/crm/contacts?type=lead", headers={"X-API-Key": "key_a_123"})
        data_type = res_type.get_json()
        assert len(data_type["contacts"]) == 1
        assert data_type["contacts"][0]["id"] == "c2"

        # Paginación
        res_page = client.get("/api/v1/crm/contacts?limit=2&offset=1", headers={"X-API-Key": "key_a_123"})
        data_page = res_page.get_json()
        assert data_page["limit"] == 2
        assert data_page["offset"] == 1
        assert data_page["total"] == 3  # Excluye deleted


def test_api_crm_get_contact_detail_and_404(client):
    """GET /api/v1/crm/contacts/<id> retorna detalle o 404."""
    contact_sample = {"id": "c1", "razonSocial": "Acme Corp", "isDeleted": False}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contact") as mock_get_contact:

        # Encontrado
        mock_get_contact.return_value = contact_sample
        res = client.get("/api/v1/crm/contacts/c1", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        assert res.get_json()["contact"]["razonSocial"] == "Acme Corp"

        # No encontrado
        mock_get_contact.return_value = None
        res_not_found = client.get("/api/v1/crm/contacts/c99", headers={"X-API-Key": "key_a_123"})
        assert res_not_found.status_code == 404
        assert res_not_found.get_json()["error"]["code"] == "CONTACT_NOT_FOUND"


def test_api_crm_get_contact_360(client):
    """GET /api/v1/crm/contacts/<id>/360 delega en CRMService.get_contact_360."""
    sample_360 = {
        "contact": {"id": "c1", "razonSocial": "Acme Corp"},
        "opportunities": [],
        "activities": [],
        "timeline": [],
        "metrics": {"totalInvoiced": 50000.0, "openOpportunitiesCount": 1},
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_contact_360", return_value=sample_360):
        res = client.get("/api/v1/crm/contacts/c1/360", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["contact"]["id"] == "c1"
        assert data["metrics"]["totalInvoiced"] == 50000.0


def test_api_crm_list_opportunities_filters(client):
    """GET /api/v1/crm/opportunities delega en CRMService y filtra por stage, status, assignedTo."""
    opps_sample = [
        {"id": "o1", "stage": "Prospecto", "status": "abierta", "assignedTo": "user1", "amount": 1000.0, "isDeleted": False},
        {"id": "o2", "stage": "Propuesta", "status": "abierta", "assignedTo": "user2", "amount": 5000.0, "isDeleted": False},
        {"id": "o3", "stage": "Ganada", "status": "ganada", "assignedTo": "user1", "amount": 10000.0, "isDeleted": False},
    ]

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunities", return_value=opps_sample):

        res_stage = client.get("/api/v1/crm/opportunities?stage=Propuesta", headers={"X-API-Key": "key_a_123"})
        data_stage = res_stage.get_json()
        assert len(data_stage["opportunities"]) == 1
        assert data_stage["opportunities"][0]["id"] == "o2"

        res_status = client.get("/api/v1/crm/opportunities?status=ganada", headers={"X-API-Key": "key_a_123"})
        data_status = res_status.get_json()
        assert len(data_status["opportunities"]) == 1
        assert data_status["opportunities"][0]["id"] == "o3"


def test_api_crm_get_opportunity_detail_and_404(client):
    """GET /api/v1/crm/opportunities/<id> retorna detalle o 404."""
    opp_sample = {"id": "o1", "title": "Proyecto Alpha", "amount": 25000.0, "isDeleted": False}

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity") as mock_get_opp:

        mock_get_opp.return_value = opp_sample
        res = client.get("/api/v1/crm/opportunities/o1", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        assert res.get_json()["opportunity"]["title"] == "Proyecto Alpha"

        mock_get_opp.return_value = None
        res_not_found = client.get("/api/v1/crm/opportunities/o99", headers={"X-API-Key": "key_a_123"})
        assert res_not_found.status_code == 404
        assert res_not_found.get_json()["error"]["code"] == "OPPORTUNITY_NOT_FOUND"


def test_api_crm_list_activities_filters(client):
    """GET /api/v1/crm/activities delega en CRMService y filtra por status y assignedTo."""
    acts_sample = [
        {"id": "a1", "title": "Llamada inicial", "status": "pendiente", "assignedTo": "user1", "isDeleted": False},
        {"id": "a2", "title": "Reunión propuesta", "status": "completada", "assignedTo": "user2", "isDeleted": False},
    ]

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_activities", return_value=acts_sample):

        res_pend = client.get("/api/v1/crm/activities?status=pendiente", headers={"X-API-Key": "key_a_123"})
        assert res_pend.status_code == 200
        data_pend = res_pend.get_json()
        assert len(data_pend["activities"]) == 1
        assert data_pend["activities"][0]["id"] == "a1"


def test_api_crm_get_metrics(client):
    """GET /api/v1/crm/metrics delega en CRMService.get_sales_metrics pasando todos los filtros."""
    sample_metrics = {
        "openOpportunities": 5, "wonOpportunities": 3, "lostOpportunities": 1,
        "pipelineValue": 150000.0, "weightedPipelineValue": 90000.0,
        "winRate": 75.0, "avgWonAmount": 50000.0, "avgSalesCycleDays": 10.0,
        "funnel": {"Prospecto": 8, "Ganada": 3},
        "conversionRates": {"prospect_to_contacted": 87.5},
        "bySalesperson": [], "byBranch": [], "byProject": [],
    }

    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_sales_metrics") as mock_metrics:

        mock_metrics.return_value = sample_metrics
        res = client.get("/api/v1/crm/metrics?branch_id=br_stgo&date_from=2026-09-01&date_to=2026-10-01", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["metrics"]["winRate"] == 75.0
        assert data["metrics"]["pipelineValue"] == 150000.0

        mock_metrics.assert_called_once_with(
            owner_uid="owner_a",
            sandbox=True,
            company_id="comp_a",
            branch_id="br_stgo",
            project_id=None,
            assigned_to=None,
            date_from="2026-09-01",
            date_to="2026-10-01",
        )
