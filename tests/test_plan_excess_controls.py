"""Pruebas exhaustivas para el control granular de recursos adicionales en suscripción.
Valida:
1. is_resource_excess_blocked (por defecto desbloqueado, respeta booleanos y fallback).
2. Bloqueo vs Desbloqueo en los 6 puntos de creación:
   - Empleados (RRHH)
   - Usuarios / Colaboradores
   - Sucursales
   - Almacenes
   - Cajas POS
   - Documentos e-CF (check_document_limit_exceeded)
3. Endpoint AJAX POST /suscripcion/toggle-recurso-adicional
"""

import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from app.services.db_service import DatabaseService
from app.utils.plan_limits import is_resource_excess_blocked, RESOURCE_KEYS, RESOURCE_LABELS


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
    "uid": "owner_excess_123",
    "ownerUID": "owner_excess_123",
    "name": "Admin Suscripción",
    "email": "admin@empresa.do",
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
        "canManageUsers": True,
    },
}

MOCK_PLAN = {
    "id": "plan_test",
    "name": "Plan Test",
    "plan_version": 1,
    "modules": {
        "e_cf": {"enabled": True},
        "nomina": {"enabled": True},
        "pos": {"enabled": True},
        "inventario": {"enabled": True},
    },
}


class TestIsResourceExcessBlockedHelper:
    """Verifica la función utilitaria is_resource_excess_blocked."""

    def test_default_unblocked_when_no_controls(self):
        profile = {"companyName": "Empresa Test"}
        for res in RESOURCE_KEYS:
            assert is_resource_excess_blocked(profile, res) is False

    def test_unblocked_when_explicitly_false(self):
        profile = {
            "excess_controls": {"employees": False, "users": False, "boxes": False}
        }
        assert is_resource_excess_blocked(profile, "employees") is False
        assert is_resource_excess_blocked(profile, "users") is False
        assert is_resource_excess_blocked(profile, "boxes") is False
        assert is_resource_excess_blocked(profile, "warehouses") is False

    def test_blocked_when_explicitly_true(self):
        profile = {
            "excess_controls": {
                "employees": True,
                "users": True,
                "branches": True,
                "warehouses": True,
                "boxes": True,
                "documents": True,
            }
        }
        for res in RESOURCE_KEYS:
            assert is_resource_excess_blocked(profile, res) is True

    def test_respects_camel_case_excessControls(self):
        profile = {
            "excessControls": {"employees": True, "users": False}
        }
        assert is_resource_excess_blocked(profile, "employees") is True
        assert is_resource_excess_blocked(profile, "users") is False

    def test_respects_flat_block_excess_field(self):
        profile = {
            "block_excess_warehouses": True,
            "block_excess_branches": False,
        }
        assert is_resource_excess_blocked(profile, "warehouses") is True
        assert is_resource_excess_blocked(profile, "branches") is False

    def test_handles_string_booleans(self):
        profile = {
            "excess_controls": {"employees": "true", "users": "false", "boxes": "1"}
        }
        assert is_resource_excess_blocked(profile, "employees") is True
        assert is_resource_excess_blocked(profile, "users") is False
        assert is_resource_excess_blocked(profile, "boxes") is True


class TestCreationBlockingBehavior:
    """Valida que cada una de las 6 entidades respete el bloqueo cuando está activado."""

    @pytest.fixture(autouse=True)
    def setup_session(self):
        with patch.object(DatabaseService, 'get_user_profile', return_value=MOCK_OWNER), \
             patch.object(DatabaseService, 'get_associated_companies', return_value=[{'ownerUID': 'owner_excess_123', 'id': 'comp_test_123', 'companyName': 'Empresa SA', 'role': 'owner'}]), \
             patch.object(DatabaseService, 'get_company', return_value={'id': 'comp_test_123', 'owner_uid': 'owner_excess_123', 'status': 'active', 'configured': True, 'plan_id': 'plan_test'}), \
             patch.object(DatabaseService, 'get_company_context', return_value={'role': 'owner', 'owner_uid': 'owner_excess_123', 'permissions': MOCK_OWNER['permissions']}), \
             patch.object(DatabaseService, 'get_membership', return_value={'status': 'active'}), \
             patch.object(DatabaseService, 'get_branches', return_value=[]), \
             patch.object(DatabaseService, 'get_plan', return_value=MOCK_PLAN):
            yield

    def _login_client(self, client):
        with client.session_transaction() as sess:
            sess['user'] = MOCK_OWNER
            sess['selected_company_id'] = 'comp_test_123'
            sess['selected_owner_uid'] = 'owner_excess_123'
            sess['is_sandbox_mode'] = False
            sess['company_plan_id'] = 'plan_test'
            sess['company_profile_pos_enabled'] = True
            sess['company_modules'] = MOCK_PLAN['modules']

    def test_employees_blocked_when_excess_blocked(self, client):
        """Crear empleado cuando excess_controls['employees'] = True debe ser bloqueado."""
        self._login_client(client)
        from app.services import hr_data_service as hr

        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(hr, 'get_employees') as mock_employees, \
             patch.object(hr, 'save_employee') as mock_save:

            mock_profile.return_value = {
                "planId": "plan_test",
                "employeeLimit": 2,
                "excess_controls": {"employees": True},
            }
            # Ya existen 2 empleados activos
            mock_employees.return_value = [
                {"id": "e1", "status": "activo"},
                {"id": "e2", "status": "activo"},
            ]

            resp = client.post('/rrhh/employees/new', data={
                'firstName': 'Juan',
                'firstLastName': 'Perez',
                'idType': 'cedula',
                'idNumber': '40200000001',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_save.assert_not_called()
            assert "bloqueada la creaci\xc3\xb3n de empleados adicionales".encode('utf-8') in resp.data or b"bloqueada" in resp.data

    def test_employees_allowed_when_excess_unblocked(self, client):
        """Crear empleado cuando excess_controls['employees'] = False debe permitirse aunque supere el límite."""
        self._login_client(client)
        from app.services import hr_data_service as hr

        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(hr, 'get_employees') as mock_employees, \
             patch.object(hr, 'save_employee') as mock_save:

            mock_profile.return_value = {
                "planId": "plan_test",
                "employeeLimit": 2,
                "additionalEmployeeCost": 5.0,
                "excess_controls": {"employees": False},
            }
            mock_employees.return_value = [
                {"id": "e1", "status": "activo"},
                {"id": "e2", "status": "activo"},
            ]

            resp = client.post('/rrhh/employees/new', data={
                'firstName': 'Juan',
                'firstLastName': 'Perez',
                'idType': 'cedula',
                'idNumber': '40200000001',
            }, follow_redirects=False)

            assert resp.status_code == 302
            mock_save.assert_called_once()

    def test_users_blocked_when_excess_blocked(self, client):
        """Crear usuario cuando excess_controls['users'] = True debe ser bloqueado."""
        self._login_client(client)

        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_team_members') as mock_team, \
             patch.object(DatabaseService, 'register_user') as mock_reg:

            mock_profile.return_value = {
                "planId": "plan_test",
                "userLimit": 2,
                "excess_controls": {"users": True},
            }
            mock_team.return_value = [{"uid": "u1"}, {"uid": "u2"}]

            resp = client.post('/settings/team/new', data={
                'name': 'Nuevo Colaborador',
                'email': 'nuevo@empresa.do',
                'password': 'Password123!',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_reg.assert_not_called()
            assert "bloqueada la creaci\xc3\xb3n de usuarios adicionales".encode('utf-8') in resp.data or b"bloqueada" in resp.data

    def test_branches_blocked_when_excess_blocked(self, client):
        """Crear sucursal cuando excess_controls['branches'] = True debe ser bloqueada."""
        self._login_client(client)

        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_branches') as mock_branches, \
             patch.object(DatabaseService, 'save_branch') as mock_save:

            mock_profile.return_value = {
                "planId": "plan_test",
                "branchLimit": 1,
                "excess_controls": {"branches": True},
            }
            mock_branches.return_value = [{"id": "b1", "name": "Principal"}]

            resp = client.post('/settings/branches/save', data={
                'name': 'Sucursal Nueva',
                'code': 'SUC-02',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_save.assert_not_called()
            assert "bloqueada la creaci\xc3\xb3n de sucursales adicionales".encode('utf-8') in resp.data or b"bloqueada" in resp.data

    def test_warehouses_blocked_when_excess_blocked(self, client):
        """Crear almacén cuando excess_controls['warehouses'] = True debe ser bloqueado."""
        self._login_client(client)

        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_warehouses') as mock_wh, \
             patch.object(DatabaseService, 'save_warehouse') as mock_save:

            mock_profile.return_value = {
                "planId": "plan_test",
                "warehouseLimit": 1,
                "excess_controls": {"warehouses": True},
            }
            mock_wh.return_value = [{"id": "w1", "name": "Almacén Central"}]

            resp = client.post('/inventory/warehouses/new', data={
                'name': 'Almacén Extra',
                'code': 'ALM-99',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_save.assert_not_called()
            assert "bloqueada la creaci\xc3\xb3n de almacenes adicionales".encode('utf-8') in resp.data or b"bloqueada" in resp.data

    def test_boxes_blocked_when_excess_blocked(self, client):
        """Crear caja registradora cuando excess_controls['boxes'] = True debe ser bloqueada."""
        self._login_client(client)

        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_cash_registers') as mock_boxes, \
             patch.object(DatabaseService, 'save_cash_register') as mock_save:

            mock_profile.return_value = {
                "planId": "plan_test",
                "boxLimit": 1,
                "excess_controls": {"boxes": True},
            }
            mock_boxes.return_value = [
                {"id": "box-1", "name": "Caja 1", "createdAt": "2026-11-01T12:00:00Z"}
            ]

            resp = client.post('/pos/register/new', data={
                'name': 'Caja 2',
                'warehouseId': 'w1',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_save.assert_not_called()
            assert "bloqueada la creaci\xc3\xb3n de cajas adicionales".encode('utf-8') in resp.data or b"bloqueada" in resp.data

    def test_documents_blocked_in_check_document_limit_exceeded(self):
        """Validar que check_document_limit_exceeded bloquee si excess_controls['documents'] = True."""
        from app.web.invoices import check_document_limit_exceeded

        profile = {
            "documentLimit": 100,
            "additionalDocumentCost": 0.25,
            "billingDay": 1,
            "excess_controls": {"documents": True},
        }

        with patch.object(DatabaseService, 'get_company_profile', return_value=profile), \
             patch.object(DatabaseService, 'get_invoice_stats', return_value={'prod_current_cycle': 100}):

            exceeded, msg = check_document_limit_exceeded("owner_excess_123", company_id="comp_test_123", sandbox=False)
            assert exceeded is True
            assert "bloqueada la emisión de comprobantes adicionales" in msg

    def test_documents_allowed_with_warning_when_unblocked(self):
        """Validar que check_document_limit_exceeded no bloquee si excess_controls['documents'] = False."""
        from app.web.invoices import check_document_limit_exceeded

        profile = {
            "documentLimit": 100,
            "additionalDocumentCost": 0.25,
            "billingDay": 1,
            "excess_controls": {"documents": False},
        }

        with patch.object(DatabaseService, 'get_company_profile', return_value=profile), \
             patch.object(DatabaseService, 'get_invoice_stats', return_value={'prod_current_cycle': 100}):

            exceeded, msg = check_document_limit_exceeded("owner_excess_123", company_id="comp_test_123", sandbox=False)
            assert exceeded is False
            assert "costo adicional de USD $ 0.25" in msg


class TestToggleResourceExcessEndpoint:
    """Prueba el endpoint AJAX POST /suscripcion/toggle-recurso-adicional."""

    @pytest.fixture(autouse=True)
    def setup_session(self):
        with patch.object(DatabaseService, 'get_user_profile', return_value=MOCK_OWNER), \
             patch.object(DatabaseService, 'get_associated_companies', return_value=[{'ownerUID': 'owner_excess_123', 'id': 'comp_test_123', 'companyName': 'Empresa SA', 'role': 'owner'}]), \
             patch.object(DatabaseService, 'get_company', return_value={'id': 'comp_test_123', 'owner_uid': 'owner_excess_123', 'status': 'active', 'configured': True, 'plan_id': 'plan_test'}), \
             patch.object(DatabaseService, 'get_company_context', return_value={'role': 'owner', 'owner_uid': 'owner_excess_123', 'permissions': MOCK_OWNER['permissions']}), \
             patch.object(DatabaseService, 'get_membership', return_value={'status': 'active'}), \
             patch.object(DatabaseService, 'get_branches', return_value=[]), \
             patch.object(DatabaseService, 'get_company_profile', return_value={'planId': 'plan_test', 'excess_controls': {}}), \
             patch.object(DatabaseService, 'get_plan', return_value=MOCK_PLAN):
            yield

    def test_unauthenticated_rejected(self, client):
        resp = client.post('/suscripcion/toggle-recurso-adicional', json={
            'resource': 'employees',
            'blocked': True
        })
        assert resp.status_code in (302, 401, 403)

    def test_invalid_resource_rejected(self, client):
        with client.session_transaction() as sess:
            sess['user'] = MOCK_OWNER
            sess['selected_company_id'] = 'comp_test_123'
            sess['selected_owner_uid'] = 'owner_excess_123'
            sess['company_plan_id'] = 'plan_test'
            sess['company_modules'] = MOCK_PLAN['modules']

        resp = client.post('/suscripcion/toggle-recurso-adicional', json={
            'resource': 'invalid_resource_name',
            'blocked': True
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert "inválido" in data['error'].lower()

    def test_successful_toggle_to_blocked_and_unblocked(self, client):
        from app.services.db_service import db_firestore, _cached_company_profile
        from app.cache import cache

        mock_company_doc = MagicMock()
        mock_user_doc = MagicMock()

        with patch.object(db_firestore, 'collection') as mock_collection, \
             patch.object(cache, 'delete_memoized') as mock_cache_delete:

            def get_collection(coll_name):
                col = MagicMock()
                if coll_name == 'companies':
                    col.document.return_value = mock_company_doc
                elif coll_name == 'users':
                    user_doc = MagicMock()
                    subcol = MagicMock()
                    subcol.document.return_value = mock_user_doc
                    user_doc.collection.return_value = subcol
                    col.document.return_value = user_doc
                return col

            mock_collection.side_effect = get_collection

            with client.session_transaction() as sess:
                sess['user'] = MOCK_OWNER
                sess['selected_company_id'] = 'comp_test_123'
                sess['selected_owner_uid'] = 'owner_excess_123'
                sess['company_plan_id'] = 'plan_test'
                sess['company_modules'] = MOCK_PLAN['modules']

            # 1. Bloquear empleados
            resp1 = client.post('/suscripcion/toggle-recurso-adicional', json={
                'resource': 'employees',
                'blocked': True
            })
            assert resp1.status_code == 200
            data1 = resp1.get_json()
            assert data1['success'] is True
            assert data1['blocked'] is True
            assert data1['resource'] == 'employees'
            assert "bloqueada" in data1['message']

            # Verifica que Firestore recibió los datos correctos
            mock_company_doc.set.assert_called_with({
                'excess_controls': {'employees': True},
                'block_excess_employees': True
            }, merge=True)
            mock_cache_delete.assert_called_with(_cached_company_profile, 'owner_excess_123')

            # 2. Desbloquear empleados
            resp2 = client.post('/suscripcion/toggle-recurso-adicional', json={
                'resource': 'employees',
                'blocked': False
            })
            assert resp2.status_code == 200
            data2 = resp2.get_json()
            assert data2['success'] is True
            assert data2['blocked'] is False
            assert "desbloqueada" in data2['message']
