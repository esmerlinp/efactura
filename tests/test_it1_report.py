from unittest.mock import MagicMock, patch
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

def test_it1_list_unauthenticated(client):
    resp = client.get('/reports/fiscal/it1')
    assert resp.status_code == 302

def test_it1_list_authenticated_empty(client):
    mock_login(client)
    mock_coll = MagicMock()
    mock_coll.get.return_value = []
    
    with patch('app.web.reports_sales._it1_coll', return_value=mock_coll), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get('/reports/fiscal/it1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'No se encontraron reportes' in html

def test_it1_list_with_data(client):
    mock_login(client)
    
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {
        'id': 'it1-1',
        'year': 2026,
        'month': 7,
        'status': 'Borrador',
        'sales_subtotal': 100000.0,
        'total_itbis_sales': 18000.0,
        'expenses_subtotal': 50000.0,
        'total_itbis_expenses': 9000.0,
        'total_retained_itbis': 2000.0,
        'total_retained_isr': 1500.0
    }
    
    mock_coll = MagicMock()
    mock_coll.get.return_value = [mock_doc]
    
    with patch('app.web.reports_sales._it1_coll', return_value=mock_coll), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get('/reports/fiscal/it1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Julio' in html
        assert '2026' in html
        assert 'Borrador' in html
        assert 'RD$ 50,000.00' in html
        # Total retenciones = 2000 + 1500 = 3500.00
        assert 'RD$ 3,500.00' in html

def test_it1_new_preview(client):
    mock_login(client)
    
    # Mock invoices for June 2026
    mock_invoices = [
        {
            'id': 'inv-1',
            'date': '2026-06-15',
            'subtotal': 100000.0,
            'totalITBIS': 18000.0,
            'retainedITBIS': 2000.0,
            'retainedISR': 1500.0,
            'status': 'Cobrada',
            'isQuotation': False
        }
    ]
    mock_expenses = [
        {
            'id': 'exp-1',
            'date': '2026-06-20',
            'amount': 59000.0,
            'itbisAmount': 9000.0,
            'isITBISDeductible': True,
            'approvalStatus': 'Aprobado'
        }
    ]
    
    with patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=mock_expenses), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        
        # GET request to preview
        resp = client.get('/reports/fiscal/it1/new?year=2026&month=6')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        
        assert 'Resumen Previo' in html
        # Sales gravadas: 100000.00
        assert 'RD$ 100,000.00' in html
        # ITBIS Ventas: 18000.00
        assert 'RD$ 18,000.00' in html
        # Compras deducibles: 59000 - 9000 = 50000.00
        assert 'RD$ 50,000.00' in html
        # ITBIS Compras: 9000.00
        assert 'RD$ 9,000.00' in html
        # ITBIS Balance: 18000 - 9000 = 9000.00 (Neto a pagar)
        assert 'RD$ 9,000.00' in html

def test_it1_create_report(client):
    mock_login(client)
    
    mock_invoices = []
    mock_expenses = []
    
    mock_coll = MagicMock()
    # Mock duplicate check return empty
    mock_coll.where.return_value.where.return_value.get.return_value = []
    
    with patch('app.web.reports_sales._it1_coll', return_value=mock_coll), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=mock_expenses), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        
        # POST request to create report for June 2026
        resp = client.post('/reports/fiscal/it1/new', data={'year': '2026', 'month': '6'})
        # Should redirect to detail view
        assert resp.status_code == 302
        assert '/reports/fiscal/it1/' in resp.headers['Location']
        
        # Verify that set() was called on a document
        mock_coll.document.assert_called_once()
        saved_data = mock_coll.document.return_value.set.call_args[0][0]
        assert saved_data['year'] == 2026
        assert saved_data['month'] == 6
        assert saved_data['status'] == 'Borrador'

def test_it1_report_detail_and_update(client):
    mock_login(client)
    
    report_data = {
        'id': 'it1-1',
        'year': 2026,
        'month': 7,
        'status': 'Borrador',
        'sales_subtotal': 100000.0,
        'total_itbis_sales': 18000.0,
        'expenses_subtotal': 50000.0,
        'total_itbis_expenses': 9000.0,
        'total_retained_itbis': 2000.0,
        'total_retained_isr': 1500.0
    }
    
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = report_data
    
    mock_coll = MagicMock()
    mock_coll.document.return_value.get.return_value = mock_doc
    
    with patch('app.web.reports_sales._it1_coll', return_value=mock_coll), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
         
        # GET Detail
        resp = client.get('/reports/fiscal/it1/it1-1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Declaración de ITBIS' in html
        assert '07/2026' in html
        
        # POST Update status to 'Presentado'
        resp_post = client.post('/reports/fiscal/it1/it1-1', data={'status': 'Presentado'})
        assert resp_post.status_code == 200
        mock_coll.document.return_value.update.assert_called_with({'status': 'Presentado'})

def test_it1_report_delete(client):
    mock_login(client)
    
    mock_coll = MagicMock()
    
    with patch('app.web.reports_sales._it1_coll', return_value=mock_coll), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
         
        resp = client.post('/reports/fiscal/it1/it1-1/delete')
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/reports/fiscal/it1')
        mock_coll.document.assert_called_with('it1-1')
        mock_coll.document.return_value.delete.assert_called_once()
