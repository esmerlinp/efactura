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

def test_ingresos_compras_unauthenticated(client):
    resp = client.get('/reports/admin/ingresos-compras')
    assert resp.status_code == 302

def test_ingresos_compras_authenticated_empty(client):
    mock_login(client)
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]))
        resp = client.get('/reports/admin/ingresos-compras?show_zero=1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Ventas' in html
        assert 'Gastos de venta' in html
        assert 'RD$ 0.00' in html

def test_ingresos_compras_with_data(client):
    mock_login(client)
    # Target date: current year
    current_year = datetime.now(timezone.utc).year
    
    mock_invoices = [
        {
            'id': 'inv-1',
            'subtotal': 5000.0,
            'total': 5900.0,
            'totalITBIS': 900.0,
            'creditedAmount': 500.0,
            'date': f'{current_year}-06-01',
            'status': 'Emitida'
        }
    ]
    mock_expenses = [
        {
            'id': 'exp-1',
            'amount': 2360.0,
            'total': 2360.0,
            'totalITBIS': 360.0,
            'concept': 'Pago de sueldo de junio secretaria',
            'category': 'Otros Gastos',
            'approvalStatus': 'Aprobado',
            'date': f'{current_year}-06-10'
        },
        {
            'id': 'exp-2',
            'amount': 1180.0,
            'total': 1180.0,
            'totalITBIS': 180.0,
            'concept': 'Compra de mercancia para bodega',
            'category': 'Otros Gastos',
            'approvalStatus': 'Aprobado',
            'date': f'{current_year}-06-15'
        }
    ]
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=mock_expenses))
        resp = client.get(f'/reports/admin/ingresos-compras?year={current_year}&month=6&show_zero=1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        
        # Verify Sales: 5000.00
        assert 'RD$ 5,000.00' in html
        # Verify Devoluciones: -500.00
        assert 'RD$ -500.00' in html
        # Verify Costos del inventario (exp-2 subtotal = 1180 - 180 = 1000): 1,000.00
        assert 'RD$ 1,000.00' in html
        # Verify Sueldos y salarios (exp-1 subtotal = 2360 - 360 = 2000): 2,000.00
        assert 'RD$ 2,000.00' in html
        
        # Total de ingresos: 5000 - 500 = 4500.00
        assert 'RD$ 4,500.00' in html
        # Total de egresos: Costos (1000) + Gastos (2000) = 3000.00
        assert 'RD$ 3,000.00' in html
        # Saldo: 4500 - 3000 = 1500.00
        assert 'RD$ 1,500.00' in html

def test_ingresos_compras_export(client):
    mock_login(client)
    current_year = datetime.now(timezone.utc).year
    
    mock_invoices = [
        {
            'id': 'inv-1',
            'subtotal': 5000.0,
            'total': 5900.0,
            'totalITBIS': 900.0,
            'creditedAmount': 0.0,
            'date': f'{current_year}-06-01',
            'status': 'Emitida'
        }
    ]
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]))
        resp = client.get(f'/reports/admin/ingresos-compras/export?year={current_year}&month=6&show_zero=1')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        csv_data = resp.data.decode('utf-8-sig')
        assert 'Ventas' in csv_data
        assert '5000.00' in csv_data
