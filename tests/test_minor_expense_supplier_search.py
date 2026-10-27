from unittest.mock import patch
from contextlib import ExitStack
from tests.test_cxp_report import mock_login, DB_PATCHES
from app import create_app


def test_api_suppliers_search_returns_suppliers_and_contacts(client):
    mock_login(client)
    with client.session_transaction() as sess:
        sess['company_modules']['gastos'] = {'enabled': True}
        sess['company_modules']['cxp_compras'] = {'enabled': True}
        sess['company_modules']['e_cf'] = {'enabled': True}

    mock_sups = [
        {'id': 'sup-1', 'name': 'Comercializadora Hermanos Perez SRL', 'rnc': '101-00101-1', 'supplierType': 'formal', 'email': 'perez@test.com'},
        {'id': 'sup-2', 'name': 'Juan Jose Morales', 'rnc': '001-0000000-1', 'supplierType': 'informal', 'email': 'juan@test.com'}
    ]
    mock_contacts = [
        {'id': 'cont-1', 'razonSocial': 'Empresa Asociada Contacto', 'rnc': '131-88068-1', 'supplierType': 'formal', 'email': 'contacto@test.com', 'types': ['cliente']}
    ]

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.supplier_service.SupplierService.get_suppliers', return_value=mock_sups))
        stack.enter_context(patch('app.services.contact_service.ContactService.get_contacts', return_value=mock_contacts))

        # 1. Sin query: debe listar proveedores y contactos disponibles
        res = client.get('/api/suppliers/search')
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert len(data['suppliers']) == 3

        # 2. Búsqueda por nombre de proveedor
        res_perez = client.get('/api/suppliers/search?q=perez')
        assert res_perez.status_code == 200
        data_perez = res_perez.get_json()
        assert len(data_perez['suppliers']) == 1
        assert data_perez['suppliers'][0]['name'] == 'Comercializadora Hermanos Perez SRL'

        # 3. Búsqueda por contacto / cliente
        res_cont = client.get('/api/suppliers/search?q=asociada')
        assert res_cont.status_code == 200
        data_cont = res_cont.get_json()
        assert len(data_cont['suppliers']) == 1
        assert data_cont['suppliers'][0]['name'] == 'Empresa Asociada Contacto'
        assert data_cont['suppliers'][0]['isContact'] is True

        # 4. Búsqueda por dígitos limpios de RNC
        res_rnc = client.get('/api/suppliers/search?q=131880681')
        assert res_rnc.status_code == 200
        data_rnc = res_rnc.get_json()
        assert len(data_rnc['suppliers']) == 1
        assert data_rnc['suppliers'][0]['rnc'] == '131-88068-1'


def test_minor_expense_new_route_preloads_suppliers(client):
    mock_login(client)
    with client.session_transaction() as sess:
        sess['company_modules']['gastos'] = {'enabled': True}
        sess['company_modules']['e_cf'] = {'enabled': True}

    mock_sups = [
        {'id': 'sup-1', 'name': 'Proveedor Formal SRL', 'rnc': '101-00101-1', 'supplierType': 'formal'},
        {'id': 'sup-2', 'name': 'Juan Morales', 'rnc': '', 'supplierType': 'informal'}
    ]
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_company_context', return_value={'role': 'owner', 'permissions': {'canManageMinorExpenses': True}}))
        stack.enter_context(patch('app.services.supplier_service.SupplierService.get_suppliers', return_value=mock_sups))
        stack.enter_context(patch('app.services.contact_service.ContactService.get_contacts', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_tax_rules', return_value={}))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_chart_of_accounts', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_sequences', return_value=[]))

        resp = client.get('/expenses/minor/new')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        # Verificar inputs y contenedor de resultados
        assert 'id="supplier-search"' in html
        assert 'id="supplier-search-results"' in html
        assert 'showSupplierDropdown' in html
        assert 'selectSupplier' in html
        assert 'Proveedor Formal SRL' in html
        assert 'Juan Morales' in html
