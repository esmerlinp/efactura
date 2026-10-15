"""Tests para el aislamiento de roles y permisos en entornos multiempresa.

Verifica que un usuario que es propietario ('owner') en su propia empresa no herede
el rol de 'owner' ni permisos completos cuando es invitado como colaborador
en otra empresa con permisos específicos.
"""

import pytest
from unittest.mock import MagicMock, patch
from app import create_app
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestMultiCompanyRoleIsolation:
    """Verifica que los roles y permisos se aíslen por empresa activa."""

    def test_get_team_members_returns_collaborator_role_not_global_owner(self):
        """Si un colaborador es owner en su perfil global, get_team_members debe retornar su rol en la empresa y NO 'owner'."""
        with patch('app.services.db_service.firebase_initialized', True), \
             patch.object(DatabaseService, '_company_team_coll') as mock_team_coll, \
             patch('app.services.db_service.db_firestore') as mock_db:

            mock_owner_uid = "owner_a"
            mock_comp_id = "comp_a"
            collab_uid = "user_b_is_owner_elsewhere"

            # Simular documento en companies/{comp_a}/team
            team_doc = MagicMock()
            team_doc.id = collab_uid
            team_doc.exists = True
            team_doc.to_dict.return_value = {
                "uid": collab_uid,
                "name": "Usuario B",
                "email": "user_b@otraempresa.do",
                "role": "personalizado",
                "permissions": {"canInvoice": True, "canHR": False, "canModifySettings": False},
                "status": "active",
                "createdAt": "2026-10-15T10:00:00",
            }

            team_coll_ref = MagicMock()
            team_coll_ref.get.return_value = [team_doc]
            mock_team_coll.return_value = team_coll_ref

            # Simular user_profile global de User B (donde es owner de su propia cuenta)
            user_b_profile_doc = MagicMock()
            user_b_profile_doc.exists = True
            user_b_profile_doc.to_dict.return_value = {
                "uid": collab_uid,
                "name": "Usuario B",
                "email": "user_b@otraempresa.do",
                "role": "owner",
                "ownerUID": collab_uid,
                "permissions": {"canInvoice": True, "canHR": True, "canModifySettings": True},
            }

            # Simular user_profile del propietario de comp_a
            owner_a_profile_doc = MagicMock()
            owner_a_profile_doc.exists = True
            owner_a_profile_doc.to_dict.return_value = {
                "uid": mock_owner_uid,
                "name": "Owner A",
                "email": "owner_a@empresa-a.do",
                "role": "owner",
                "ownerUID": mock_owner_uid,
            }

            def mock_get_user_profile_doc(doc_id):
                doc = MagicMock()
                if doc_id == collab_uid:
                    doc.get.return_value = user_b_profile_doc
                else:
                    doc.get.return_value = owner_a_profile_doc
                return doc

            mock_db.collection.return_value.document.side_effect = lambda uid: MagicMock(
                collection=lambda coll: MagicMock(
                    document=lambda d: mock_get_user_profile_doc(uid)
                )
            )

            team = DatabaseService.get_team_members(mock_owner_uid, company_id=mock_comp_id)

            # Debe haber 2 miembros: Owner A (insertado) y Usuario B
            collab_member = next((m for m in team if m["uid"] == collab_uid), None)
            assert collab_member is not None
            # El rol DEBE ser 'personalizado', NO 'owner'
            assert collab_member["role"] == "personalizado"
            assert collab_member["role"] != "owner"
            # Los permisos deben ser los asignados en comp_a (canHR=False)
            assert collab_member["permissions"]["canHR"] is False
            assert collab_member["permissions"]["canInvoice"] is True

    def test_get_team_members_auto_heals_corrupted_owner_role_for_collaborator(self):
        """Si un colaborador tenía 'role: owner' guardado en team, debe auto-sanarse a 'personalizado'."""
        with patch('app.services.db_service.firebase_initialized', True), \
             patch.object(DatabaseService, '_company_team_coll') as mock_team_coll, \
             patch.object(DatabaseService, 'update_membership') as mock_upd_mem, \
             patch('app.services.db_service.db_firestore') as mock_db:

            mock_owner_uid = "owner_a"
            mock_comp_id = "comp_a"
            collab_uid = "user_b_corrupted"

            team_doc = MagicMock()
            team_doc.id = collab_uid
            team_doc.exists = True
            team_doc.to_dict.return_value = {
                "uid": collab_uid,
                "name": "Usuario B",
                "email": "user_b@test.do",
                "role": "owner",  # Corrupto por el bug anterior
                "permissions": {"canInvoice": True, "canHR": False, "canExpenses": False},
                "status": "active",
            }

            team_coll_ref = MagicMock()
            team_coll_ref.get.return_value = [team_doc]
            team_doc_ref = MagicMock()
            team_coll_ref.document.return_value = team_doc_ref
            mock_team_coll.return_value = team_coll_ref

            emp_doc = MagicMock()
            emp_doc.exists = True
            emp_doc.to_dict.return_value = {
                "uid": collab_uid,
                "name": "Usuario B",
                "email": "user_b@test.do",
                "role": "owner",
            }
            mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value = emp_doc

            team = DatabaseService.get_team_members(mock_owner_uid, company_id=mock_comp_id)

            collab_member = next((m for m in team if m["uid"] == collab_uid), None)
            assert collab_member is not None
            # Debe haber corregido el rol a personalizado
            assert collab_member["role"] == "personalizado"
            assert collab_member["role"] != "owner"
            # Debe haber llamado update en Firestore para sanar el documento
            team_doc_ref.update.assert_called_with({"role": "personalizado"})

    def test_get_company_context_never_returns_owner_role_for_non_owner(self):
        """get_company_context debe asegurar que si el usuario no es el owner_uid de la empresa, su rol no sea 'owner'."""
        with patch.object(DatabaseService, 'get_company') as mock_company, \
             patch.object(DatabaseService, 'get_membership') as mock_mem:

            mock_company.return_value = {
                "id": "comp_a",
                "owner_uid": "owner_a",
                "company_name": "Empresa A",
                "status": "active",
            }
            # Simular membresía con role='owner' erróneo
            mock_mem.return_value = {
                "status": "active",
                "role": "owner",
                "permissions": {"canInvoice": True, "canHR": False},
            }

            ctx = DatabaseService.get_company_context("user_b", "comp_a")
            assert ctx is not None
            assert ctx["role"] != "owner"
            assert ctx["role"] == "personalizado"
            assert ctx["owner_uid"] == "owner_a"

    def test_session_role_and_permissions_scoped_to_active_company(self, client):
        """En before_request, session['user'] debe adoptar el rol y permisos de la compañía activa."""
        user_b_profile = {
            "uid": "user_b",
            "ownerUID": "user_b",
            "name": "Usuario B",
            "email": "b@test.do",
            "role": "owner",  # En su perfil global es owner
            "permissions": {"canInvoice": True, "canHR": True, "canModifySettings": True},
        }

        comp_a_context = {
            "company_id": "comp_a",
            "owner_uid": "owner_a",
            "company_name": "Empresa A",
            "role": "personalizado",
            "permissions": {"canInvoice": True, "canHR": False, "canModifySettings": False},
        }

        with patch.object(DatabaseService, 'get_user_profile', return_value=user_b_profile), \
             patch.object(DatabaseService, 'get_company_context', return_value=comp_a_context), \
             patch.object(DatabaseService, 'get_company', return_value={'id': 'comp_a', 'owner_uid': 'owner_a', 'configured': True, 'plan_id': 'plan_test'}), \
             patch.object(DatabaseService, 'get_plan', return_value={'id': 'plan_test', 'name': 'Plan Test', 'modules': {}}), \
             patch.object(DatabaseService, 'get_branches', return_value=[]), \
             patch.object(DatabaseService, 'get_projects', return_value=[]), \
             patch.object(DatabaseService, 'get_membership', return_value={'status': 'active'}), \
             patch.object(DatabaseService, 'get_associated_companies', return_value=[{'id': 'comp_a'}]):

            with client.session_transaction() as sess:
                sess['user'] = user_b_profile
                sess['selected_company_id'] = 'comp_a'
                sess['selected_owner_uid'] = 'owner_a'

            # Al hacer una petición, before_request sincroniza session['user'] con el contexto de comp_a
            client.get('/dashboard')

            with client.session_transaction() as sess:
                user_in_session = sess['user']
                assert user_in_session['role'] == 'personalizado'
                assert user_in_session['role'] != 'owner'
                assert user_in_session['permissions']['canHR'] is False
                assert user_in_session['permissions']['canInvoice'] is True
                assert user_in_session['ownerUID'] == 'owner_a'

    def test_update_employee_permissions_does_not_overwrite_independent_owner_profile(self):
        """update_employee_permissions para una empresa no debe sobrescribir el user_profile de un dueño independiente."""
        with patch('app.services.db_service.firebase_initialized', True), \
             patch('app.services.db_service.db_firestore') as mock_db, \
             patch.object(DatabaseService, 'update_membership') as mock_upd_mem, \
             patch.object(DatabaseService, '_company_team_coll') as mock_team_coll, \
             patch('app.services.db_service.cache'):

            collab_uid = "owner_of_company_b"
            prof_doc = MagicMock()
            prof_doc.exists = True
            prof_doc.to_dict.return_value = {
                "uid": collab_uid,
                "role": "owner",
                "ownerUID": collab_uid,  # Es dueño de su propia cuenta
                "canManageOwnCompany": True,
            }

            user_doc_ref = MagicMock()
            user_doc_ref.collection.return_value.document.return_value.get.return_value = prof_doc
            mock_db.collection.return_value.document.return_value = user_doc_ref

            team_ref = MagicMock()
            mock_team_coll.return_value = team_ref

            mock_upd_mem.return_value = True

            success = DatabaseService.update_employee_permissions(
                employee_uid=collab_uid,
                permissions={"canInvoice": True, "canHR": False},
                role="vendedor",
                company_id="comp_a"
            )

            assert success is True
            # user_profile NO debe haber sido actualizado con role='vendedor'
            user_doc_ref.collection.return_value.document.return_value.update.assert_not_called()
            # La membresía en comp_a SÍ debe haberse actualizado
            mock_upd_mem.assert_called_once_with(collab_uid, "comp_a", {
                "permissions": {"canInvoice": True, "canExpenses": False, "canClients": True,
                                "canModifySettings": False, "canManageInventory": False, "canManagePOS": True,
                                "canViewDashboard": True, "canManageCXC": False, "canManageCXP": False,
                                "canManageContracts": False, "canManageCommissions": True, "canViewBI": False,
                                "canViewAuditLog": False, "canAccounting": False, "isPosSupervisor": False,
                                "canViewSubscription": False, "canToggleSandbox": False, "canManageNotes": False,
                                "canManageSuppliers": False, "canManagePurchaseCXP": False, "canUseChatbot": False,
                                "canManageTools": False, "canHR": False, "canVoidInvoice": False,
                                "canCreateSupplier": False, "canApprovePayments": False, "canApprovePayroll": False,
                                "canApproveExpenses": False, "canSupervisePOS": False, "canAssignApprovers": False},
                "role": "vendedor",
            })
            # El equipo de comp_a SÍ debe haberse actualizado
            team_ref.document.assert_called_once_with(collab_uid)
            team_ref.document.return_value.set.assert_called_once()
