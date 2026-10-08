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
    'permissions': {'canInvoice': True}
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
    patch('app.services.db_service.DatabaseService.get_plan', return_value={'modules': {'e_cf': {'enabled': True}, 'reportes': {'enabled': True}, 'gastos': {'enabled': True}, 'inventario': {'enabled': True}, 'contabilidad': {'enabled': True}, 'bancos': {'enabled': True}, 'cxc': {'enabled': True}, 'cxp': {'enabled': True}}}),
)

def mock_login(client, owner_uid='test-uid', company_id='test-uid'):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': owner_uid,
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canInvoice': True},
        }
        sess['selected_company_id'] = company_id
        sess['selected_owner_uid'] = owner_uid
        sess['company_country'] = 'DO'
        sess['company_modules'] = {'e_cf': {'enabled': True}, 'reportes': {'enabled': True}, 'gastos': {'enabled': True}}
        sess['is_sandbox_mode'] = True

def test_annual_report_unauthenticated(client):
    resp = client.get('/reports/admin/reporte-anual')
    assert resp.status_code in (302, 401)


def test_annual_report_authenticated_empty(client):
    mock_login(client)
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_team_members', return_value=[]))
        resp = client.get('/reports/admin/reporte-anual?year=2025')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'No se registraron ventas en este periodo' in html
        assert 'No hay información de ventas para este periodo' in html
        assert 'No hay ventas asociadas a vendedores' in html
        assert 'No se registraron ventas a clientes' in html
        assert 'No se registraron gastos en el año seleccionado' in html
        assert 'RD$ 0.00' in html

def test_annual_report_with_data(client):
    mock_login(client)
    
    mock_invoices = [
        {
            'id': 'inv-1',
            'clientName': 'Cliente VIP',
            'clientRNC': '131-11111-1',
            'date': '2025-05-15T12:00:00Z',
            'total': 120000.0,
            'subtotal': 100000.0,
            'totalITBIS': 20000.0,
            'status': 'Cobrada',
            'isQuotation': False,
            'createdBy': 'vendedor@test.com',
            'items': [
                {
                    'name': 'Producto Premium',
                    'reference': 'REF-PREM',
                    'quantity': 5.0,
                    'price': 20000.0,
                    'total': 100000.0
                }
            ]
        }
    ]
    
    mock_expenses = [
        {
            'id': 'exp-1',
            'category': 'Servicios Públicos',
            'concept': 'Electricidad',
            'date': '2025-06-20',
            'total': 15000.0,
            'approvalStatus': 'Aprobado'
        }
    ]
    
    mock_members = [
        {
            'email': 'vendedor@test.com',
            'name': 'Pedro Vendedor'
        }
    ]
    
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=mock_expenses))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_team_members', return_value=mock_members))
        resp = client.get('/reports/admin/reporte-anual?year=2025')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        
        # Verify Averages:
        # avg_monthly = 120000 / 12 = 10000.00
        assert 'RD$ 10,000.00' in html
        # avg_weekly = 120000 / 52 = 2307.69
        assert 'RD$ 2,307.69' in html
        # avg_daily = 120000 / 365 = 328.77
        assert 'RD$ 328.77' in html
        
        # Verify rankings & details
        assert 'Producto Premium' in html
        assert 'Pedro Vendedor' in html
        assert 'Cliente VIP' in html
        assert 'Servicios Públicos' in html

def test_annual_report_comparison(client):
    mock_login(client)
    
    # 2025: 120,000 sales
    # 2024: 60,000 sales (+100.0% vs previous year)
    mock_invoices = [
        {
            'id': 'inv-1',
            'clientName': 'Cliente A',
            'date': '2025-05-15T12:00:00Z',
            'total': 120000.0,
            'status': 'Cobrada',
            'isQuotation': False,
        },
        {
            'id': 'inv-2',
            'clientName': 'Cliente B',
            'date': '2024-04-10T12:00:00Z',
            'total': 60000.0,
            'status': 'Cobrada',
            'isQuotation': False,
        }
    ]
    
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_team_members', return_value=[]))
        resp = client.get('/reports/admin/reporte-anual?year=2025&compare=1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        
        # Verify the comparison badge +100.0% is displayed
        assert '+100.0% vs 2024' in html
