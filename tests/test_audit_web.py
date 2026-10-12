from unittest.mock import patch, MagicMock
import pytest


def _setup_audit_session(client, role='owner'):
    user_dict = {
        'uid': 'test_owner_uid',
        'ownerUID': 'test_owner_uid',
        'role': role,
        'email': 'admin@test.com',
        'name': 'Admin',
        'status': 'active',
        'default_company_id': 'test_comp_1',
        'permissions': {'canViewAuditLog': True}
    }
    with client.session_transaction() as sess:
        sess.clear()
        sess['user'] = dict(user_dict)
        sess['selected_company_id'] = 'test_comp_1'
        sess['selected_owner_uid'] = 'test_owner_uid'
        sess['company_country'] = 'DO'
        sess['company_plan_id'] = 'plan_test'
        sess['company_plan_version'] = 1
        sess['company_modules'] = {'auditoria': {'enabled': True}}
    return user_dict


COMPANY_DOC = {
    'id': 'test_comp_1',
    'status': 'Activo',
    'planId': 'plan_test',
    'plan_id': 'plan_test',
    'plan_version': 1,
    'owner_uid': 'test_owner_uid',
    'country': 'DO',
    'configured': True,
    'pos_enabled': False,
    'posEnabled': False,
    'production_enabled': True,
    'sandbox_enabled': True,
    'sandbox_indefinite': True,
}


def test_audit_detail_resolves_company_id(client):
    """Verifica que audit_detail no arroja NameError por _resolve_company_id."""
    user_dict = _setup_audit_session(client)

    sample_log = {
        "id": "log-123",
        "action": "UPDATE",
        "module": "Facturas",
        "entityId": "INV-001",
        "entityLabel": "Factura #1",
        "performedBy": "Admin",
        "performedByEmail": "admin@example.com",
        "timestamp": "2026-10-12T08:00:00Z",
        "before": {"status": "draft"},
        "after": {"status": "signed"},
        "isSandbox": True,
        "ipAddress": "127.0.0.1",
        "userAgent": "Mozilla/5.0",
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_dict), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=COMPANY_DOC), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=COMPANY_DOC), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'role': 'owner', 'permissions': {'canViewAuditLog': True}, 'company': COMPANY_DOC}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'auditoria': {'enabled': True}}}), \
         patch('app.services.audit_service.AuditService.get_log_detail', return_value=sample_log) as mock_get_detail, \
         patch('app.web.audit._resolve_company_id', return_value='test_comp_1') as mock_resolve:

        resp = client.get('/audit/log-123')
        assert resp.status_code == 200
        assert b"log-123" in resp.data
        mock_resolve.assert_called_once_with('test_owner_uid')
        mock_get_detail.assert_called_once_with('test_owner_uid', 'log-123', company_id='test_comp_1')


def test_audit_detail_not_found_redirects(client):
    """Verifica redirección y flash si el log no existe."""
    user_dict = _setup_audit_session(client)

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_dict), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=COMPANY_DOC), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=COMPANY_DOC), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'role': 'owner', 'permissions': {'canViewAuditLog': True}, 'company': COMPANY_DOC}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'auditoria': {'enabled': True}}}), \
         patch('app.services.audit_service.AuditService.get_log_detail', return_value=None), \
         patch('app.services.db_service._resolve_company_id', return_value='test_comp_1'):

        resp = client.get('/audit/non-existent-log', follow_redirects=False)
        assert resp.status_code == 302
        assert '/audit' in resp.headers['Location']


def test_audit_export_resolves_company_id(client):
    """Verifica que audit_export no arroja NameError y genera CSV correctamente."""
    user_dict = _setup_audit_session(client)

    sample_logs = [
        {
            "timestamp": "2026-10-12T08:00:00Z",
            "module": "Facturas",
            "action": "CREATE",
            "entityLabel": "Factura #1",
            "entityId": "INV-001",
            "performedBy": "Admin",
            "performedByEmail": "admin@example.com",
            "ipAddress": "127.0.0.1",
            "isSandbox": False,
        }
    ]

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_dict), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=COMPANY_DOC), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=COMPANY_DOC), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'role': 'owner', 'permissions': {'canViewAuditLog': True}, 'company': COMPANY_DOC}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'auditoria': {'enabled': True}}}), \
         patch('app.services.audit_service.AuditService.export_to_csv_rows', return_value=sample_logs), \
         patch('app.web.audit._resolve_company_id', return_value='test_comp_1') as mock_resolve:

        resp = client.post('/audit/export', data={'module': 'Todos', 'action': 'Todos'})
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        assert b"Factura #1" in resp.data
        mock_resolve.assert_called_once_with('test_owner_uid')
