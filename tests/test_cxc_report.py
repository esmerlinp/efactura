from unittest.mock import patch
from datetime import datetime, timezone
from contextlib import ExitStack

MOCK_USER_PROFILE = {
    'uid': 'test-uid',
    'email': 'admin@test.com',
    'name': 'Admin',
    'role': 'owner',
    'ownerUID': 'test-uid',
    'status': 'active',
    'permissions': {'canInvoice': True, 'canReports': True}
}

MOCK_COMPANY = {
    'companyRNC': '132-10912-2',
    'companyName': 'Test Co',
    'configured': True,
    'posEnabled': True,
    'productionEnabled': True,
    'sandboxEnabled': True,
    'sandboxIndefinite': True,
    'planId': 'plan123',
    'country': 'DO',
}

DB_PATCHES = (
    patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE),
    patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-uid', 'companyName': 'Test Co', 'role': 'owner'}]),
    patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY),
    patch('app.services.db_service.DatabaseService.get_company', return_value=None),
    patch('app.services.db_service.DatabaseService.get_company_context', return_value={'permissions': {}, 'company_name': 'Test Co'}),
    patch('app.services.db_service.DatabaseService.get_branches', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_projects', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active'}),
    patch('app.services.db_service.DatabaseService.get_plan', return_value={'modules': {
        'e_cf': {'enabled': True},
        'reportes': {'enabled': True},
        'gastos': {'enabled': True},
        'inventario': {'enabled': True},
        'contabilidad': {'enabled': True},
        'bancos': {'enabled': True},
        'cxc': {'enabled': True},
        'cxp': {'enabled': True},
    }}),
)

def mock_login(client, owner_uid='test-uid', company_id='test-uid'):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': owner_uid,
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canInvoice': True, 'canReports': True},
        }
        sess['selected_company_id'] = company_id
        sess['selected_owner_uid'] = owner_uid
        sess['company_country'] = 'DO'
        sess['company_modules'] = {
            'e_cf': {'enabled': True},
            'reportes': {'enabled': True},
            'gastos': {'enabled': True},
            'inventario': {'enabled': True},
            'contabilidad': {'enabled': True},
            'bancos': {'enabled': True},
            'cxc': {'enabled': True},
            'cxp': {'enabled': True},
        }
        sess['is_sandbox_mode'] = True

def test_cxc_report_unauthenticated(client):
    resp = client.get('/reports/admin/cxc')
    assert resp.status_code == 302 # Redirect to login page

def test_cxc_report_authenticated_empty(client):
    mock_login(client)
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]))
        resp = client.get('/reports/admin/cxc')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'No tienes facturas pendientes por cobrar' in html

def test_cxc_report_with_data(client):
    mock_login(client)
    mock_invoices = [
        {
            'id': 'inv-1',
            'invoiceNumber': 'F001',
            'encf': 'E310000000001',
            'clientName': 'Cliente A',
            'clientId': 'client-a',
            'clientRNC': '131111111',
            'date': '2026-06-01',
            'dueDate': '2026-06-15',
            'status': 'Emitida',
            'isQuotation': False,
            'total': 1000.0,
            'totalPaid': 0.0,
            'remainingBalance': 1000.0,
            'netPayable': 1000.0,
            'ecfType': 'Factura de Crédito Fiscal (E31)'
        },
        {
            'id': 'inv-2',
            'invoiceNumber': 'F002',
            'encf': 'E310000000002',
            'clientName': 'Cliente B',
            'clientId': 'client-b',
            'clientRNC': '131111112',
            'date': '2026-06-10',
            'dueDate': '2026-07-10',
            'status': 'Parcialmente Cobrada',
            'isQuotation': False,
            'total': 2000.0,
            'totalPaid': 500.0,
            'remainingBalance': 1500.0,
            'netPayable': 2000.0,
            'ecfType': 'Factura de Crédito Fiscal (E31)'
        }
    ]
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices))
        resp = client.get('/reports/admin/cxc?hasta=2026-07-04')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Cliente A' in html
        assert 'Cliente B' in html
        assert 'E310000000001' in html
        assert 'E310000000002' in html
        assert 'RD$ 1,000.00' in html
        assert 'RD$ 1,500.00' in html
        assert 'RD$ 2,500.00' in html

def test_cxc_report_export(client):
    mock_login(client)
    mock_invoices = [
        {
            'id': 'inv-1',
            'invoiceNumber': 'F001',
            'encf': 'E310000000001',
            'clientName': 'Cliente A',
            'clientId': 'client-a',
            'clientRNC': '131111111',
            'date': '2026-06-01',
            'dueDate': '2026-06-15',
            'status': 'Emitida',
            'isQuotation': False,
            'total': 1000.0,
            'totalPaid': 0.0,
            'remainingBalance': 1000.0,
            'netPayable': 1000.0,
            'ecfType': 'Factura de Crédito Fiscal (E31)'
        }
    ]
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices))
        resp = client.get('/reports/admin/cxc/export?hasta=2026-07-04')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        assert 'attachment' in resp.headers.get('Content-Disposition', '')
        csv_data = resp.data.decode('utf-8-sig')
        assert 'Cliente A' in csv_data
        assert 'E310000000001' in csv_data
