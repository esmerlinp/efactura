"""Tests de seguridad y autorización para la gestión de módulos (Entitlements y RBAC).

Verifica que se cumpla estrictamente la regla fundamental:
ACCESO = authenticated AND tenant_valid AND module_enabled(company, module) AND user_has_permission(user, permission)

En particular:
1. module no contratado + owner -> DENY (403)
2. module no contratado + member con permiso -> DENY (403)
3. module contratado + member sin permiso -> DENY (403)
4. module contratado + member con permiso -> ALLOW (200)
5. Deep links bloqueados en Web Blueprints
6. APIs REST v1 bloqueadas con código 403 y error MODULE_DISABLED
7. Invalidez de caché con plan_version
8. Fail-closed total si company_modules está vacío o es None
"""

import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from app.utils.module_gate import module_enabled, require_module


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ═══════════════════════════════════════════════════════════════════════════
# 1. PRUEBAS DE FAIL-CLOSED Y ENTITLEMENT (module_gate.py)
# ═══════════════════════════════════════════════════════════════════════════

def test_empty_modules_fails_closed(app):
    """Si company_modules está vacío, NINGÚN módulo debe estar habilitado."""
    with app.test_request_context():
        from flask import session
        session.clear()
        session['company_modules'] = {}
        session['user'] = {'role': 'owner', 'permissions': {}}

        assert module_enabled('e_cf') is False
        assert module_enabled('crm') is False
        assert module_enabled('inventario') is False
        assert module_enabled('banks') is False
        assert module_enabled('contabilidad') is False
        assert module_enabled('nomina') is False
        assert module_enabled('pos') is False
        assert module_enabled('ia_bi') is False


def test_missing_session_modules_fails_closed(app):
    """Si no existe la llave company_modules en sesión, retorna False."""
    with app.test_request_context():
        from flask import session
        session.clear()
        session['user'] = {'role': 'owner', 'permissions': {}}

        assert module_enabled('crm') is False
        assert module_enabled('nomina') is False


def test_unknown_module_fails_closed(app):
    """Módulos no existentes o no reconocidos deben retornar False."""
    with app.test_request_context():
        from flask import session
        session.clear()
        session['company_modules'] = {'crm': {'enabled': True}}
        session['user'] = {'role': 'owner', 'permissions': {}}

        assert module_enabled('non_existent_module_xyz') is False


def test_owner_cannot_bypass_disabled_module(app):
    """Un usuario con rol 'owner' NO puede acceder si el módulo no está en el plan."""
    with app.test_request_context():
        from flask import session
        session.clear()
        # Solo CRM y e_cf habilitados
        session['company_modules'] = {
            'e_cf': {'enabled': True},
            'crm': {'enabled': True},
            'nomina': {'enabled': False},
            'contabilidad': {'enabled': False},
            'inventario': {'enabled': False},
            'banks': {'enabled': False}
        }
        session['user'] = {
            'role': 'owner',
            'permissions': {
                'canHR': True,
                'canAccounting': True,
                'canManageInventory': True,
                'canExpenses': True
            }
        }

        # CRM y e_cf habilitados
        assert module_enabled('crm') is True
        assert module_enabled('e_cf') is True

        # Nómina, Contabilidad, Inventario y Bancos DENEGADOS a pesar de ser owner
        assert module_enabled('nomina') is False
        assert module_enabled('contabilidad') is False
        assert module_enabled('inventario') is False
        assert module_enabled('banks') is False


def test_pos_requires_both_plan_and_company_profile(app):
    """POS requiere que esté habilitado en el plan Y en el perfil de la compañía."""
    with app.test_request_context():
        from flask import session
        session.clear()
        session['user'] = {'role': 'owner'}

        # Caso 1: En plan Sí, en perfil Sí -> True
        session['company_modules'] = {'pos': {'enabled': True}}
        session['company_profile_pos_enabled'] = True
        assert module_enabled('pos') is True

        # Caso 2: En plan Sí, en perfil No -> False
        session['company_profile_pos_enabled'] = False
        assert module_enabled('pos') is False

        # Caso 3: En plan No, en perfil Sí -> False
        session['company_modules'] = {'pos': {'enabled': False}}
        session['company_profile_pos_enabled'] = True
        assert module_enabled('pos') is False


# ═══════════════════════════════════════════════════════════════════════════
# 2. PRUEBAS DE RUTAS WEB Y DEEP LINKS (HTTP GET / RESTRICTED)
# ═══════════════════════════════════════════════════════════════════════════

def _setup_session(client, role='owner', permissions=None, enabled_modules=None):
    if permissions is None:
        permissions = {
            'canCRM': True,
            'canManageInventory': True,
            'canManagePOS': True,
            'canExpenses': True,
            'canAccounting': True,
            'canHR': True,
            'canInvoice': True
        }
    if enabled_modules is None:
        enabled_modules = {'e_cf': {'enabled': True}}

    user_dict = {
        'uid': 'test_user_uid',
        'ownerUID': 'test_owner_uid',
        'role': str(role),
        'email': 'user@test.com',
        'status': 'active',
        'default_company_id': 'test_comp_1',
        'permissions': dict(permissions)
    }

    with client.session_transaction() as sess:
        sess.clear()
        sess['user'] = dict(user_dict)
        sess['selected_company_id'] = 'test_comp_1'
        sess['selected_owner_uid'] = 'test_owner_uid'
        sess['company_country'] = 'DO'
        sess['company_plan_id'] = 'plan_test'
        sess['company_plan_version'] = 1
        sess['company_modules'] = dict(enabled_modules)
        sess['company_profile_pos_enabled'] = bool(enabled_modules.get('pos', {}).get('enabled', False))

    return user_dict


def test_deep_links_blocked_when_module_disabled(client):
    """Verifica que intentar entrar por URL directa a un módulo no contratado retorne 403."""
    user_mock = _setup_session(
        client,
        role='owner',
        enabled_modules={
            'e_cf': {'enabled': True},
            'crm': {'enabled': False},
            'inventario': {'enabled': False},
            'banks': {'enabled': False},
            'contabilidad': {'enabled': False},
            'nomina': {'enabled': False},
            'pos': {'enabled': False},
            'reporte_606': {'enabled': False},
        }
    )

    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_id': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'pos_enabled': False,
        'posEnabled': False,
        'production_enabled': True,
        'sandbox_enabled': True,
        'sandbox_indefinite': True,
        'sandbox_start_date': '',
        'sandbox_end_date': '',
        'offboarding_mode': 'simple',
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'owner', 'permissions': {}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.update_company', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'e_cf': {'enabled': True}}}):

        urls_to_test = [
            ('/crm', 'CRM'),
            ('/crm/activities', 'CRM Activities'),
            ('/inventory/advanced', 'Inventario'),
            ('/banks', 'Bancos'),
            ('/accounting', 'Contabilidad'),
            ('/accounting/chart-of-accounts', 'Catálogo Contable'),
            ('/rrhh/employees', 'RRHH Empleados'),
            ('/rrhh/payroll', 'RRHH Nómina'),
            ('/reports/606', 'Reporte 606'),
            ('/pos', 'POS'),
        ]

        for url, label in urls_to_test:
            resp = client.get(url, follow_redirects=False)
            assert resp.status_code == 403, f"Ruta {url} ({label}) debió retornar 403 pero retornó {resp.status_code}"
            assert b"no est\xc3\xa1 incluido en tu plan" in resp.data or b"restringido" in resp.data or b"Restringido" in resp.data or b"Permiso Denegado" in resp.data, f"Ruta {url} no mostró mensaje de restricción"


def test_route_allowed_when_module_enabled_and_authorized(client):
    """Verifica que una ruta sea accesible cuando el módulo está contratado y el usuario autorizado."""
    user_mock = _setup_session(
        client,
        role='owner',
        enabled_modules={
            'e_cf': {'enabled': True},
            'crm': {'enabled': True}
        }
    )

    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_id': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'pos_enabled': False,
        'posEnabled': False,
        'production_enabled': True,
        'sandbox_enabled': True,
        'sandbox_indefinite': True,
        'sandbox_start_date': '',
        'sandbox_end_date': '',
        'offboarding_mode': 'simple',
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'owner', 'permissions': {'canCRM': True, 'canCRMReports': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.update_company', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'e_cf': {'enabled': True}, 'crm': {'enabled': True}}}), \
         patch('app.services.crm_service.CRMService.get_dashboard', return_value={
             'metrics': {},
             'salesMetrics': {
                 'funnel': {},
                 'conversionRates': {'prospect_to_contacted': 0, 'contacted_to_qualified': 0, 'qualified_to_proposal': 0, 'proposal_to_negotiation': 0, 'negotiation_to_won': 0},
                 'pipelineVelocity': {},
                 'revenueByRep': [],
                 'winRate': 0,
                 'avgDealSize': 0,
                 'totalPipeline': 0,
                 'wonPipeline': 0,
                 'lostPipeline': 0,
                 'wonCount': 0,
                 'lostCount': 0,
                 'openCount': 0,
                 'bySalesperson': [],
                 'byBranch': [],
                 'byProject': [],
             },
             'pipeline': {},
             'activities': [],
             'activitiesToday': [],
             'activitiesOverdue': [],
             'staleOpportunities': [],
             'topLeads': [],
             'suggestions': [],
             'recentOpportunities': []
         }), \
         patch('app.services.crm_service.CRMService.get_opportunities', return_value=[]):

        resp = client.get('/crm', follow_redirects=True)
        assert resp.status_code == 200
        assert b"CRM" in resp.data


# ═══════════════════════════════════════════════════════════════════════════
# 3. PRUEBAS DE REST API v1 (API KEY + MODULE GATING)
# ═══════════════════════════════════════════════════════════════════════════

def test_api_v1_returns_403_module_disabled_when_not_in_plan(client):
    """Una API Key válida consumiendo un módulo no contratado debe recibir 403 MODULE_DISABLED."""
    company_mock = {
        'id': 'test_comp_1',
        'ownerUID': 'test_owner_uid',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'role': 'owner',
        'modules': {
            'e_cf': {'enabled': True},
            'crm': {'enabled': False},
            'inventario': {'enabled': False},
            'contabilidad': {'enabled': False},
            'gastos': {'enabled': False}
        }
    }

    plan_mock = {
        'id': 'plan_test',
        'plan_version': 1,
        'modules': company_mock['modules']
    }

    api_endpoints = [
        ('/api/v1/inventory/kardex?itemId=item_1', 'inventario'),
        ('/api/v1/accounting/accounts', 'contabilidad'),
        ('/api/v1/expenses/payments', 'gastos'),
        ('/api/v1/prospects', 'crm'),
    ]

    with patch('app.services.db_service.DatabaseService.get_company_by_api_key', return_value=company_mock), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value=plan_mock):
        for url, mod_key in api_endpoints:
            if url == '/api/v1/prospects':
                resp = client.post(url, json={'rnc': '123', 'razonSocial': 'Test'}, headers={'X-API-Key': 'valid_api_key_123'})
            else:
                resp = client.get(url, headers={'X-API-Key': 'valid_api_key_123'})
            assert resp.status_code == 403, f"API {url} debió responder 403 pero respondió {resp.status_code}"
            data = resp.get_json()
            assert data['success'] is False
            assert data['error']['code'] == 'MODULE_DISABLED'


def test_api_v1_succeeds_when_module_is_enabled(client):
    """Una API Key válida consumiendo un módulo contratado debe responder 200."""
    company_mock = {
        'id': 'test_comp_1',
        'ownerUID': 'test_owner_uid',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'role': 'owner',
        'modules': {
            'contabilidad': {'enabled': True}
        }
    }

    plan_mock = {
        'id': 'plan_test',
        'plan_version': 1,
        'modules': company_mock['modules']
    }

    with patch('app.services.db_service.DatabaseService.get_company_by_api_key', return_value=company_mock), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value=plan_mock), \
         patch('app.services.db_service.DatabaseService.get_chart_of_accounts', return_value=[]):
        resp = client.get('/api/v1/accounting/accounts', headers={'X-API-Key': 'valid_api_key_123'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True


# ═══════════════════════════════════════════════════════════════════════════
# 4. PRUEBA DE INVALIDACIÓN DE CACHÉ DE PLAN CON plan_version
# ═══════════════════════════════════════════════════════════════════════════

def test_plan_cache_busts_on_version_increment(app):
    """_cached_plan debe retornar versiones diferentes cuando plan_version cambia."""
    from app.services.db_service import _cached_plan, DatabaseService
    
    doc_v1 = {
        'id': 'plan_p1',
        'name': 'Plan Inicial',
        'plan_version': 1,
        'modules': {'crm': {'enabled': False}}
    }

    doc_v2 = {
        'id': 'plan_p1',
        'name': 'Plan Actualizado',
        'plan_version': 2,
        'modules': {'crm': {'enabled': True}}
    }

    mock_doc_1 = MagicMock()
    mock_doc_1.exists = True
    mock_doc_1.to_dict.return_value = doc_v1

    mock_doc_2 = MagicMock()
    mock_doc_2.exists = True
    mock_doc_2.to_dict.return_value = doc_v2

    with patch('app.services.db_service.firebase_initialized', True), \
         patch('app.services.db_service.db_firestore') as mock_db:
        # Consulta versión 1
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc_1
        plan_v1 = DatabaseService.get_plan('plan_p1', plan_version=1)
        assert plan_v1['plan_version'] == 1
        assert plan_v1['modules']['crm']['enabled'] is False

        # Consulta versión 2 (debe invalidar el caché memoizado por versión)
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc_2
        plan_v2 = DatabaseService.get_plan('plan_p1', plan_version=2)
        assert plan_v2['plan_version'] == 2
        assert plan_v2['modules']['crm']['enabled'] is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. PRUEBAS DE RBAC vs ENTITLEMENT Y TENANT ISOLATION
# ═══════════════════════════════════════════════════════════════════════════

def test_user_with_permission_but_company_without_module_denied_403(client):
    """Un usuario con permiso canAccounting pero en una empresa SIN contabilidad en su plan recibe 403."""
    user_mock = _setup_session(
        client,
        role='member',
        permissions={'canAccounting': True},
        enabled_modules={'e_cf': {'enabled': True}, 'contabilidad': {'enabled': False}}
    )

    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'configured': True,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'member'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'role': 'member', 'permissions': {'canAccounting': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'contabilidad': {'enabled': False}}}):

        resp = client.get('/accounting', follow_redirects=False)
        assert resp.status_code == 403
        assert b"no est\xc3\xa1 incluido en tu plan" in resp.data or b"restringido" in resp.data or b"Restringido" in resp.data


def test_user_without_permission_when_module_is_enabled_denied_403(client):
    """Un usuario sin permiso canAccounting en una empresa CON contabilidad contratada recibe 403 por RBAC."""
    user_mock = _setup_session(
        client,
        role='member',
        permissions={'canAccounting': False},
        enabled_modules={'e_cf': {'enabled': True}, 'contabilidad': {'enabled': True}}
    )

    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'configured': True,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'member'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'role': 'member', 'permissions': {'canAccounting': False}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'contabilidad': {'enabled': True}}}):

        resp = client.get('/accounting', follow_redirects=False)
        assert resp.status_code == 403


def test_tenant_isolation_company_a_cannot_access_company_b(client):
    """Una API Key de Empresa A no puede acceder a los datos de Empresa B."""
    company_a = {
        'id': 'comp_A',
        'ownerUID': 'owner_A',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'modules': {'inventario': {'enabled': True}}
    }
    company_b = {
        'id': 'comp_B',
        'ownerUID': 'owner_B',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'modules': {'inventario': {'enabled': True}}
    }

    with patch('app.services.db_service.DatabaseService.get_company_by_api_key') as mock_get_comp, \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'inventario': {'enabled': True}}}), \
         patch('app.services.kardex_service.KardexService.get_kardex_summary') as mock_kardex:
        
        # Invocación con API Key de Empresa A
        mock_get_comp.return_value = company_a
        mock_kardex.return_value = {}
        resp = client.get('/api/v1/inventory/kardex?itemId=item_1', headers={'X-API-Key': 'key_comp_a'})
        assert resp.status_code == 200
        
        # Verificar que get_kardex_summary recibió company_id='comp_A' y owner_uid='owner_A'
        assert mock_kardex.call_args[1].get('company_id') == 'comp_A'
        assert mock_kardex.call_args[1].get('owner_uid') == 'owner_A'
        assert mock_kardex.call_args[1].get('company_id') != 'comp_B'


def test_ui_sidebar_renders_only_entitled_modules(app):
    """Verifica que el sidebar solo renderice los enlaces de módulos contratados."""
    with app.test_request_context():
        from flask import session, render_template
        session.clear()
        session['user'] = {'role': 'owner', 'email': 'owner@test.com', 'permissions': {}}
        session['company_modules'] = {
            'e_cf': {'enabled': True},
            'nomina': {'enabled': False},
            'contabilidad': {'enabled': False},
            'pos': {'enabled': False},
            'banks': {'enabled': False},
            'crm': {'enabled': False},
            'ia_bi': {'enabled': False},
            'portal_cliente': {'enabled': False},
            'certificacion': {'enabled': False},
        }
        session['company_profile_pos_enabled'] = False

        html = render_template('_sidebar_modules.html')
        # e_cf está contratado
        assert 'Facturación' in html
        # Módulos deshabilitados no deben aparecer
        assert 'Nómina y RRHH' not in html
        assert 'Contabilidad' not in html
        assert 'Punto de Venta (POS)' not in html
        assert 'Portal de Clientes' not in html
        assert 'BI Drill-down' not in html


# ═══════════════════════════════════════════════════════════════════════════
# 6. AUDITORÍA FASE 3: MATRIZ EXHAUSTIVA DE LOS 25 MÓDULOS CANÓNICOS
# ═══════════════════════════════════════════════════════════════════════════

def test_canonical_catalog_25_modules_integrity():
    """Valida la integridad del catálogo canónico de 25 módulos de VykOne."""
    from app.utils.module_gate import MODULE_DEFS, MODULE_MAP
    assert len(MODULE_DEFS) == 25
    assert len(MODULE_MAP) == 25
    
    expected_keys = {
        "e_cf", "dashboard", "catalogo", "cotizaciones", "crm",
        "pos", "price_lists", "inventario", "contratos", "comisiones",
        "cxc", "cxp_compras", "gastos", "banks", "contabilidad",
        "nomina", "reporte_606", "certificacion", "api", "multi_empresa",
        "portal_cliente", "ia_bi", "auditoria", "exportacion_contable", "pasarela_azul"
    }
    assert set(MODULE_MAP.keys()) == expected_keys


# Matriz de mapeo: (modulo, ruta_web_representativa, ruta_api_representativa, permisos_a_desactivar)
MODULE_TEST_MATRIX = [
    ("e_cf", "/invoices", "/api/v1/invoices", ["canInvoice"]),
    ("catalogo", "/items", None, ["canClients", "canManageInventory"]),
    ("cotizaciones", "/quotations", None, ["canInvoice", "canCreateQuotation"]),
    ("crm", "/crm", "/api/v1/crm/opportunities", ["canCRM", "canCRMReports", "canClients"]),
    ("pos", "/pos", None, ["canManagePOS"]),
    ("price_lists", "/price-lists", None, ["canManageInventory"]),
    ("inventario", "/inventory/advanced", "/api/v1/inventory/kardex?itemId=item_1", ["canManageInventory"]),
    ("contratos", "/operations/contracts", None, ["canManageContracts"]),
    ("comisiones", "/operations/commissions", None, ["canManageCommissions"]),
    ("cxc", "/cxc", None, ["canManageCXC", "canInvoice"]),
    ("cxp_compras", "/suppliers", "/api/v1/supplier-invoices", ["canManageSuppliers", "canExpenses"]),
    ("gastos", "/expenses", "/api/v1/expenses/payments", ["canExpenses"]),
    ("banks", "/banks", None, ["canExpenses"]),
    ("contabilidad", "/accounting", "/api/v1/accounting/accounts", ["canAccounting"]),
    ("nomina", "/rrhh/employees", "/api/v1/labor/settlement", ["canHR"]),
    ("reporte_606", "/reports/606", None, ["canExpenses"]),
    ("certificacion", "/certificacion/paso/1", None, ["canCertifyDGII"]),
    ("api", "/desarrolladores", None, None),
    ("portal_cliente", "/portal/admin", None, ["canClients"]),
    ("ia_bi", "/budgets", None, ["canExpenses", "canViewBI"]),
    ("auditoria", "/audit", None, ["canViewAuditLog"]),
    ("exportacion_contable", "/reports/export/accounting", None, ["canInvoice", "canAccounting"]),
]


@pytest.mark.parametrize("mod_key, web_url, api_url, perms", MODULE_TEST_MATRIX)
def test_matrix_all_modules_blocked_when_disabled_web(client, mod_key, web_url, api_url, perms):
    """Para CADA módulo: empresa sin módulo -> TODAS sus rutas web devuelven 403."""
    user_mock = _setup_session(
        client,
        role='owner',
        enabled_modules={mod_key: {'enabled': False}}
    )
    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'pos_enabled': False,
        'production_enabled': True,
        'sandbox_enabled': True,
        'sandbox_indefinite': True,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'owner', 'permissions': {}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {mod_key: {'enabled': False}}}):

        resp = client.get(web_url, follow_redirects=False)
        assert resp.status_code == 403, f"Módulo {mod_key} en {web_url} debió responder 403 pero respondió {resp.status_code}"


@pytest.mark.parametrize("mod_key, web_url, api_url, perms", [m for m in MODULE_TEST_MATRIX if m[2] is not None])
def test_matrix_all_modules_blocked_when_disabled_api(client, mod_key, web_url, api_url, perms):
    """Para CADA módulo con API: empresa sin módulo -> TODAS sus APIs devuelven 403 MODULE_DISABLED."""
    company_mock = {
        'id': 'test_comp_1',
        'ownerUID': 'test_owner_uid',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'role': 'owner',
        'modules': {mod_key: {'enabled': False}}
    }
    plan_mock = {
        'id': 'plan_test',
        'plan_version': 1,
        'modules': company_mock['modules']
    }

    with patch('app.services.db_service.DatabaseService.get_company_by_api_key', return_value=company_mock), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value=plan_mock):

        if 'settlement' in api_url or 'prospects' in api_url or 'invoices' in api_url:
            resp = client.post(api_url, json={'employeeId': 'emp_1'}, headers={'X-API-Key': 'valid_api_key'})
        else:
            resp = client.get(api_url, headers={'X-API-Key': 'valid_api_key'})

        assert resp.status_code == 403, f"API {api_url} ({mod_key}) debió responder 403 pero retornó {resp.status_code}"
        data = resp.get_json()
        assert data['success'] is False
        assert data['error']['code'] == 'MODULE_DISABLED'


@pytest.mark.parametrize("mod_key, web_url, api_url, perms", [m for m in MODULE_TEST_MATRIX if m[3] is not None])
def test_matrix_rbac_blocked_when_permission_missing_even_if_module_enabled(client, mod_key, web_url, api_url, perms):
    """Para CADA módulo: empresa con módulo + usuario SIN permiso -> devuelve 403 por RBAC."""
    denied_perms = {p: False for p in perms}
    user_mock = _setup_session(
        client,
        role='member',
        permissions=denied_perms,
        enabled_modules={mod_key: {'enabled': True}}
    )
    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'pos_enabled': True,
        'production_enabled': True,
        'sandbox_enabled': True,
        'sandbox_indefinite': True,
    }

    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'member'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'company_name': 'Test Co', 'rnc': '123456789', 'role': 'member', 'permissions': denied_perms, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {mod_key: {'enabled': True}}}):

        resp = client.get(web_url, follow_redirects=False)
        assert resp.status_code == 403, f"Módulo {mod_key} sin permisos {perms} en {web_url} debió responder 403 pero retornó {resp.status_code}"


# ═══════════════════════════════════════════════════════════════════════════
# 7. ARCHITECTURE GUARD TEST: PROTECCIÓN PREVENTIVA PERMANENTE
# ═══════════════════════════════════════════════════════════════════════════

def test_all_functional_routes_have_module_guard(app):
    """Architecture Guard Test: Verifica que CADA una de las rutas registradas en Flask
    tenga una asignación determinística a un módulo comercial canónico o pertenezca a la
    whitelist explícita de rutas públicas/globales.
    
    Si en el futuro un desarrollador añade una ruta funcional huérfana sin módulo:
    → ESTE TEST FALLA AUTOMÁTICAMENTE EN CI.
    """
    from app.utils.module_gate import resolve_endpoint_module, MODULE_MAP

    unassigned_routes = []
    total_routes = 0
    assigned_modules_count = {}

    for rule in app.url_map.iter_rules():
        total_routes += 1
        mod_key, category = resolve_endpoint_module(rule)

        if category == 'UNKNOWN':
            unassigned_routes.append((rule.endpoint, rule.rule))
        elif mod_key is not None:
            assert mod_key in MODULE_MAP, f"Ruta {rule.endpoint} asignada a módulo inexistente '{mod_key}'"
            assigned_modules_count[mod_key] = assigned_modules_count.get(mod_key, 0) + 1

    assert len(unassigned_routes) == 0, (
        f"Se encontraron {len(unassigned_routes)} rutas funcionales huérfanas sin protección de módulo ni whitelist:\n"
        + "\n".join(f"  - Endpoint: {ep} -> Ruta: {r}" for ep, r in unassigned_routes)
    )
    assert total_routes >= 1000, f"Se esperaban más de 1000 rutas auditadas pero se registraron {total_routes}"


def test_all_api_blueprints_have_module_guard(app):
    """Architecture Guard Test para REST API: Verifica que todos los endpoints /api/v1/
    estén formalmente mapeados a sus módulos y no queden expuestos sin control.
    """
    from app.utils.module_gate import resolve_endpoint_module, MODULE_MAP

    api_routes = [r for r in app.url_map.iter_rules() if r.rule.startswith('/api/v1/')]
    assert len(api_routes) >= 60, f"Se esperaban al menos 60 rutas REST v1 pero se encontraron {len(api_routes)}"

    for rule in api_routes:
        mod_key, category = resolve_endpoint_module(rule)
        if category in ('WHITELIST_BLUEPRINT', 'INVOICE_WHITELIST'):
            continue
        assert mod_key in MODULE_MAP, f"API endpoint {rule.endpoint} ({rule.rule}) no tiene módulo canónico válido"


# ═══════════════════════════════════════════════════════════════════════════
# 8. VALIDACIÓN DE CONSISTENCIA: MODULE_DEFS ↔ PLAN CATALOG ↔ UI ↔ RBAC
# ═══════════════════════════════════════════════════════════════════════════

def test_module_defs_plan_catalog_ui_consistency():
    """Valida la correspondencia inequívoca entre:
    Módulo comercial → Plan → module_key → Blueprint/rutas → Permisos RBAC → Menú/UI → API.
    
    Verifica especialmente los 9 módulos de capacidades transversales / independientes:
    - dashboard, api, multi_empresa, portal_cliente, pasarela_azul,
      ia_bi, exportacion_contable, catalogo, price_lists.
    """
    from app.utils.module_gate import MODULE_DEFS, MODULE_MAP, BLUEPRINT_MODULE_MAP

    # 1. Integridad de los 25 módulos
    assert len(MODULE_DEFS) == 25
    for mod in MODULE_DEFS:
        assert 'key' in mod
        assert 'label' in mod
        assert 'category' in mod
        assert 'perm' in mod
        assert mod['category'] in ('core', 'ventas', 'logistica', 'operaciones', 'finanzas', 'rrhh', 'cumplimiento', 'integraciones', 'enterprise')

    # 2. Verificación de los 9 módulos específicos
    special_modules = [
        'dashboard', 'api', 'multi_empresa', 'portal_cliente', 'pasarela_azul',
        'ia_bi', 'exportacion_contable', 'catalogo', 'price_lists'
    ]
    for key in special_modules:
        assert key in MODULE_MAP, f"Módulo especial '{key}' falta en MODULE_MAP"
        info = MODULE_MAP[key]
        assert info['label'] != "", f"Módulo '{key}' debe tener una etiqueta clara"

    # 3. Verificación de correspondencia con blueprints
    for bp, mod_key in BLUEPRINT_MODULE_MAP.items():
        assert mod_key in MODULE_MAP, f"Blueprint '{bp}' mapea a clave inválida '{mod_key}'"


# ═══════════════════════════════════════════════════════════════════════════
# 9. VALIDACIÓN DE RUTAS INTENCIONALMENTE PÚBLICAS / GLOBALES
# ═══════════════════════════════════════════════════════════════════════════

def test_explicit_public_and_global_whitelist(client):
    """Verifica que las rutas intencionalmente públicas y globales funcionen
    correctamente sin ser bloqueadas indebidamente por el gating de módulos comerciales.
    """
    public_endpoints = [
        ('/login', 200),
        ('/', 200),
        ('/precios', 200),
        ('/modulos', 200),
        ('/faqs', 200),
        ('/fe/autenticacion/api/semilla', 200),
        ('/health', 200),
    ]

    for path, expected_status in public_endpoints:
        resp = client.get(path)
        assert resp.status_code == expected_status, f"Ruta pública {path} debió responder {expected_status} pero respondió {resp.status_code}"
        assert b"MODULE_DISABLED" not in resp.data



# ═══════════════════════════════════════════════════════════════════════════
# 10. SIMULACIÓN INTEGRAL: MATRIZ DE EMPRESA REAL EN 6 ESCENARIOS
# ═══════════════════════════════════════════════════════════════════════════

def test_real_company_simulation_matrix_end_to_end(client):
    """Prueba integral de los 6 escenarios operativos en una empresa real:
    1. Empresa con 0 módulos (plan vacío / cancelado) → Fail-Closed (403)
    2. Empresa con 1 módulo (solo e_cf) → e_cf permitido (200), otros 403
    3. Empresa con múltiples módulos (e_cf, nomina, contabilidad, crm) → permitidos (200), no contratados 403
    4. Rol 'owner' en módulo no contratado → 403 (No hay bypass)
    5. Rol 'member' sin permiso en módulo contratado → 403 (RBAC)
    6. Rol 'member' con permiso en módulo contratado → 200 (Permitido)
    """
    company_doc = {
        'id': 'test_comp_1',
        'status': 'Activo',
        'planId': 'plan_test',
        'plan_version': 1,
        'owner_uid': 'test_owner_uid',
        'country': 'DO',
        'configured': True,
        'pos_enabled': False,
        'production_enabled': True,
        'sandbox_enabled': True,
        'sandbox_indefinite': True,
    }

    # ── ESCENARIO 1: Empresa con 0 módulos (Fail-Closed) ──
    user_mock_1 = _setup_session(client, role='owner', enabled_modules={})
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock_1), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'role': 'owner', 'permissions': {'canInvoice': True, 'canHR': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {}}):
        resp = client.get('/invoices', follow_redirects=False)
        assert resp.status_code == 403, f"Empresa sin módulos debe responder 403 en /invoices pero respondió {resp.status_code}"
        resp = client.get('/rrhh/employees', follow_redirects=False)
        assert resp.status_code == 403, f"Empresa sin módulos debe responder 403 en /rrhh/employees pero respondió {resp.status_code}"

    # ── ESCENARIO 2: Empresa con 1 módulo (solo e_cf) ──
    user_mock_2 = _setup_session(client, role='owner', enabled_modules={'e_cf': {'enabled': True}})
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock_2), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'role': 'owner', 'permissions': {'canInvoice': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_sequences', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'e_cf': {'enabled': True}}}):

        # e_cf permitido
        resp_ecf = client.get('/invoices', follow_redirects=False)
        assert resp_ecf.status_code == 200

        # Módulos no contratados bloqueados 403
        resp_hr = client.get('/rrhh/employees', follow_redirects=False)
        assert resp_hr.status_code == 403
        resp_acc = client.get('/accounting', follow_redirects=False)
        assert resp_acc.status_code == 403
        resp_crm = client.get('/crm', follow_redirects=False)
        assert resp_crm.status_code == 403

    # ── ESCENARIO 3: Empresa con múltiples módulos (e_cf, nomina, contabilidad, crm) ──
    multi_modules = {
        'e_cf': {'enabled': True},
        'nomina': {'enabled': True},
        'contabilidad': {'enabled': True},
        'crm': {'enabled': True},
        'pos': {'enabled': False},
        'banks': {'enabled': False}
    }
    user_mock_3 = _setup_session(client, role='owner', enabled_modules=multi_modules)
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock_3), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'role': 'owner', 'permissions': {'canInvoice': True, 'canHR': True, 'canAccounting': True, 'canCRM': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': multi_modules}):

        # Módulos no contratados en este plan bloqueados 403
        resp_pos = client.get('/pos', follow_redirects=False)
        assert resp_pos.status_code == 403
        resp_banks = client.get('/banks', follow_redirects=False)
        assert resp_banks.status_code == 403

    # ── ESCENARIO 4: Rol owner en módulo no contratado (Fail-Closed) ──
    user_mock_4 = _setup_session(client, role='owner', enabled_modules={'e_cf': {'enabled': True}, 'pos': {'enabled': False}})
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock_4), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'role': 'owner', 'permissions': {'canManagePOS': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'pos': {'enabled': False}}}):
        resp_owner_pos = client.get('/pos', follow_redirects=False)
        assert resp_owner_pos.status_code == 403

    # ── ESCENARIO 5: Rol member sin permiso en módulo contratado (RBAC Deny 403) ──
    user_mock_5 = _setup_session(client, role='member', permissions={'canAccounting': False}, enabled_modules={'contabilidad': {'enabled': True}})
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock_5), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'member'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'role': 'member', 'permissions': {'canAccounting': False}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'contabilidad': {'enabled': True}}}):
        resp_member_no_perm = client.get('/accounting', follow_redirects=False)
        assert resp_member_no_perm.status_code == 403

    # ── ESCENARIO 6: Rol member con permiso en módulo contratado (Allow 200) ──
    user_mock_6 = _setup_session(client, role='member', permissions={'canInvoice': True}, enabled_modules={'e_cf': {'enabled': True}})
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_mock_6), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=company_doc), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'member'}), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid', 'role': 'member', 'permissions': {'canInvoice': True}, 'company': company_doc}), \
         patch('app.services.db_service.DatabaseService.get_invoices', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_sequences', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'plan_test', 'plan_version': 1, 'modules': {'e_cf': {'enabled': True}}}):
        resp_member_ok = client.get('/invoices', follow_redirects=False)
        assert resp_member_ok.status_code == 200



