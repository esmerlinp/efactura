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

def test_inventory_value_report_unauthenticated(client):
    resp = client.get('/reports/admin/inventory-value')
    assert resp.status_code == 302

def test_inventory_value_report_authenticated_empty(client):
    mock_login(client)
    with patch('app.services.db_service.DatabaseService.get_warehouses', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_items', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_inventory_stock', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get('/reports/admin/inventory-value')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Búsqueda sin resultados' in html
        assert 'RD$ 0.00' in html

def test_inventory_value_report_with_data(client):
    mock_login(client)
    mock_warehouses = [
        {'id': 'wh-1', 'name': 'Almacén Principal'},
        {'id': 'wh-2', 'name': 'Almacén Secundario'}
    ]
    mock_items = [
        {
            'id': 'item-1',
            'name': 'Producto A',
            'reference': 'REF-A',
            'type': 'Bien',
            'costPrice': 150.0
        },
        {
            'id': 'item-2',
            'name': 'Servicio B',
            'reference': 'REF-B',
            'type': 'Servicio',
            'costPrice': 500.0
        }
    ]
    mock_stocks = [
        {'itemId': 'item-1', 'warehouseId': 'wh-1', 'quantity': 10.0},
        {'itemId': 'item-1', 'warehouseId': 'wh-2', 'quantity': 5.0},
        {'itemId': 'item-2', 'warehouseId': 'wh-1', 'quantity': 2.0} # Should be ignored because it's a Service
    ]
    with patch('app.services.db_service.DatabaseService.get_warehouses', return_value=mock_warehouses), \
         patch('app.services.db_service.DatabaseService.get_items', return_value=mock_items), \
         patch('app.services.db_service.DatabaseService.get_inventory_stock', return_value=mock_stocks), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        
        # Test 1: All Warehouses
        resp = client.get('/reports/admin/inventory-value')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Producto A' in html
        assert 'Servicio B' not in html # Servico ignored
        assert 'Almacén Principal' in html
        assert 'Almacén Secundario' in html
        # Total value: (10 * 150) + (5 * 150) = 2250.00
        assert 'RD$ 2,250.00' in html

        # Test 2: Filter by Warehouse Principal (only wh-1 row should be processed in calculations and rendered in table)
        resp = client.get('/reports/admin/inventory-value?warehouse_id=wh-1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Almacén Principal' in html
        # Total value: 10 * 150 = 1500.00
        assert 'RD$ 1,500.00' in html
        # Let's verify that the table has the specific row, but the total stock value matches 1,500.00, not 2,250.00
        assert 'RD$ 2,250.00' not in html


def test_inventory_value_export(client):
    mock_login(client)
    mock_warehouses = [
        {'id': 'wh-1', 'name': 'Almacén Principal'}
    ]
    mock_items = [
        {
            'id': 'item-1',
            'name': 'Producto A',
            'reference': 'REF-A',
            'type': 'Bien',
            'costPrice': 150.0
        }
    ]
    mock_stocks = [
        {'itemId': 'item-1', 'warehouseId': 'wh-1', 'quantity': 10.0}
    ]
    with patch('app.services.db_service.DatabaseService.get_warehouses', return_value=mock_warehouses), \
         patch('app.services.db_service.DatabaseService.get_items', return_value=mock_items), \
         patch('app.services.db_service.DatabaseService.get_inventory_stock', return_value=mock_stocks), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        resp = client.get('/reports/admin/inventory-value/export')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/csv'
        csv_data = resp.data.decode('utf-8-sig')
        assert 'Producto A' in csv_data
        assert 'REF-A' in csv_data
        assert '1500.00' in csv_data
