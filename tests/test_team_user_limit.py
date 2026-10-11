"""Tests para la validación de límites de usuarios de plan y roles predefinidos."""

import pytest
from unittest.mock import patch
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


class TestCompanyProfileUserLimit:
    """Verifica que DatabaseService.get_company_profile resuelva userLimit correctamente."""

    def test_get_company_profile_resolves_limit_from_plan(self):
        """Si la empresa tiene planId pero no userLimit en su doc, debe obtenerlo del plan."""
        with patch.object(DatabaseService, 'get_company') as mock_get_company, \
             patch.object(DatabaseService, 'get_plan') as mock_get_plan:
            mock_get_company.return_value = {
                "owner_uid": "owner_123",
                "company_name": "Empresa Test",
                "plan_id": "plan_enterprise_100",
                "plan_version": 1,
            }
            mock_get_plan.return_value = {
                "id": "plan_enterprise_100",
                "name": "Plan Enterprise 100",
                "userLimit": 100,
                "documentLimit": 5000,
            }

            profile = DatabaseService.get_company_profile("owner_123", company_id="comp_123")
            assert profile is not None
            assert profile["userLimit"] == 100
            assert profile["documentLimit"] == 5000
            assert profile["planId"] == "plan_enterprise_100"

    def test_get_company_profile_preserves_explicit_user_limit(self):
        """Si la empresa tiene un userLimit explícito en su doc, debe respetarse."""
        with patch.object(DatabaseService, 'get_company') as mock_get_company, \
             patch.object(DatabaseService, 'get_plan') as mock_get_plan:
            mock_get_company.return_value = {
                "owner_uid": "owner_123",
                "company_name": "Empresa Test",
                "plan_id": "plan_basic",
                "userLimit": 15,
            }
            mock_get_plan.return_value = {
                "id": "plan_basic",
                "userLimit": 5,
            }

            profile = DatabaseService.get_company_profile("owner_123", company_id="comp_123")
            assert profile is not None
            assert profile["userLimit"] == 15


class TestAddTeamMemberLimits:
    """Verifica que el endpoint add_team_member respete los límites reales del plan."""

    MOCK_USER_PROFILE = {
        "uid": "owner_123",
        "ownerUID": "owner_123",
        "name": "Owner Test",
        "email": "owner@test.com",
        "role": "owner",
        "status": "active",
        "disabled": False,
        "permissions": {"canModifySettings": True},
    }

    @pytest.fixture(autouse=True)
    def common_mocks(self):
        with patch.object(DatabaseService, 'get_user_profile', return_value=self.MOCK_USER_PROFILE), \
             patch.object(DatabaseService, 'get_associated_companies', return_value=[{'ownerUID': 'owner_123', 'companyName': 'Empresa Test', 'role': 'owner'}]), \
             patch.object(DatabaseService, 'get_company', return_value={'id': 'comp_123', 'owner_uid': 'owner_123', 'company_name': 'Empresa Test', 'plan_id': 'plan_test', 'status': 'active', 'configured': True}), \
             patch.object(DatabaseService, 'get_company_context', return_value={'permissions': {'canModifySettings': True}, 'company_name': 'Empresa Test'}), \
             patch.object(DatabaseService, 'get_branches', return_value=[]), \
             patch.object(DatabaseService, 'get_projects', return_value=[]), \
             patch.object(DatabaseService, 'get_membership', return_value={'status': 'active'}), \
             patch.object(DatabaseService, 'get_plan', return_value={'id': 'plan_test', 'name': 'Plan Test', 'modules': {'e_cf': {'enabled': True}}}):
            yield

    def test_add_member_allowed_with_100_user_plan(self, client):
        """Un plan con 100 usuarios y 1 miembro actual (propietario) debe permitir crear colaborador."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_team_members') as mock_team, \
             patch.object(DatabaseService, 'register_user') as mock_register, \
             patch.object(DatabaseService, 'update_employee_permissions') as mock_update_perms:

            mock_profile.return_value = {
                "companyName": "Empresa 100",
                "planId": "plan_100",
                "userLimit": 100,
                "configured": True,
            }
            # Actualmente 1 usuario en el equipo (propietario)
            mock_team.return_value = [
                {"uid": "owner_123", "role": "owner", "name": "Owner"}
            ]
            mock_register.return_value = {"uid": "new_emp_1"}

            with client.session_transaction() as sess:
                sess['user'] = self.MOCK_USER_PROFILE
                sess['selected_company_id'] = 'comp_123'
                sess['selected_owner_uid'] = 'owner_123'

            resp = client.post('/settings/team/new', data={
                'name': 'Juan Pérez',
                'email': 'juan@empresa.do',
                'password': 'password123',
                'role': 'vendedor',
                'canInvoice': 'on',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_register.assert_called_once()
            mock_update_perms.assert_called_once()

    def test_add_member_allowed_with_2_user_plan_when_currently_1(self, client):
        """Un plan con 2 usuarios permitidos y 1 actual (propietario) debe permitir crear el 2do usuario."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_team_members') as mock_team, \
             patch.object(DatabaseService, 'register_user') as mock_register, \
             patch.object(DatabaseService, 'update_employee_permissions') as mock_update_perms:

            mock_profile.return_value = {
                "companyName": "Empresa 2",
                "planId": "plan_test",
                "userLimit": 2,
                "configured": True,
            }
            mock_team.return_value = [
                {"uid": "owner_123", "role": "owner", "name": "Owner"}
            ]
            mock_register.return_value = {"uid": "new_emp_1"}

            with client.session_transaction() as sess:
                sess['user'] = self.MOCK_USER_PROFILE
                sess['selected_company_id'] = 'comp_123'
                sess['selected_owner_uid'] = 'owner_123'

            resp = client.post('/settings/team/new', data={
                'name': 'Segundo Usuario',
                'email': 'user2@empresa.do',
                'password': 'password123',
                'role': 'vendedor',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_register.assert_called_once()

    def test_add_member_blocked_when_limit_reached(self, client):
        """Un plan con 2 usuarios y 2 miembros actuales (propietario + 1 colaborador) debe bloquear la creación."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_team_members') as mock_team, \
             patch.object(DatabaseService, 'register_user') as mock_register:

            mock_profile.return_value = {
                "companyName": "Empresa 2",
                "planId": "plan_test",
                "userLimit": 2,
                "configured": True,
            }
            mock_team.return_value = [
                {"uid": "owner_123", "role": "owner", "name": "Owner"},
                {"uid": "emp_1", "role": "employee", "name": "Empleado 1"},
            ]

            with client.session_transaction() as sess:
                sess['user'] = self.MOCK_USER_PROFILE
                sess['selected_company_id'] = 'comp_123'
                sess['selected_owner_uid'] = 'owner_123'

            resp = client.post('/settings/team/new', data={
                'name': 'Tercer Usuario',
                'email': 'user3@empresa.do',
                'password': 'password123',
                'role': 'vendedor',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_register.assert_not_called()
            assert b"L\xc3\xadmite de usuarios alcanzado (2 usuarios en tu plan)" in resp.data

    def test_add_member_allowed_when_plan_is_unlimited(self, client):
        """Un plan ilimitado (userLimit=0) no debe bloquear la adición de colaboradores."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_team_members') as mock_team, \
             patch.object(DatabaseService, 'register_user') as mock_register, \
             patch.object(DatabaseService, 'update_employee_permissions') as mock_update_perms:

            mock_profile.return_value = {
                "companyName": "Empresa Ilimitada",
                "planId": "plan_test",
                "userLimit": 0,
                "configured": True,
            }
            mock_team.return_value = [
                {"uid": "owner_123", "role": "owner", "name": "Owner"},
                {"uid": "emp_1", "role": "employee", "name": "Empleado 1"},
                {"uid": "emp_2", "role": "employee", "name": "Empleado 2"},
            ]
            mock_register.return_value = {"uid": "new_emp_3"}

            with client.session_transaction() as sess:
                sess['user'] = self.MOCK_USER_PROFILE
                sess['selected_company_id'] = 'comp_123'
                sess['selected_owner_uid'] = 'owner_123'

            resp = client.post('/settings/team/new', data={
                'name': 'Cuarto Usuario',
                'email': 'user4@empresa.do',
                'password': 'password123',
                'role': 'vendedor',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_register.assert_called_once()


class TestTeamRegistrationCompanyAssignment:
    """Verifica que el registro de nuevos usuarios asigne la compañía correcta en multiempresa."""

    MOCK_USER_PROFILE = {
        "uid": "owner_123",
        "ownerUID": "owner_123",
        "name": "Owner Multiempresa",
        "email": "owner@test.com",
        "role": "owner",
        "status": "active",
        "disabled": False,
        "permissions": {"canModifySettings": True},
    }

    @pytest.fixture(autouse=True)
    def common_mocks(self):
        with patch.object(DatabaseService, 'get_user_profile', return_value=self.MOCK_USER_PROFILE), \
             patch.object(DatabaseService, 'get_associated_companies', return_value=[
                 {'ownerUID': 'owner_123', 'id': 'comp_A', 'companyName': 'Empresa A', 'role': 'owner'},
                 {'ownerUID': 'owner_123', 'id': 'comp_B', 'companyName': 'Empresa B', 'role': 'owner'},
             ]), \
             patch.object(DatabaseService, 'get_company', return_value={'id': 'comp_B', 'owner_uid': 'owner_123', 'company_name': 'Empresa B', 'plan_id': 'plan_test', 'status': 'active', 'configured': True}), \
             patch.object(DatabaseService, 'get_company_context', return_value={'permissions': {'canModifySettings': True}, 'company_name': 'Empresa B'}), \
             patch.object(DatabaseService, 'get_branches', return_value=[]), \
             patch.object(DatabaseService, 'get_projects', return_value=[]), \
             patch.object(DatabaseService, 'get_membership', return_value={'status': 'active'}), \
             patch.object(DatabaseService, 'get_plan', return_value={'id': 'plan_test', 'name': 'Plan Test', 'userLimit': 10}):
            yield

    def test_add_team_member_passes_selected_company_id_to_register_user(self, client):
        """Verifica que /settings/team/new pase el company_id activo de la sesión a register_user."""
        with patch.object(DatabaseService, 'get_company_profile') as mock_profile, \
             patch.object(DatabaseService, 'get_team_members') as mock_team, \
             patch.object(DatabaseService, 'register_user') as mock_register, \
             patch.object(DatabaseService, 'update_employee_permissions') as mock_update_perms:

            mock_profile.return_value = {
                "companyName": "Empresa B",
                "planId": "plan_test",
                "userLimit": 10,
                "configured": True,
            }
            mock_team.return_value = [
                {"uid": "owner_123", "role": "owner", "name": "Owner"}
            ]
            mock_register.return_value = {"uid": "new_collab_uid"}

            with client.session_transaction() as sess:
                sess['user'] = self.MOCK_USER_PROFILE
                sess['selected_company_id'] = 'comp_B'
                sess['selected_owner_uid'] = 'owner_123'

            resp = client.post('/settings/team/new', data={
                'name': 'Carlos Santana',
                'email': 'carlos@empresa-b.do',
                'password': 'password123',
                'role': 'cajero',
            }, follow_redirects=True)

            assert resp.status_code == 200
            mock_register.assert_called_once_with(
                email='carlos@empresa-b.do',
                password='password123',
                name='Carlos Santana',
                role='employee',
                owner_uid='owner_123',
                company_id='comp_B'
            )
            mock_update_perms.assert_called_once()
            args, kwargs = mock_update_perms.call_args
            assert kwargs.get('company_id') == 'comp_B'

    def test_register_user_creates_membership_for_target_company_not_first_owner_company(self):
        """register_user con company_id='comp_B' debe vincular a comp_B y no a comp_A."""
        with patch('app.services.db_service.firebase_initialized', True), \
             patch('app.services.db_service.auth.get_user_by_email') as mock_auth_lookup, \
             patch('app.services.db_service.auth.create_user') as mock_create_user, \
             patch('app.services.db_service.db_firestore') as mock_db, \
             patch.object(DatabaseService, 'get_companies_by_owner') as mock_owner_companies, \
             patch.object(DatabaseService, 'create_membership') as mock_create_mem, \
             patch.object(DatabaseService, 'get_membership', return_value=None), \
             patch.object(DatabaseService, '_company_team_coll') as mock_team_coll, \
             patch('app.services.db_service.cache'):

            from unittest.mock import MagicMock

            mock_user_record = MagicMock()
            mock_user_record.uid = "collab_uid_999"
            mock_auth_lookup.return_value = mock_user_record

            # Simular que el owner tiene comp_A primero y luego comp_B
            mock_owner_companies.return_value = [
                {"id": "comp_A", "name": "Empresa A"},
                {"id": "comp_B", "name": "Empresa B"},
            ]

            # Simular Firestore doc_ref para user_profile (nuevo)
            mock_doc_snap = MagicMock()
            mock_doc_snap.exists = False
            mock_doc_ref = MagicMock()
            mock_doc_ref.get.return_value = mock_doc_snap
            mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref

            mock_team_ref = MagicMock()
            mock_team_coll.return_value = mock_team_ref

            profile = DatabaseService.register_user(
                email="collab@empresa-b.do",
                password="password123",
                name="Colaborador B",
                role="employee",
                owner_uid="owner_123",
                company_id="comp_B"
            )

            # Verificar que la membresía se crea para comp_B (NO comp_A)
            mock_create_mem.assert_called_once_with(
                uid="collab_uid_999",
                company_id="comp_B",
                role="employee",
                permissions=profile.get("permissions", {}),
                invited_by="owner_123"
            )

            # Verificar que el perfil tiene default_company_id = comp_B
            assert profile["default_company_id"] == "comp_B"

            # Verificar que _company_team_coll se llamó con comp_B
            mock_team_coll.assert_called_once_with("owner_123", company_id="comp_B")
            mock_team_ref.document.assert_called_once_with("collab_uid_999")

