import pytest
from unittest.mock import patch
from tests.test_module_gating import _setup_session


def test_clients_accessible_with_ecf_even_when_crm_disabled(client):
    """Verifica que una empresa con Facturación Electrónica (e-CF) pero SIN CRM
    puede acceder al directorio de contactos/clientes para su operación diaria."""
    modules = {
        'e_cf': {'enabled': True},
        'crm': {'enabled': False},
        'cxp_compras': {'enabled': False},
    }
    user_mock = _setup_session(client, role='owner', permissions={'canClients': True}, enabled_modules=modules)
    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'modules': modules,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'owner', 'permissions': {'canClients': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}), \
         patch('app.services.contact_service.ContactService.get_contacts', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]):

        resp = client.get('/contacts?tab=clientes', follow_redirects=False)
        assert resp.status_code == 200
        assert b"Clientes" in resp.data


def test_new_contact_accessible_with_ecf_without_crm(client):
    """Verifica que se puede acceder al formulario de nuevo contacto sin tener CRM contratado."""
    modules = {
        'e_cf': {'enabled': True},
        'crm': {'enabled': False},
    }
    user_mock = _setup_session(client, role='owner', permissions={'canClients': True}, enabled_modules=modules)
    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'modules': modules,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'owner', 'permissions': {'canClients': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}), \
         patch('app.services.db_service.DatabaseService.get_price_lists', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_team_members', return_value=[]):

        resp = client.get('/contacts/new', follow_redirects=False)
        assert resp.status_code == 200


def test_crm_strict_actions_blocked_when_crm_disabled(client):
    """Verifica que las rutas y acciones estrictamente de CRM quedan bloqueadas (403)
    cuando el módulo CRM no está contratado."""
    modules = {
        'e_cf': {'enabled': True},
        'crm': {'enabled': False},
    }
    user_mock = _setup_session(client, role='owner', permissions={'canClients': True, 'canCRM': True}, enabled_modules=modules)
    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'modules': modules,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'owner', 'permissions': {'canClients': True, 'canCRM': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}):

        # 1. Pipeline CRM completo bloqueado
        resp_crm = client.get('/crm/pipeline', follow_redirects=False)
        assert resp_crm.status_code == 403

        # 2. Modificación de etapa del pipeline en contacto bloqueada
        resp_update = client.post('/contacts/contact_123/update_pipeline',
                                  json={'pipelineStage': 'Negociación'})
        assert resp_update.status_code == 403
        data = resp_update.get_json()
        assert data['error']['code'] == 'MODULE_DISABLED'


def test_suppliers_accessible_with_cxp_without_crm(client):
    """Verifica que los proveedores son accesibles si la empresa tiene cxp_compras activo,
    incluso cuando el módulo CRM está totalmente deshabilitado."""
    modules = {
        'e_cf': {'enabled': False},
        'crm': {'enabled': False},
        'cxp_compras': {'enabled': True},
    }
    user_mock = _setup_session(client, role='owner', permissions={'canManageSuppliers': True, 'canCreateSupplier': True}, enabled_modules=modules)
    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'modules': modules,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'owner', 'permissions': {'canManageSuppliers': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}), \
         patch('app.services.supplier_service.SupplierService.get_suppliers', return_value=[]), \
         patch('app.services.contact_service.ContactService.get_contacts', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_expenses', return_value=[]):

        # Ruta nativa de proveedores
        resp_suppliers = client.get('/suppliers', follow_redirects=False)
        assert resp_suppliers.status_code == 200

        # Pestaña de proveedores en contactos
        resp_tab = client.get('/contacts?tab=proveedores', follow_redirects=False)
        assert resp_tab.status_code == 200


def test_contacts_fail_closed_when_no_modules_enabled(client):
    """Verifica política Fail-Closed: si la empresa no tiene contratado ningún módulo
    de ventas, facturación, compras ni CRM, el acceso a /contacts es denegado (403)."""
    modules = {}
    user_mock = _setup_session(client, role='owner', permissions={'canClients': True}, enabled_modules=modules)
    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'modules': modules,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'owner', 'permissions': {'canClients': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}):

        resp = client.get('/contacts', follow_redirects=False)
        assert resp.status_code == 403


def test_sidebar_shows_clients_under_ventas_when_ecf_enabled_without_crm(app):
    """Verifica que en el sidebar HTML aparece el enlace a Clientes bajo la sección Ventas
    cuando e_cf está activo y CRM deshabilitado, y NO se muestra la sección de CRM."""
    with app.test_request_context():
        from flask import session, render_template
        session.clear()
        session['user'] = {'role': 'owner', 'email': 'owner@test.com', 'permissions': {'canClients': True, 'canInvoice': True}}
        session['company_modules'] = {
            'e_cf': {'enabled': True},
            'crm': {'enabled': False},
            'cxp_compras': {'enabled': False},
        }

        html = render_template('_sidebar_nav.html')
        # "Ventas y Clientes" y enlace a Clientes deben estar presentes
        assert 'Ventas y Clientes' in html
        assert 'Clientes' in html
        assert 'tab=clientes' in html
        # Sección CRM no debe estar presente
        assert 'CRM & Oportunidades' not in html
        assert 'Pipeline' not in html


def test_sidebar_shows_clients_even_when_sales_modules_disabled_if_user_has_permission(app):
    """Verifica que un usuario con canClients ve la sección 'Ventas y Clientes' y la opción 'Clientes'
    incluso si no tiene e_cf o cotizaciones contratadas."""
    with app.test_request_context():
        from flask import session, render_template
        session.clear()
        session['user'] = {'role': 'collaborator', 'email': 'collab@test.com', 'permissions': {'canClients': True}}
        session['company_modules'] = {
            'crm': {'enabled': False},
            'e_cf': {'enabled': False},
        }

        html = render_template('_sidebar_nav.html')
        assert 'Ventas y Clientes' in html
        assert 'Clientes' in html
        assert 'tab=clientes' in html


def test_granular_can_create_client_permission(client):
    """Verifica que canCreateClient controle estrictamente la creación de clientes
    y permita fallback a canClients si la clave granular no está definida."""
    modules = {'e_cf': {'enabled': True}, 'crm': {'enabled': False}}
    company_doc = {
        'id': 'test_comp_1', 'status': 'Activo', 'planId': 'plan_test', 'plan_version': 1,
        'owner_uid': 'test_owner_uid', 'country': 'DO', 'configured': True, 'modules': modules,
    }

    # 1. Usuario con canClients=True pero canCreateClient=False -> 403
    user_forbidden = _setup_session(client, role='vendedor', permissions={'canClients': True, 'canCreateClient': False}, enabled_modules=modules)
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_forbidden), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'vendedor'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'vendedor', 'permissions': {'canClients': True, 'canCreateClient': False}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}):

        resp_new = client.get('/clients/new', follow_redirects=False)
        assert resp_new.status_code == 403

        resp_ajax = client.post('/clients/ajax_create', json={'razonSocial': 'Empresa X'}, follow_redirects=False)
        assert resp_ajax.status_code == 403

        resp_contacts_new = client.get('/contacts/new', follow_redirects=False)
        assert resp_contacts_new.status_code == 403

    # 2. Usuario con canCreateClient=True -> 200
    user_allowed = _setup_session(client, role='vendedor', permissions={'canClients': True, 'canCreateClient': True}, enabled_modules=modules)
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_allowed), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'vendedor'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'vendedor', 'permissions': {'canClients': True, 'canCreateClient': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}), \
         patch('app.services.db_service.DatabaseService.get_price_lists', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_team_members', return_value=[]):

        resp_new = client.get('/clients/new', follow_redirects=False)
        assert resp_new.status_code == 200

    # 3. Fallback: Usuario legacy sin canCreateClient en su diccionario hereda de canClients
    user_legacy = _setup_session(client, role='vendedor', permissions={'canClients': True}, enabled_modules=modules)
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_legacy), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'vendedor'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'vendedor', 'permissions': {'canClients': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}), \
         patch('app.services.db_service.DatabaseService.get_price_lists', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_team_members', return_value=[]):

        resp_new = client.get('/clients/new', follow_redirects=False)
        assert resp_new.status_code == 200


def test_granular_can_delete_client_permission(client):
    """Verifica que canDeleteClient restrinja el borrado de clientes si está deshabilitado."""
    modules = {'e_cf': {'enabled': True}, 'crm': {'enabled': False}}
    company_doc = {
        'id': 'test_comp_1', 'status': 'Activo', 'planId': 'plan_test', 'plan_version': 1,
        'owner_uid': 'test_owner_uid', 'country': 'DO', 'configured': True, 'modules': modules,
    }

    # 1. Usuario con canClients=True pero canDeleteClient=False -> 403
    user_forbidden = _setup_session(client, role='vendedor', permissions={'canClients': True, 'canDeleteClient': False}, enabled_modules=modules)
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_forbidden), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'vendedor'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'vendedor', 'permissions': {'canClients': True, 'canDeleteClient': False}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}), \
         patch('app.services.contact_service.ContactService.get_contact', return_value={'id': 'c1', 'types': ['cliente']}):

        resp_del_client = client.post('/clients/c1/delete', follow_redirects=False)
        assert resp_del_client.status_code == 403

        resp_del_contact = client.post('/contacts/c1/delete', follow_redirects=False)
        assert resp_del_contact.status_code == 403

    # 2. Usuario con canDeleteClient=True -> Permitido
    user_allowed = _setup_session(client, role='vendedor', permissions={'canClients': True, 'canDeleteClient': True}, enabled_modules=modules)
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_allowed), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'vendedor'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'vendedor', 'permissions': {'canClients': True, 'canDeleteClient': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': modules}), \
         patch('app.services.db_service.DatabaseService.get_clients', return_value=[{'id': 'c1'}]), \
         patch('app.services.db_service.DatabaseService.delete_client', return_value=True), \
         patch('app.services.contact_service.ContactService.get_contact', return_value={'id': 'c1', 'types': ['cliente']}), \
         patch('app.services.contact_service.ContactService.delete_contact', return_value=True):

        resp_del_client = client.post('/clients/c1/delete', follow_redirects=False)
        assert resp_del_client.status_code == 302
        assert resp_del_client.headers['Location'].endswith('/clients')

        resp_del_contact = client.post('/contacts/c1/delete', follow_redirects=False)
        assert resp_del_contact.status_code == 302
        assert resp_del_contact.headers['Location'].endswith('/contacts')
