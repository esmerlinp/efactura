import pytest
from unittest.mock import patch, MagicMock
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


def _mock_company_doc():
    return {
        'id': 'comp_123',
        'owner_uid': 'user_123',
        'company_name': 'Test Company SRL',
        'companyName': 'Test Company SRL',
        'rnc': '131880681',
        'country': 'DO',
        'plan_id': 'plan_test',
        'planId': 'plan_test',
        'plan_version': 1,
        'status': 'active',
        'configured': True,
    }


def _mock_transfers():
    return [
        {
            "id": "trf_001_pend",
            "status": "pendiente",
            "originWarehouseId": "wh_01",
            "originWarehouseName": "Almacén Central",
            "destinationWarehouseId": "wh_02",
            "destinationWarehouseName": "Sucursal Santiago",
            "lines": [
                {
                    "itemId": "item_a",
                    "itemName": "Laptop Dell XPS 15",
                    "quantity": 5,
                    "unitCost": 55000.0,
                },
                {
                    "itemId": "item_b",
                    "itemName": "Mouse Logitech MX Master 3",
                    "quantity": 10,
                    "unitCost": 4500.0,
                }
            ],
            "requestedBy": "pedro@empresa.com",
            "requestedDate": "2026-10-16T10:00:00Z",
            "notes": "Reposición de inventario para sucursal norte",
        },
        {
            "id": "trf_002_comp",
            "status": "completada",
            "originWarehouseId": "wh_02",
            "originWarehouseName": "Sucursal Santiago",
            "destinationWarehouseId": "wh_01",
            "destinationWarehouseName": "Almacén Central",
            "lines": [
                {
                    "itemId": "item_c",
                    "itemName": "Teclado Mecánico Keychron K2",
                    "quantity": 3,
                    "unitCost": 6000.0,
                }
            ],
            "requestedBy": "maria@empresa.com",
            "requestedDate": "2026-10-15T14:30:00Z",
            "approvedBy": "admin@empresa.com",
            "approvedDate": "2026-10-15T15:00:00Z",
            "completedDate": "2026-10-15T15:00:00Z",
            "notes": "Devolución por sobre-stock",
        },
        {
            "id": "trf_003_rech",
            "status": "rechazada",
            "originWarehouseId": "wh_01",
            "originWarehouseName": "Almacén Central",
            "destinationWarehouseId": "wh_03",
            "destinationWarehouseName": "Almacén Bávaro",
            "lines": [
                {
                    "itemId": "item_a",
                    "itemName": "Laptop Dell XPS 15",
                    "quantity": 20,
                    "unitCost": 55000.0,
                }
            ],
            "requestedBy": "juan@empresa.com",
            "requestedDate": "2026-10-14T09:15:00Z",
            "rejectionReason": "Stock insuficiente en almacén central",
            "notes": "Envío urgente para proyecto",
        }
    ]


def test_transfer_list_unauthenticated(client):
    res = client.get('/inventory/transfers')
    assert res.status_code == 302
    assert '/login' in res.location


def test_transfer_detail_unauthenticated(client):
    res = client.get('/inventory/transfers/trf_001_pend')
    assert res.status_code == 302
    assert '/login' in res.location


def test_transfers_forbidden_without_permission(client):
    company_doc = _mock_company_doc()
    with patch('app.services.db_service.DatabaseService.get_user_profile', side_effect=lambda uid, **kw: session.get("user", {})), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'inventario': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'employee'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'employee', 'permissions': {'canInventoryTransfers': False}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.web.invoices.check_permission', return_value=False):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'employee', 'permissions': {'canInventoryTransfers': False}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res_list = client.get('/inventory/transfers')
        assert res_list.status_code == 403

        res_detail = client.get('/inventory/transfers/trf_001_pend')
        assert res_detail.status_code == 403


def test_transfers_list_renders_actions_and_details_for_all_statuses(client):
    company_doc = _mock_company_doc()
    transfers = _mock_transfers()

    with patch('app.services.db_service.DatabaseService.get_user_profile', side_effect=lambda uid, **kw: session.get("user", {})), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'inventario': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'owner', 'permissions': {'canInventoryTransfers': True}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.web.invoices.check_permission', return_value=True), \
         patch('app.services.warehouse_transfer_service.WarehouseTransferService.get_transfers', return_value=transfers):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'owner', 'permissions': {'canInventoryTransfers': True}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res = client.get('/inventory/transfers')
        assert res.status_code == 200
        html = res.data.decode('utf-8')

        # Check Page Title & Header
        assert "Transferencias entre Almacenes" in html

        # Check KPIs
        assert "Total Transferencias" in html
        assert "Pendientes de Aprobación" in html
        assert "Completadas" in html
        assert "Rechazadas" in html

        # Check that ALL transfers have "Detalle" link and are displayed
        assert "/inventory/transfers/trf_001_pend" in html
        assert "/inventory/transfers/trf_002_comp" in html
        assert "/inventory/transfers/trf_003_rech" in html

        # Check that completed & rejected rows now HAVE action buttons (not empty!)
        assert "btn-transfer-view" in html
        assert "btn-transfer-drawer" in html
        assert "openTransferDrawer('trf_002_comp')" in html
        assert "openTransferDrawer('trf_003_rech')" in html

        # Check that Quick View Drawer elements exist
        assert "id=\"transferDrawer\"" in html
        assert "id=\"drawerBackdrop\"" in html


def test_transfer_detail_route_renders_full_information(client):
    company_doc = _mock_company_doc()
    transfer = _mock_transfers()[0]  # trf_001_pend

    with patch('app.services.db_service.DatabaseService.get_user_profile', side_effect=lambda uid, **kw: session.get("user", {})), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'inventario': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'owner', 'permissions': {'canInventoryTransfers': True}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.web.invoices.check_permission', return_value=True), \
         patch('app.services.warehouse_transfer_service.WarehouseTransferService.get_transfer', return_value=transfer):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'owner', 'permissions': {'canInventoryTransfers': True}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res = client.get('/inventory/transfers/trf_001_pend')
        assert res.status_code == 200
        html = res.data.decode('utf-8')

        # Check transfer ID and warehouses
        assert "#trf_001_" in html
        assert "Almacén Central" in html
        assert "Sucursal Santiago" in html

        # Check items transferred table
        assert "Laptop Dell XPS 15" in html
        assert "Mouse Logitech MX Master 3" in html
        assert "55,000.00" in html
        assert "4,500.00" in html

        # Check total units (5 + 10 = 15)
        assert "15" in html

        # Check approval & reject action buttons are present for pending status
        assert "Aprobar Transferencia" in html
        assert "Rechazar" in html


def test_transfer_detail_not_found_redirects_to_list(client):
    company_doc = _mock_company_doc()

    with patch('app.services.db_service.DatabaseService.get_user_profile', side_effect=lambda uid, **kw: session.get("user", {})), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'inventario': {'enabled': True}}}), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'owner', 'permissions': {'canInventoryTransfers': True}}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.web.invoices.check_permission', return_value=True), \
         patch('app.services.warehouse_transfer_service.WarehouseTransferService.get_transfer', return_value=None):

        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user_123', 'ownerUID': 'user_123', 'role': 'owner', 'permissions': {'canInventoryTransfers': True}}
            sess['selected_company_id'] = 'comp_123'
            sess['is_sandbox_mode'] = True

        res = client.get('/inventory/transfers/non_existent_id')
        assert res.status_code == 302
        assert '/inventory/transfers' in res.location
