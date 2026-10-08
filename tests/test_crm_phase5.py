"""
Pruebas de Fase 5.1 y 5.1.1 (REST API CRM Security Hardening & Read-Only Endpoints).

Cubre:
1. Autenticación y Cabeceras (X-API-Key, Authorization: Bearer, 401 estructurado).
2. Aislamiento Multi-Tenant y Company Context (X-Company-ID, anti-impersonación, 403/404 sin filtración).
3. Anti-Enumeración Cross-Tenant (Contactos, Oportunidades, Actividades, Contact 360).
4. Permisos Granulares CRM (RBAC) y Aislamiento entre submódulos.
5. Reglas Legacy 'canClients' acotadas (sin escalación a Reportes o Actividades).
6. Validación Estricta de Entradas (paginación negativa/inválida, límites de tamaño).
7. Prevención de Fuga de Información en Respuestas de Error (500 controlado sin stack trace ni rutas internas).
8. Endpoints Funcionales Read-Only (Contactos, Oportunidades, Actividades, Métricas).
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


MOCK_MODULES_CRM = {
    "crm": {"enabled": True},
}

MOCK_COMPANY_A = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "owner",
    "apiKey": "key_a_123",
    "name": "Empresa A SRL",
    "allowed_company_ids": ["comp_a", "comp_a_subsidiary"],
    "modules": MOCK_MODULES_CRM,
}

MOCK_COMPANY_B = {
    "id": "comp_b",
    "ownerUID": "owner_b",
    "role": "owner",
    "apiKey": "key_b_456",
    "name": "Empresa B SRL",
    "allowed_company_ids": ["comp_b"],
    "modules": MOCK_MODULES_CRM,
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
    },
    "allowed_company_ids": ["comp_a"],
    "modules": MOCK_MODULES_CRM,
}

MOCK_USER_CONTACTS_ONLY = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "employee",
    "apiKey": "key_employee_contacts_only",
    "permissions": {
        "canCRM": False,
        "canCRMContacts": True,
        "canCRMOpportunities": False,
        "canCRMActivities": False,
        "canCRMReports": False,
    },
    "allowed_company_ids": ["comp_a"],
    "modules": MOCK_MODULES_CRM,
}

MOCK_USER_FALLBACK = {
    "id": "comp_a",
    "ownerUID": "owner_a",
    "role": "employee",
    "apiKey": "key_employee_fallback",
    "permissions": {
        "canClients": True,
    },
    "allowed_company_ids": ["comp_a"],
    "modules": MOCK_MODULES_CRM,
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


def test_api_crm_authorized_subsidiary_company_context(client):
    """Consulta especificando una filial autorizada explícitamente en allowed_company_ids retorna 200."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contacts", return_value=[]):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_a_123", "X-Company-ID": "comp_a_subsidiary"})
        assert res.status_code == 200


def test_api_crm_unauthorized_company_header_rejected(client):
    """Cliente autenticado como Empresa A intenta acceder a Empresa B vía X-Company-ID -> 403 Forbidden."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_a_123", "X-Company-ID": "comp_b"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "FORBIDDEN_COMPANY"


def test_api_crm_unauthorized_company_query_param_rejected(client):
    """Cliente autenticado como Empresa A intenta acceder a Empresa B vía query param -> 403 Forbidden."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A):
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


# ─────────────────────────────────────────────────────────────────────────────
# 5. Fase 5.1.1 — Auditoría y Hardening de Seguridad
# ─────────────────────────────────────────────────────────────────────────────

def test_security_01_missing_api_key(client):
    """Escenario 1: Request sin credencial retorna 401 AUTH_REQUIRED."""
    res = client.get("/api/v1/crm/opportunities")
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "AUTH_REQUIRED"


def test_security_02_invalid_api_key(client):
    """Escenario 2: Request con API Key inexistente/revocada retorna 401 AUTH_INVALID."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=None):
        res = client.get("/api/v1/crm/opportunities", headers={"X-API-Key": "revoked_or_fake_key"})
        assert res.status_code == 401
        assert res.get_json()["error"]["code"] == "AUTH_INVALID"


def test_security_03_invalid_bearer_format(client):
    """Escenario 3: Request con Bearer inválido o malformado."""
    # Bearer vacío o sin token
    res_empty = client.get("/api/v1/crm/opportunities", headers={"Authorization": "Bearer "})
    assert res_empty.status_code == 401
    assert res_empty.get_json()["error"]["code"] == "AUTH_REQUIRED"

    # Bearer no registrado en base de datos
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=None):
        res_fake = client.get("/api/v1/crm/opportunities", headers={"Authorization": "Bearer fake_bearer_token"})
        assert res_fake.status_code == 401
        assert res_fake.get_json()["error"]["code"] == "AUTH_INVALID"


def test_security_04_unauthorized_company_id_header(client):
    """Escenario 4: Company ID no autorizado en cabecera retorna 403 FORBIDDEN_COMPANY."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A):
        res = client.get("/api/v1/crm/opportunities", headers={"X-API-Key": "key_a_123", "X-Company-ID": "comp_unauthorized"})
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN_COMPANY"


def test_security_05_cross_tenant_opportunity_returns_404_no_leak(client):
    """
    Escenario 5: Consultar una oportunidad de otra empresa retorna 404
    sin revelar título, cliente, monto ni existencia.
    """
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunity", return_value=None):
        res = client.get("/api/v1/crm/opportunities/opp_other_company_id", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 404
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "OPPORTUNITY_NOT_FOUND"
        # No leak de datos
        assert "opp_other_company_id" not in data["error"]["message"]
        assert "amount" not in data
        assert "assignedTo" not in data


def test_security_06_cross_tenant_contact_returns_404_no_leak(client):
    """
    Escenario 6: Consultar un contacto de otra empresa retorna 404
    sin revelar datos de la otra empresa.
    """
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contact", return_value=None):
        res = client.get("/api/v1/crm/contacts/contact_other_company_id", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 404
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "CONTACT_NOT_FOUND"
        assert "contact_other_company_id" not in data["error"]["message"]


def test_security_07_cross_tenant_activity_isolation(client):
    """Escenario 7: Listar actividades delega estrictamente con company_id autenticado."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_activities") as mock_acts:
        mock_acts.return_value = []
        res = client.get("/api/v1/crm/activities", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        mock_acts.assert_called_once_with(
            owner_uid="owner_a",
            sandbox=True,
            include_completed=True,
            company_id="comp_a",
            branch_id=None,
            project_id=None,
            contact_id=None,
            opportunity_id=None,
        )


def test_security_08_cross_tenant_contact_360_returns_404(client):
    """Escenario 8: Contact 360 de un contacto inexistente/cross-tenant retorna 404 sin leaks."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_contact_360", return_value={"contact": None}):
        res = client.get("/api/v1/crm/contacts/foreign_contact_id/360", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 404
        data = res.get_json()
        assert data["error"]["code"] == "CONTACT_NOT_FOUND"


def test_security_09_permission_denied_granular(client):
    """Escenario 9: Acceso denegado cuando falta el permiso requerido."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_RESTRICTED):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_employee_restricted"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"]["code"] == "FORBIDDEN_PERMISSION"
        assert "canCRMContacts" in data["error"]["message"]


def test_security_10_permission_isolation_contacts_vs_reports(client):
    """
    Escenario 10: Aislamiento de permisos entre submódulos.
    canCRMContacts=True permite /crm/contacts y /crm/contacts/<id>/360,
    pero NO permite /crm/metrics (canCRMReports=False) -> 403.
    """
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_CONTACTS_ONLY), \
         patch.object(ContactService, "get_contacts", return_value=[]), \
         patch.object(CRMService, "get_contact_360", return_value={"contact": {"id": "c1"}}):

        # Contactos permitido
        res_contacts = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_employee_contacts_only"})
        assert res_contacts.status_code == 200

        # Contact 360 permitido (requiere canCRMContacts)
        res_360 = client.get("/api/v1/crm/contacts/c1/360", headers={"X-API-Key": "key_employee_contacts_only"})
        assert res_360.status_code == 200

        # Métricas denegado (requiere canCRMReports)
        res_metrics = client.get("/api/v1/crm/metrics", headers={"X-API-Key": "key_employee_contacts_only"})
        assert res_metrics.status_code == 403
        assert res_metrics.get_json()["error"]["code"] == "FORBIDDEN_PERMISSION"


def test_security_11_fake_owner_uid_injection_ignored(client):
    """Escenario 11: Parámetro ownerUID malicioso en query no altera el owner de la credencial."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(CRMService, "get_opportunities") as mock_opps:
        mock_opps.return_value = []
        res = client.get("/api/v1/crm/opportunities?ownerUID=attacker_injected_uid", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        # Confirma que se usó owner_a de la base de datos, nunca el inyectado
        mock_opps.assert_called_once_with(
            owner_uid="owner_a",
            sandbox=True,
            company_id="comp_a",
            include_closed=True,
            branch_id=None,
            project_id=None,
            contact_id=None,
        )


def test_security_12_fake_company_id_rejected_403(client):
    """Escenario 12: Inyección de company_id no autorizado retorna 403 FORBIDDEN_COMPANY."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A):
        res = client.get("/api/v1/crm/opportunities?company_id=fake_or_competitor_co", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN_COMPANY"


def test_security_13_nonexistent_company_id_no_silent_fallback(client):
    """Escenario 13: Company ID inexistente retorna 403 y no hace fallback silencioso a la empresa default."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_a_123", "X-Company-ID": "non_existent_company_999"})
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN_COMPANY"


def test_security_14_invalid_pagination_parameters(client):
    """Escenario 14: Paginación con valores negativos, 0 o strings no enteros retorna 400."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A):
        # Límite negativo
        res1 = client.get("/api/v1/crm/contacts?limit=-5", headers={"X-API-Key": "key_a_123"})
        assert res1.status_code == 400
        assert res1.get_json()["error"]["code"] == "INVALID_PAGINATION"

        # Límite cero
        res2 = client.get("/api/v1/crm/contacts?limit=0", headers={"X-API-Key": "key_a_123"})
        assert res2.status_code == 400
        assert res2.get_json()["error"]["code"] == "INVALID_PAGINATION"

        # Offset negativo
        res3 = client.get("/api/v1/crm/opportunities?offset=-10", headers={"X-API-Key": "key_a_123"})
        assert res3.status_code == 400
        assert res3.get_json()["error"]["code"] == "INVALID_PAGINATION"

        # Offset no numérico
        res4 = client.get("/api/v1/crm/activities?limit=abc", headers={"X-API-Key": "key_a_123"})
        assert res4.status_code == 400
        assert res4.get_json()["error"]["code"] == "INVALID_PAGINATION"


def test_security_15_excessive_parameter_strings_handled_safely(client):
    """Escenario 15: Parámetros string con longitudes excesivas son sanitizados/truncados sin provocar scans desbordados ni crash."""
    excessive_search = "A" * 5000
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contacts", return_value=[]):
        res = client.get(f"/api/v1/crm/contacts?search={excessive_search}", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True


def test_security_16_internal_error_no_stack_trace_or_path_leak(client):
    """Escenario 16: Excepciones internas no exponen stack traces, rutas del filesystem ni colecciones Firestore en el payload JSON."""
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_COMPANY_A), \
         patch.object(ContactService, "get_contacts", side_effect=RuntimeError("Firestore connection failed: /companies/comp_a/contacts")):
        res = client.get("/api/v1/crm/contacts", headers={"X-API-Key": "key_a_123"})
        assert res.status_code == 500
        data = res.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        # Verificar que NO se fuga la ruta de Firestore ni el mensaje interno
        assert "/companies/comp_a/contacts" not in data["error"]["message"]
        assert "RuntimeError" not in data["error"]["message"]
        assert "Traceback" not in json.dumps(data)


def test_security_17_legacy_can_clients_does_not_grant_metrics_or_activities(client):
    """
    Escenario 17: canClients otorga acceso a contactos y oportunidades (compatibilidad legacy),
    pero ESTRICTAMENTE RECHAZA (403) el acceso a métricas comerciales y actividades.
    """
    with patch("app.services.db_service.DatabaseService.get_company_by_api_key", return_value=MOCK_USER_FALLBACK):
        # Rechazado en métricas
        res_metrics = client.get("/api/v1/crm/metrics", headers={"X-API-Key": "key_employee_fallback"})
        assert res_metrics.status_code == 403
        assert res_metrics.get_json()["error"]["code"] == "FORBIDDEN_PERMISSION"

        # Rechazado en actividades
        res_acts = client.get("/api/v1/crm/activities", headers={"X-API-Key": "key_employee_fallback"})
        assert res_acts.status_code == 403
        assert res_acts.get_json()["error"]["code"] == "FORBIDDEN_PERMISSION"
