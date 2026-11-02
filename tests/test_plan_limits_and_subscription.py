"""Tests exhaustivos para la gestión de límites de entidades en planes y proyección en suscripción."""

import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from app.services.db_service import DatabaseService


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


MOCK_OWNER = {
    "uid": "owner_sub_123",
    "ownerUID": "owner_sub_123",
    "name": "Propietario ERP",
    "email": "owner@erp.do",
    "role": "owner",
    "status": "active",
    "disabled": False,
    "permissions": {
        "canModifySettings": True,
        "canManageCompanySettings": True,
        "canViewSubscription": True,
        "canManagePOS": True,
        "isPosSupervisor": True,
        "canHREmployees": True,
        "canInvoice": True,
        "canManageWarehouses": True,
        "canManageInventory": True,
    },
}

MOCK_PLAN = {
    "id": "plan_test",
    "name": "Plan Test Pro",
    "documentLimit": 100,
    "additionalDocumentCost": 0.20,
    "userLimit": 2,
    "additionalUserCost": 12.0,
    "branchLimit": 1,
    "additionalBranchCost": 30.0,
    "warehouseLimit": 1,
    "additionalWarehouseCost": 25.0,
    "employeeLimit": 5,
    "additionalEmployeeCost": 4.0,
    "boxLimit": 1,
    "additionalBoxCost": 15.0,
    "modules": {
        "e_cf": {"enabled": True},
        "nomina": {"enabled": True},
        "pos": {"enabled": True},
        "inventario": {"enabled": True},
    },
}


class TestPlanLimitsResolution:
    """Verifica que DatabaseService resuelva los límites y costos de todas las entidades."""

    def test_profile_resolves_all_limits_from_plan(self):
        with patch.object(DatabaseService, 'get_company') as mock_get_company, \
             patch.object(DatabaseService, 'get_plan') as mock_get_plan:

            mock_get_company.return_value = {
                "owner_uid": "owner_sub_123",
                "company_name": "Empresa Test SA",
                "plan_id": "plan_nomina_pro",
                "plan_version": 1,
            }
            mock_get_plan.return_value = {
                "id": "plan_nomina_pro",
                "name": "Plan Pro Nómina",
                "documentLimit": 500,
                "additionalDocumentCost": 0.15,
                "userLimit": 5,
                "additionalUserCost": 10.0,
                "branchLimit": 3,
                "additionalBranchCost": 25.0,
                "warehouseLimit": 4,
                "additionalWarehouseCost": 20.0,
                "employeeLimit": 25,
                "additionalEmployeeCost": 3.5,
                "boxLimit": 2,
                "additionalBoxCost": 15.0,
            }

            profile = DatabaseService.get_company_profile("owner_sub_123", company_id="comp_sub_123")
            assert profile is not None
            assert profile["documentLimit"] == 500
            assert profile["additionalDocumentCost"] == 0.15
            assert profile["userLimit"] == 5
            assert profile["additionalUserCost"] == 10.0
            assert profile["branchLimit"] == 3
            assert profile["additionalBranchCost"] == 25.0
            assert profile["warehouseLimit"] == 4
            assert profile["additionalWarehouseCost"] == 20.0
            assert profile["employeeLimit"] == 25
            assert profile["additionalEmployeeCost"] == 3.5
            assert profile["boxLimit"] == 2
            assert profile["additionalBoxCost"] == 15.0


class TestNonBlockingResourceCreation:
    """Verifica que la creación de entidades NO se bloquee al alcanzar límites."""

    @pytest.fixture(autouse=True)
    def common_mocks(self):
        with patch.object(DatabaseService, 'get_user_profile', return_value=MOCK_OWNER), \
             patch.object(DatabaseService, 'get_associated_companies', return_value=[{'ownerUID': 'owner_sub_123', 'id': 'comp_sub_123', 'companyName': 'Empresa SA', 'role': 'owner'}]), \
             patch.object(DatabaseService, 'get_company', return_value={'id': 'comp_sub_123', 'owner_uid': 'owner_sub_123', 'company_name': 'Empresa SA', 'plan_id': 'plan_test', 'status': 'active', 'configured': True}), \
             patch.object(DatabaseService, 'get_company_context', return_value={'role': 'owner', 'owner_uid': 'owner_sub_123', 'permissions': MOCK_OWNER['permissions'], 'company_name': 'Empresa SA'}), \
             patch.object(DatabaseService, 'get_membership', return_value={'status': 'active'}), \
             patch.object(DatabaseService, 'get_plan', return_value=MOCK_PLAN):
            yield

    def test_branch_creation_allowed_past_limit(self, client):
        """Crear sucursal con límite alcanzado debe registrar exitosamente y advertir cargo adicional."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_branches') as mock_branches, \
             patch.object(DatabaseService, 'save_branch') as mock_save_branch:

            mock_profile.return_value = {
                "companyName": "Empresa SA",
                "branchLimit": 1,
                "additionalBranchCost": 20.0,
                "configured": True,
            }
            # Ya existe 1 sucursal
            mock_branches.return_value = [{"id": "b1", "name": "Principal"}]

            with client.session_transaction() as sess:
                sess['user'] = MOCK_OWNER
                sess['selected_company_id'] = 'comp_sub_123'
                sess['selected_owner_uid'] = 'owner_sub_123'
                sess['is_sandbox_mode'] = False

            resp = client.post('/settings/branches/save', data={
                'name': 'Sucursal Santiago',
                'code': 'STI-01',
                'address': 'Av 27 de Febrero',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_save_branch.assert_called_once()
            assert "superado el l\xc3\xadmite de 1 sucursales".encode('utf-8') in resp.data or b"superado el" in resp.data

    def test_pos_box_creation_allowed_past_limit(self, client):
        """Crear caja registradora con límite alcanzado no debe bloquear."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_cash_registers') as mock_registers, \
             patch.object(DatabaseService, 'save_cash_register') as mock_save_reg:

            mock_profile.return_value = {
                "companyName": "Empresa SA",
                "boxLimit": 1,
                "additionalBoxCost": 15.0,
                "configured": True,
            }
            mock_registers.return_value = [
                {"id": "caja-1", "name": "Caja 1", "createdAt": "2026-11-01T12:00:00Z"}
            ]

            with client.session_transaction() as sess:
                sess['user'] = MOCK_OWNER
                sess['selected_company_id'] = 'comp_sub_123'
                sess['selected_owner_uid'] = 'owner_sub_123'
                sess['is_sandbox_mode'] = False
                sess['company_profile_pos_enabled'] = True
                sess['company_modules'] = MOCK_PLAN['modules']

            resp = client.post('/pos/register/new', data={
                'name': 'Caja 2 Ventas',
                'warehouseId': 'wh_1',
            }, follow_redirects=False)

            assert resp.status_code == 302
            mock_save_reg.assert_called_once()

    def test_warehouse_creation_allowed_past_limit(self, client):
        """Crear almacén con límite alcanzado no debe bloquear."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_warehouses') as mock_wh, \
             patch.object(DatabaseService, 'save_warehouse') as mock_save_wh:

            mock_profile.return_value = {
                "companyName": "Empresa SA",
                "warehouseLimit": 1,
                "additionalWarehouseCost": 18.0,
                "configured": True,
            }
            mock_wh.return_value = [{"id": "w1", "name": "Almacén Central"}]

            with client.session_transaction() as sess:
                sess['user'] = MOCK_OWNER
                sess['selected_company_id'] = 'comp_sub_123'
                sess['selected_owner_uid'] = 'owner_sub_123'
                sess['is_sandbox_mode'] = False
                sess['company_modules'] = MOCK_PLAN['modules']

            resp = client.post('/inventory/warehouses/new', data={
                'name': 'Almacén Secundario',
                'code': 'ALM-02',
            }, follow_redirects=False)

            assert resp.status_code == 302
            mock_save_wh.assert_called_once()


class TestSubscriptionPageRendering:
    """Verifica que la página /suscripcion calcule y renderice correctamente todas las métricas."""

    @pytest.fixture(autouse=True)
    def common_mocks(self):
        with patch.object(DatabaseService, 'get_user_profile', return_value=MOCK_OWNER), \
             patch.object(DatabaseService, 'get_associated_companies', return_value=[{'ownerUID': 'owner_sub_123', 'id': 'comp_sub_123', 'companyName': 'Empresa SA', 'role': 'owner'}]), \
             patch.object(DatabaseService, 'get_company', return_value={'id': 'comp_sub_123', 'owner_uid': 'owner_sub_123', 'company_name': 'Empresa SA', 'plan_id': 'plan_test', 'status': 'active', 'configured': True}), \
             patch.object(DatabaseService, 'get_company_context', return_value={'role': 'owner', 'owner_uid': 'owner_sub_123', 'permissions': MOCK_OWNER['permissions'], 'company_name': 'Empresa SA'}), \
             patch.object(DatabaseService, 'get_membership', return_value={'status': 'active'}), \
             patch.object(DatabaseService, 'get_plan', return_value=MOCK_PLAN):
            yield

    def test_subscription_page_metrics_calculation(self, client):
        """Verifica el cálculo de recursos, excedentes y desglose en /suscripcion."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_invoice_stats') as mock_stats, \
             patch.object(DatabaseService, 'get_payments', return_value=[]), \
             patch.object(DatabaseService, 'get_billing_history', return_value=[]), \
             patch.object(DatabaseService, 'get_storage_usage_mb', return_value=45.5), \
             patch.object(DatabaseService, 'get_team_members') as mock_team, \
             patch.object(DatabaseService, 'get_branches') as mock_branches, \
             patch.object(DatabaseService, 'get_warehouses') as mock_wh, \
             patch.object(DatabaseService, 'get_cash_registers') as mock_boxes, \
             patch('app.services.hr_data_service.get_employees') as mock_employees, \
             patch('app.services.db_service.db_firestore') as mock_firestore:

            mock_doc_snap = MagicMock()
            mock_doc_snap.exists = True
            mock_doc_snap.to_dict.return_value = {"name": "Plan Pro Nómina"}
            mock_firestore.collection.return_value.document.return_value.get.return_value = mock_doc_snap

            mock_profile.return_value = {
                "companyName": "Empresa SA",
                "monthlyPayment": 100.0,
                "billingDay": 5,
                "documentLimit": 100,
                "additionalDocumentCost": 0.20,
                "employeeLimit": 5,
                "additionalEmployeeCost": 4.0,
                "userLimit": 2,
                "additionalUserCost": 12.0,
                "branchLimit": 1,
                "additionalBranchCost": 30.0,
                "warehouseLimit": 1,
                "additionalWarehouseCost": 25.0,
                "boxLimit": 1,
                "additionalBoxCost": 15.0,
                "activeModules": ["nomina", "pos", "facturacion"],
                "configured": True,
            }

            # 120 docs emitidos (20 excedentes = $4.00)
            mock_stats.return_value = {
                "prod_current_cycle": 120,
                "total_invoices": 120,
                "sandbox_current_cycle": 10,
                "sandbox_total": 50,
                "current_cycle_start": "2026-11-01",
                "current_cycle_end": "2026-11-30",
            }

            # 8 empleados (3 excedentes = $12.00)
            mock_employees.return_value = [
                {"id": f"emp_{i}", "status": "activo", "name": f"Emp {i}"} for i in range(8)
            ]

            # 4 usuarios (2 excedentes = $24.00)
            mock_team.return_value = [
                {"uid": f"u_{i}", "name": f"User {i}"} for i in range(4)
            ]

            # 2 sucursales (1 excedente = $30.00)
            mock_branches.return_value = [
                {"id": "b1", "name": "B1"}, {"id": "b2", "name": "B2"}
            ]

            # 2 almacenes (1 excedente = $25.00)
            mock_wh.return_value = [
                {"id": "w1", "name": "W1"}, {"id": "w2", "name": "W2"}
            ]

            # 1 caja (0 excedentes)
            mock_boxes.return_value = [
                {"id": "c1", "name": "C1"}
            ]

            with client.session_transaction() as sess:
                sess['user'] = MOCK_OWNER
                sess['selected_company_id'] = 'comp_sub_123'
                sess['selected_owner_uid'] = 'owner_sub_123'
                sess['is_sandbox_mode'] = False
                sess['company_modules'] = MOCK_PLAN['modules']

            resp = client.get('/suscripcion')
            assert resp.status_code == 200
            html = resp.data.decode('utf-8')

            # Verificar que el HTML contiene las secciones y etiquetas de entidades
            assert "Mi Plan y Consumo" in html
            assert "Consumo de Documentos Fiscales" in html
            assert "Capacidad y Recursos del Plan" in html
            assert "Empleados en N\xc3\xb3mina" in html or "Empleados en Nómina" in html
            assert "Usuarios / Colaboradores" in html
            assert "Sucursales" in html
            assert "Almacenes" in html
            assert "Cajas POS" in html

            # Total base 100 + docs(4) + emp(12) + user(24) + branch(30) + wh(25) = 195.00
            assert "195" in html

    def test_costo_mensual_fijo_resolves_from_plan_when_company_has_zero(self):
        """Verifica que el Costo Mensual Fijo no sea 0 si la empresa tiene monthly_payment: 0 pero el plan tiene monthlyPrice: 80."""
        with patch.object(DatabaseService, 'get_company') as mock_get_company, \
             patch.object(DatabaseService, 'get_plan') as mock_get_plan:

            mock_get_company.return_value = {
                "owner_uid": "owner_sub_123",
                "company_name": "Empresa Test SA",
                "plan_id": "plan_profesional",
                "monthly_payment": 0,
                "monthlyPayment": 0,
            }
            mock_get_plan.return_value = {
                "id": "plan_profesional",
                "name": "Plan Profesional",
                "monthlyPrice": 80.0,
                "documentLimit": 500,
                "userLimit": 5,
            }

            profile = DatabaseService.get_company_profile("owner_sub_123", company_id="comp_sub_123")
            assert profile is not None
            assert profile["monthlyPayment"] == 80.0

    def test_costo_mensual_fijo_displayed_on_subscription_html(self, client):
        """Verifica que en /suscripcion se muestre el Costo Mensual Fijo del plan real."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_invoice_stats') as mock_stats, \
             patch.object(DatabaseService, 'get_payments', return_value=[]), \
             patch.object(DatabaseService, 'get_team_members', return_value=[]), \
             patch.object(DatabaseService, 'get_branches', return_value=[]), \
             patch.object(DatabaseService, 'get_warehouses', return_value=[]), \
             patch.object(DatabaseService, 'get_cash_registers', return_value=[]), \
             patch('app.services.hr_data_service.get_employees', return_value=[]), \
             patch('app.services.db_service.db_firestore') as mock_firestore:

            mock_doc_snap = MagicMock()
            mock_doc_snap.exists = True
            mock_doc_snap.to_dict.return_value = {
                "name": "Plan Profesional",
                "monthlyPrice": 80.0,
            }
            mock_firestore.collection.return_value.document.return_value.get.return_value = mock_doc_snap

            # Supongamos que el perfil venía con monthlyPayment: 0 pero plan_id existe
            mock_profile.return_value = {
                "companyName": "Empresa Test",
                "planId": "plan_profesional",
                "monthlyPayment": 0.0,
                "billingDay": 1,
                "documentLimit": 500,
                "additionalDocumentCost": 0.20,
                "employeeLimit": 10,
                "additionalEmployeeCost": 4.0,
                "userLimit": 5,
                "additionalUserCost": 10.0,
                "branchLimit": 2,
                "additionalBranchCost": 20.0,
                "warehouseLimit": 2,
                "additionalWarehouseCost": 20.0,
                "boxLimit": 1,
                "additionalBoxCost": 15.0,
                "activeModules": ["nomina"],
                "configured": True,
            }
            mock_stats.return_value = {
                "prod_current_cycle": 10,
                "total_invoices": 10,
                "current_cycle_start": "2026-11-01",
                "current_cycle_end": "2026-11-30",
            }

            with client.session_transaction() as sess:
                sess['user'] = MOCK_OWNER
                sess['selected_company_id'] = 'comp_sub_123'
                sess['selected_owner_uid'] = 'owner_sub_123'
                sess['is_sandbox_mode'] = False

            resp = client.get('/suscripcion')
            assert resp.status_code == 200
            html = resp.data.decode('utf-8')

            # Verificar que 'Costo Mensual Fijo:' no sea 0 sino 80.0
            assert "Costo Mensual Fijo:" in html
            assert "USD $ 80.0" in html or "USD $ 80" in html

