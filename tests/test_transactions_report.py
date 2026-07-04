from unittest.mock import patch
from datetime import datetime, timezone

MOCK_USER_PROFILE = {
    'uid': 'test-uid',
    'email': 'admin@test.com',
    'name': 'Admin',
    'role': 'owner',
    'ownerUID': 'test-owner',
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
}

def mock_login(client, owner_uid='test-owner'):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': owner_uid,
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canInvoice': True},
        }
        sess['is_sandbox_mode'] = True

def test_transactions_report_unauthenticated(client):
    resp = client.get('/reports/admin/transactions')
    assert resp.status_code == 302

def test_transactions_report_authenticated_empty(client):
    mock_login(client)
    with patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get('/reports/admin/transactions')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'No tienes transacciones registradas' in html
        assert 'Total entradas' in html
        assert 'Total salidas' in html
        assert 'RD$ 0.00' in html

def test_transactions_report_with_data(client):
    mock_login(client)
    current_year = datetime.now(timezone.utc).year
    
    mock_invoices = [
        {
            'id': 'inv-1',
            'invoiceNumber': 'E31-1001',
            'clientName': 'Cliente A',
            'date': f'{current_year}-06-01'
        }
    ]
    mock_payments = [
        {
            'paymentDate': f'{current_year}-06-15',
            'amount': 5000.0,
            'paymentMethod': 'Transferencia',
            'bank': 'acc-1'
        }
    ]
    mock_expenses = [
        {
            'id': 'exp-1',
            'concept': 'Compra de papelería',
            'rncEmisor': '130-99999-9',
            'paymentType': 'Contado',
            'amount': 2000.0,
            'date': f'{current_year}-06-20'
        }
    ]
    mock_bank_accounts = [
        {'id': 'acc-1', 'name': 'Banco Popular'}
    ]

    with patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=mock_payments), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=mock_expenses), \
         patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=mock_bank_accounts), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        
        resp = client.get(f'/reports/admin/transactions?year={current_year}&month=6')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        
        # Verify inflows (Total entradas): 5,000.00
        assert 'RD$ 5,000.00' in html
        # Verify outflows (Total salidas): 2,000.00
        assert 'RD$ 2,000.00' in html
        
        # Verify description details
        assert 'Pago Recibido: Factura E31-1001 — Cliente A' in html
        assert 'Gasto Contado: Compra de papelería — 130-99999-9' in html
        assert 'Banco Popular' in html

def test_transactions_export(client):
    mock_login(client)
    current_year = datetime.now(timezone.utc).year
    
    mock_invoices = [
        {
            'id': 'inv-1',
            'invoiceNumber': 'E31-1001',
            'clientName': 'Cliente A',
            'date': f'{current_year}-06-01'
        }
    ]
    mock_payments = [
        {
            'paymentDate': f'{current_year}-06-15',
            'amount': 5000.0,
            'paymentMethod': 'Transferencia',
            'bank': 'acc-1'
        }
    ]
    mock_bank_accounts = [
        {'id': 'acc-1', 'name': 'Banco Popular'}
    ]

    with patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=mock_payments), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=mock_bank_accounts), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        
        resp = client.get(f'/reports/admin/transactions/export?year={current_year}&month=6')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        csv_data = resp.data.decode('utf-8-sig')
        assert 'Pago Recibido: Factura E31-1001' in csv_data
        assert '5000.00' in csv_data
