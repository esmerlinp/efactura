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
    'permissions': {'canExpenses': True, 'canReports': True}
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
            'permissions': {'canExpenses': True, 'canReports': True},
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

def test_cxp_report_unauthenticated(client):
    resp = client.get('/reports/admin/cxp')
    assert resp.status_code == 302 # Redirect to login page

def test_cxp_report_authenticated_empty(client):
    mock_login(client)
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.supplier_invoice_service.SupplierInvoiceService.get_all', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]))
        resp = client.get('/reports/admin/cxp')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'No tienes facturas pendientes por pagar' in html

def test_cxp_report_with_data(client):
    mock_login(client)
    mock_invoices = [
        {
            'id': 'inv-1',
            'invoiceNumber': 'F001',
            'ncf': 'E310000000001',
            'supplierName': 'Proveedor A',
            'supplierRnc': '131111111',
            'date': '2026-06-01',
            'dueDate': '2026-06-15',
            'cxpStatus': 'Pendiente',
            'total': 1000.0,
            'cxpRemainingBalance': 1000.0,
        }
    ]
    mock_expenses = [
        {
            'id': 'exp-1',
            'documentNumber': 'E001',
            'ncf': 'E310000000002',
            'providerName': 'Proveedor B',
            'rncEmisor': '131111112',
            'date': '2026-06-10',
            'dueDate': '2026-07-10',
            'paymentType': 'Crédito',
            'approvalStatus': 'Aprobado',
            'cxpStatus': 'Abonado',
            'amount': 2000.0,
            'cxpRemainingBalance': 1500.0,
        }
    ]
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.supplier_invoice_service.SupplierInvoiceService.get_all', return_value=mock_invoices))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=mock_expenses))
        resp = client.get('/reports/admin/cxp?hasta=2026-07-04')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Proveedor A' in html
        assert 'Proveedor B' in html
        assert 'E310000000001' in html
        assert 'E310000000002' in html
        assert 'RD$ 1,000.00' in html
        assert 'RD$ 1,500.00' in html
        assert 'RD$ 2,500.00' in html

def test_cxp_report_export(client):
    mock_login(client)
    mock_invoices = [
        {
            'id': 'inv-1',
            'invoiceNumber': 'F001',
            'ncf': 'E310000000001',
            'supplierName': 'Proveedor A',
            'supplierRnc': '131111111',
            'date': '2026-06-01',
            'dueDate': '2026-06-15',
            'cxpStatus': 'Pendiente',
            'total': 1000.0,
            'cxpRemainingBalance': 1000.0,
        }
    ]
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.supplier_invoice_service.SupplierInvoiceService.get_all', return_value=mock_invoices))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]))
        resp = client.get('/reports/admin/cxp/export?hasta=2026-07-04')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        assert 'attachment' in resp.headers.get('Content-Disposition', '')
        csv_data = resp.data.decode('utf-8-sig')
        assert 'Proveedor A' in csv_data
        assert 'E310000000001' in csv_data
