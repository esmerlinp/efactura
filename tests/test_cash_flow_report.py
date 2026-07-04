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

def test_cash_flow_report_unauthenticated(client):
    resp = client.get('/reports/financial/cash-flow')
    assert resp.status_code == 302

def test_cash_flow_report_authenticated_empty(client):
    mock_login(client)
    with patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get('/reports/financial/cash-flow?year=2026&month=7')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Sin movimientos de efectivo en este periodo' in html
        assert 'RD$ 0.00' in html

def test_cash_flow_report_with_ledger_calculations(client):
    mock_login(client)
    
    # 1 bank account with initialBalance = 10,000.00
    mock_accounts = [{'initialBalance': 10000.0, 'name': 'Banco A'}]
    
    # Invoices: 1 invoice with a payment in June 2026 of 5,000.00
    mock_invoices = [{'id': 'inv-1', 'status': 'Abonada', 'isQuotation': False, 'date': '2026-06-01'}]
    mock_invoice_payments = [{'amount': 5000.0, 'paymentDate': '2026-06-15T12:00:00Z'}]
    
    # Expenses: 1 expense with payment in July 2026 of 3,000.00
    mock_expenses = [{'id': 'exp-1', 'paymentType': 'Crédito', 'approvalStatus': 'Aprobado', 'date': '2026-07-01'}]
    mock_cxp_payments = [{'amount': 3000.0, 'paymentDate': '2026-07-10'}]
    
    with patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=mock_accounts), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=mock_invoice_payments), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=mock_expenses), \
         patch('app.services.db_service.DatabaseService.get_cxp_payments', return_value=mock_cxp_payments), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        
        # Request for July 2026 (rolling months: May 2026, June 2026, July 2026)
        resp = client.get('/reports/financial/cash-flow?year=2026&month=7')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        
        # May 2026: Saldo inicial = 10,000.00, Entradas = 0.00, Salidas = 0.00, Saldo final = 10,000.00
        # June 2026: Saldo inicial = 10,000.00, Entradas = 5,000.00, Salidas = 0.00, Saldo final = 15,000.00
        # July 2026: Saldo inicial = 15,000.00, Entradas = 0.00, Salidas = 3,000.00, Saldo final = 12,000.00
        
        # Verify Saldo Inicial: May = 10k, June = 10k, July = 15k
        assert 'RD$ 10,000.00' in html
        assert 'RD$ 15,000.00' in html
        # Verify Entradas: June = 5k
        assert 'RD$ 5,000.00' in html
        # Verify Salidas: July = 3k
        assert 'RD$ 3,000.00' in html
        # Verify Saldo final: July = 12k
        assert 'RD$ 12,000.00' in html

def test_cash_flow_export(client):
    mock_login(client)
    
    mock_accounts = [{'initialBalance': 10000.0, 'name': 'Banco A'}]
    mock_invoices = [{'id': 'inv-1', 'status': 'Abonada', 'isQuotation': False, 'date': '2026-06-01'}]
    mock_invoice_payments = [{'amount': 5000.0, 'paymentDate': '2026-06-15T12:00:00Z'}]
    mock_expenses = [{'id': 'exp-1', 'paymentType': 'Crédito', 'approvalStatus': 'Aprobado', 'date': '2026-07-01'}]
    mock_cxp_payments = [{'amount': 3000.0, 'paymentDate': '2026-07-10'}]
    
    with patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=mock_accounts), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=mock_invoice_payments), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=mock_expenses), \
         patch('app.services.db_service.DatabaseService.get_cxp_payments', return_value=mock_cxp_payments), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
         
        resp = client.get('/reports/financial/cash-flow/export?year=2026&month=7')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        csv_data = resp.data.decode('utf-8-sig')
        
        # Verify columns & fields
        assert 'Concepto' in csv_data
        assert 'Mayo 2026' in csv_data
        assert 'Junio 2026' in csv_data
        assert 'Julio 2026' in csv_data
        
        assert 'Saldo inicial en caja y bancos' in csv_data
        assert '10000.00' in csv_data
        assert '15000.00' in csv_data
        
        assert 'Saldo final en caja y bancos' in csv_data
        assert '12000.00' in csv_data
