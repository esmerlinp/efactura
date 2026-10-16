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


def test_items_route_unauthenticated(client):
    res = client.get('/items')
    assert res.status_code == 302
    assert '/login' in res.location


def test_items_route_forbidden_permission(client):
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
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'catalogo': {'enabled': True}, 'e_cf': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'viewer'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'viewer', 'permissions': {'canManageCatalog': False}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.web.invoices.check_permission', return_value=False):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'viewer', 'permissions': {'canManageCatalog': False}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res = client.get('/items')
        assert res.status_code == 403


def test_items_route_renders_redesigned_grid(client):
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
    mock_items = [
        {
            "id": "item_1",
            "code": "LAP-001",
            "barcode": "7461234567890",
            "name": "Laptop Lenovo ThinkPad",
            "categoryId": "tecnologia",
            "type": "Bien",
            "unit": "Unidad",
            "rackLocation": "Pasillo B-2",
            "price": 55000.0,
            "costPrice": 42000.0,
            "wholesalePrice": 50000.0,
            "itbisRate": 0.18,
            "codigoImpuesto": "001",
            "totalStock": 3.0,
            "minStock": 5.0,
            "maxStock": 20.0,
            "brand": "Lenovo",
            "supplierName": "Tech Import SRL",
            "imageUrl": "https://example.com/laptop.jpg",
            "isActive": True
        },
        {
            "id": "item_2",
            "code": "SRV-CONS",
            "barcode": "",
            "name": "Servicio de Consultoría IT",
            "categoryId": "servicios",
            "type": "Servicio",
            "unit": "Hora",
            "rackLocation": "",
            "price": 3500.0,
            "costPrice": 1200.0,
            "wholesalePrice": 0.0,
            "itbisRate": 0.18,
            "codigoImpuesto": "",
            "totalStock": 0.0,
            "minStock": 0.0,
            "maxStock": 0.0,
            "brand": "",
            "supplierName": "",
            "imageUrl": "",
            "isActive": True
        }
    ]

    with patch('app.services.db_service.DatabaseService.get_user_profile', side_effect=lambda uid, **kw: session.get("user", {})), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'catalogo': {'enabled': True}, 'e_cf': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'owner', 'permissions': {'canManageCatalog': True}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.utils.decorators.check_permission', return_value=True), \
         patch('app.web.invoices.check_permission', return_value=True), \
         patch('app.services.db_service.DatabaseService.get_items', return_value=mock_items):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'owner', 'permissions': {'canManageCatalog': True}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res = client.get('/items')
        assert res.status_code == 200
        html = res.data.decode('utf-8')

        # 1. Verifica los 4 KPIs ejecutivos
        assert "Catálogo Total" in html
        assert "Bienes Físicos" in html
        assert "Servicios" in html
        assert "Stock Crítico" in html

        # 2. Verifica la barra de búsqueda y los chips de filtrado rápido
        assert "catalog-search-input" in html
        assert "chip-all" in html
        assert "chip-bien" in html
        assert "chip-servicio" in html
        assert "chip-low-stock" in html

        # 3. Verifica la estructura limpia de 6 columnas
        assert "catalog-table" in html
        assert "Cód. / SKU" in html
        assert "Artículo / Producto" in html
        assert "Existencia / Stock" in html
        assert "Precio &amp; Costo" in html or "Precio & Costo" in html
        assert "ITBIS" in html
        assert "Acciones" in html

        # 4. Verifica datos del artículo Bien con alerta de stock
        assert "LAP-001" in html
        assert "Laptop Lenovo ThinkPad" in html
        assert "stock-pill-low" in html

        # 5. Verifica datos del Servicio
        assert "Servicio de Consultoría IT" in html
        assert "No inventariable" in html

        # 6. Verifica el Drawer lateral de consulta rápida
        assert "catalog-drawer" in html
        assert "drawer-title" in html
        assert "openItemDrawer" in html


def test_items_route_export_csv(client):
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
    mock_items = [
        {
            "id": "item_1",
            "code": "LAP-001",
            "barcode": "7461234567890",
            "name": "Laptop Lenovo ThinkPad",
            "categoryId": "tecnologia",
            "type": "Bien",
            "unit": "Unidad",
            "rackLocation": "Pasillo B-2",
            "price": 55000.0,
            "costPrice": 42000.0,
            "itbisRate": 0.18,
            "totalStock": 3.0,
            "isActive": True
        }
    ]

    with patch('app.services.db_service.DatabaseService.get_user_profile', side_effect=lambda uid, **kw: session.get("user", {})), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'catalogo': {'enabled': True}, 'e_cf': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'owner', 'permissions': {'canManageCatalog': True}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.utils.decorators.check_permission', return_value=True), \
         patch('app.web.invoices.check_permission', return_value=True), \
         patch('app.services.db_service.DatabaseService.get_items', return_value=mock_items):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'owner', 'permissions': {'canManageCatalog': True}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res = client.get('/items?export=csv')
        assert res.status_code == 200
        assert res.mimetype == "text/csv"
        content = res.data.decode('utf-8')
        assert "LAP-001" in content
        assert "Laptop Lenovo ThinkPad" in content
