import pytest
from unittest.mock import patch
from flask import session
from app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_inventory_route_unauthenticated(client):
    res = client.get('/inventory')
    assert res.status_code == 302
    assert '/login' in res.location


def test_inventory_route_forbidden_permission(client):
    company_doc = {
        'id': 'comp_123',
        'owner_uid': 'user_123',
        'company_name': 'Test Co',
        'companyName': 'Test Co',
        'rnc': '123456789',
        'country': 'DO',
        'plan_id': 'plan_test',
        'planId': 'plan_test',
        'plan_version': 1,
        'status': 'active',
        'configured': True,
    }
    with patch('app.services.db_service.DatabaseService.get_user_profile', side_effect=lambda uid, **kw: session.get("user", {})), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'inventario': {'enabled': True}, 'e_cf': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'viewer'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'viewer', 'permissions': {'canViewInventoryDashboard': False}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.web.invoices.check_permission', return_value=False):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'viewer', 'permissions': {'canViewInventoryDashboard': False}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res = client.get('/inventory')
        assert res.status_code == 403


def test_inventory_route_renders_redesigned_grid(client):
    company_doc = {
        'id': 'comp_123',
        'owner_uid': 'user_123',
        'company_name': 'Test Co',
        'companyName': 'Test Co',
        'rnc': '123456789',
        'country': 'DO',
        'plan_id': 'plan_test',
        'planId': 'plan_test',
        'plan_version': 1,
        'status': 'active',
        'configured': True,
    }
    mock_warehouses = [
        {"id": "wh_1", "name": "Almacén Principal", "code": "ALM-PRI"},
        {"id": "wh_2", "name": "Depósito Norte", "code": "DEP-NOR"}
    ]
    mock_items = [
        {
            "id": "item_1",
            "code": "MON-24",
            "barcode": "7469876543210",
            "name": "Monitor Dell 24 pulgadas",
            "categoryId": "tecnologia",
            "type": "Bien",
            "unit": "Unidad",
            "rackLocation": "A-1",
            "price": 12000.0,
            "costPrice": 8500.0,
            "totalStock": 4.0,
            "minStock": 5.0,
            "maxStock": 20.0,
            "isActive": True
        },
        {
            "id": "item_2",
            "code": "TECL-RGB",
            "barcode": "7461112223334",
            "name": "Teclado Mecánico RGB",
            "categoryId": "accesorios",
            "type": "Bien",
            "unit": "Unidad",
            "rackLocation": "B-3",
            "price": 4500.0,
            "costPrice": 2800.0,
            "totalStock": 15.0,
            "minStock": 3.0,
            "maxStock": 30.0,
            "isActive": True
        }
    ]
    mock_stocks = [
        {"itemId": "item_1", "warehouseId": "wh_1", "quantity": 3.0},
        {"itemId": "item_1", "warehouseId": "wh_2", "quantity": 1.0},
        {"itemId": "item_2", "warehouseId": "wh_1", "quantity": 10.0},
        {"itemId": "item_2", "warehouseId": "wh_2", "quantity": 5.0},
    ]

    with patch('app.services.db_service.DatabaseService.get_user_profile', side_effect=lambda uid, **kw: session.get("user", {})), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'inventario': {'enabled': True}, 'e_cf': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'owner', 'permissions': {'canViewInventoryDashboard': True}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.utils.decorators.check_permission', return_value=True), \
         patch('app.web.invoices.check_permission', return_value=True), \
         patch('app.services.db_service.DatabaseService.get_warehouses', return_value=mock_warehouses), \
         patch('app.services.db_service.DatabaseService.get_items', return_value=mock_items), \
         patch('app.services.db_service.DatabaseService.get_inventory_stock', return_value=mock_stocks):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'owner', 'permissions': {'canViewInventoryDashboard': True}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res = client.get('/inventory')
        assert res.status_code == 200
        html = res.data.decode('utf-8')

        # 1. Verifica los 4 KPIs ejecutivos de inventario
        assert "Almacenes" in html
        assert "Bienes Registrados" in html
        assert "Existencia Total" in html
        assert "Stock Crítico" in html

        # 2. Verifica la barra de búsqueda y los chips de filtrado rápido
        assert "inventory-search-input" in html
        assert "chip-all" in html
        assert "chip-in-stock" in html
        assert "chip-low-stock" in html

        # 3. Verifica las cabeceras de almacén y matriz
        assert "inventory-table" in html
        assert "Cód. / SKU" in html
        assert "Descripción del Producto" in html
        assert "Almacén Principal" in html
        assert "Depósito Norte" in html
        assert "Existencia Total" in html
        assert "Valorización" in html
        assert "Acciones" in html

        # 4. Verifica producto con alerta de stock crítico
        assert "MON-24" in html
        assert "Monitor Dell 24 pulgadas" in html
        assert "stock-pill-low" in html

        # 5. Verifica Drawer lateral de consulta rápida de inventario
        assert "inventory-drawer" in html
        assert "drawer-wh-container" in html
        assert "openInventoryDrawer" in html
