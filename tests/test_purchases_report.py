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

def test_purchases_report_unauthenticated(client):
    resp = client.get('/reports/admin/purchases')
    assert resp.status_code == 302

def test_purchases_report_authenticated_empty(client):
    mock_login(client)
    with patch('app.services.supplier_invoice_service.SupplierInvoiceService.get_all', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get('/reports/admin/purchases')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'No hay registros que cumplan con los filtros' in html
        assert 'RD$ 0.00' in html

def test_purchases_report_with_data(client):
    mock_login(client)
    current_year = datetime.now(timezone.utc).year
    
    mock_invoices = [
        {
            'id': 'sinv-1',
            'invoiceNumber': 'FAC-001',
            'supplierInvoiceNumber': 'NCF-001',
            'ncf': 'B1100000001',
            'supplierName': 'Proveedor A',
            'supplierRnc': '131-00000-1',
            'date': f'{current_year}-06-10',
            'dueDate': f'{current_year}-07-10',
            'subtotal': 10000.0,
            'discount': 1000.0,
            'itbis': 1620.0,
            'total': 10620.0,
            'cxpStatus': 'Pendiente'
        }
    ]
    with patch('app.services.supplier_invoice_service.SupplierInvoiceService.get_all', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get(f'/reports/admin/purchases?year={current_year}&month=6')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        
        # Verify subtotal (Antes de impuestos): 10000 - 1000 = 9000.00
        assert 'RD$ 9,000.00' in html
        # Verify total (Después de impuestos): 10620.00
        assert 'RD$ 10,620.00' in html
        
        # Verify columns & text details
        assert 'FAC-001' in html
        assert 'NCF-001' in html
        assert 'Proveedor A' in html
        assert 'RNC: 131-00000-1' in html

def test_purchases_export(client):
    mock_login(client)
    current_year = datetime.now(timezone.utc).year
    
    mock_invoices = [
        {
            'id': 'sinv-1',
            'invoiceNumber': 'FAC-001',
            'supplierInvoiceNumber': 'NCF-001',
            'ncf': 'B1100000001',
            'supplierName': 'Proveedor A',
            'supplierRnc': '131-00000-1',
            'date': f'{current_year}-06-10',
            'dueDate': f'{current_year}-07-10',
            'subtotal': 10000.0,
            'discount': 1000.0,
            'itbis': 1620.0,
            'total': 10620.0,
            'cxpStatus': 'Pendiente'
        }
    ]
    with patch('app.services.supplier_invoice_service.SupplierInvoiceService.get_all', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get(f'/reports/admin/purchases/export?year={current_year}&month=6')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        csv_data = resp.data.decode('utf-8-sig')
        assert 'FAC-001' in csv_data
        assert '9000.00' in csv_data
        assert '10620.00' in csv_data
