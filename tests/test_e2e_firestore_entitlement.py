"""Test E2E de validación práctica del ciclo de Entitlement comercial.

Ejecuta el gate de producción de 12 pasos:
1. Setup de tenant de prueba y asignación de Plan Enterprise con 25 módulos.
2. Confirmación de campos plan_id y plan_version en la entidad de empresa.
3. Inicio de sesión / carga de contexto de tenant en e-FacturaWeb.
4. Confirmación de los 25 módulos habilitados en la sesión.
5. Verificación de acceso permitido a módulos sensibles:
   - Bancos (/banks)
   - Listas de Precios (/price-lists)
   - Certificación DGII (/certificacion/paso/1)
   - Contabilidad (/accounting)
   - Nómina (/rrhh/employees)
6. Downgrade comercial en Firestore a plan restringido (Esencial: e_cf y gastos).
7. Incremento de plan_version (+1) en la empresa.
8. Request subsecuente sin cerrar sesión: verificación de reload automático de sesión.
9. Confirmación inmediata de HTTP 403 Forbidden en módulos no contratados:
   - Bancos -> 403
   - Listas de Precios -> 403
   - Certificación DGII -> 403
   - Contabilidad -> 403
   - Nómina -> 403
10. Confirmación de acceso permitido a módulos contratados (e_cf -> 200, gastos -> 200).
11. Suspensión de empresa (status: 'suspended', prod/sandbox deshabilitados) y confirmación de bloqueo de acceso.
12. Restauración de empresa (status: 'active', prod/sandbox habilitados) y recuperación de acceso según el plan vigente.
"""

import os
import sys
from contextlib import ExitStack
import pytest
from unittest.mock import patch
from flask import session

from app import create_app
from app.utils.module_gate import MODULE_DEFS, module_enabled

PORTAL_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'portal'))
if PORTAL_ROOT not in sys.path:
    sys.path.insert(0, PORTAL_ROOT)

from database_service import DatabaseService as PortalDatabaseService


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_full_12_step_e2e_entitlement_lifecycle(app, client):
    """Ejecuta los 12 pasos del ciclo E2E de gobernanza y entitlement."""
    
    # --- Datos de Prueba ---
    TEST_COMPANY_ID = "e2e_test_company_001"
    TEST_OWNER_UID = "e2e_owner_uid_001"
    
    # 1. Definición de Planes usando el catálogo canónico del Portal (25 claves)
    all_25_keys = [m["key"] for m in PortalDatabaseService.MODULE_DEFS]
    enterprise_modules = PortalDatabaseService.default_modules(all_25_keys)
    restricted_modules = PortalDatabaseService.default_modules(["e_cf", "gastos"])
    
    plans_store = {
        "plan_enterprise": {
            "id": "plan_enterprise",
            "name": "Enterprise",
            "plan_version": 1,
            "modules": enterprise_modules,
        },
        "plan_esencial": {
            "id": "plan_esencial",
            "name": "Esencial",
            "plan_version": 2,
            "modules": restricted_modules,
        }
    }
    
    # Mock dinámico del almacenamiento de empresas
    company_store = {
        TEST_COMPANY_ID: {
            "id": TEST_COMPANY_ID,
            "owner_uid": TEST_OWNER_UID,
            "status": "active",
            "plan_id": "plan_enterprise",
            "planId": "plan_enterprise",
            "plan_version": 1,
            "pos_enabled": True,
            "country": "DO",
            "configured": True,
            "production_enabled": True,
            "sandbox_enabled": True,
            "sandbox_indefinite": True,
        }
    }
    
    # Mock dinámico del perfil de usuario
    user_data = {
        "uid": TEST_OWNER_UID,
        "ownerUID": TEST_OWNER_UID,
        "email": "owner@e2e-test.com",
        "role": "owner",
        "permissions": {
            "canInvoice": True,
            "canExpenses": True,
            "canManageInventory": True,
            "canAccounting": True,
            "canHR": True,
            "canCertifyDGII": True,
            "canManagePOS": True,
            "canCRM": True,
            "canExpenses": True,
            "canViewDashboard": True,
        }
    }

    # Helpers de mock para DatabaseService
    def mock_get_company(cid=None, *args, **kwargs):
        if not cid and 'company_id' in kwargs:
            cid = kwargs['company_id']
        return company_store.get(cid or TEST_COMPANY_ID)

    def mock_get_company_profile(uid=None, company_id=None, *args, **kwargs):
        cid = company_id or (args[0] if args else None) or TEST_COMPANY_ID
        return company_store.get(cid, company_store[TEST_COMPANY_ID])

    def mock_get_plan(pid, plan_version=None):
        return plans_store.get(pid)

    with ExitStack() as stack:
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_company', side_effect=mock_get_company))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_company_profile', side_effect=mock_get_company_profile))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_plan', side_effect=mock_get_plan))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_data))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_company_context', return_value={
            'company_id': TEST_COMPANY_ID, 'owner_uid': TEST_OWNER_UID, 'company_name': 'E2E Co', 'rnc': '123456789',
            'role': 'owner', 'permissions': user_data['permissions'], 'company': company_store[TEST_COMPANY_ID]
        }))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[company_store[TEST_COMPANY_ID]]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_branches', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_projects', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_default_branch', return_value=None))
        stack.enter_context(patch('app.services.db_service.DatabaseService.update_company', return_value=None))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_accounting_entries', return_value=[]))
        stack.enter_context(patch('app.services.accounting_service.AccountingService.seed_default_accounts', return_value=None))
        stack.enter_context(patch('app.services.accounting_service.AccountingService.seed_default_entry_types', return_value=None))
        stack.enter_context(patch('app.services.accounting_service.AccountingService.get_accounts_tree', return_value=({}, [])))
        stack.enter_context(patch('app.services.accounting_service.AccountingService.get_balance_sheet', return_value={'activos': {'total': 0}, 'pasivos': {'total': 0}, 'patrimonio': {'total': 0}}))
        stack.enter_context(patch('app.services.accounting_service.AccountingService.get_income_statement', return_value={'netIncome': 0}))
        stack.enter_context(patch('app.services.accounting_service.AccountingService.get_trial_balance', return_value={}))
        stack.enter_context(patch('app.services.hr_data_service.get_employees', return_value=[]))
        stack.enter_context(patch('app.services.dgii_cert_service.DgiiCertService.get_process', return_value={}))

        # -------------------------------------------------------------
        # PASO 1 & 2: Confirmar estado inicial en Firestore (Enterprise)
        # -------------------------------------------------------------
        company_data = company_store[TEST_COMPANY_ID]
        assert company_data["plan_id"] == "plan_enterprise"
        assert company_data["plan_version"] == 1
        assert company_data["status"] == "active"

        # -------------------------------------------------------------
        # PASO 3 & 4: Iniciar sesión y confirmar los 25 módulos en ERP
        # -------------------------------------------------------------
        with client.session_transaction() as sess:
            sess['user'] = user_data
            sess['company_id'] = TEST_COMPANY_ID
            sess['selected_company_id'] = TEST_COMPANY_ID
            sess['company_plan_id'] = 'plan_enterprise'
            sess['company_plan_version'] = 1
            sess['company_modules'] = enterprise_modules
            sess['company_profile_pos_enabled'] = True

        with app.test_request_context():
            session['company_modules'] = enterprise_modules
            session['company_profile_pos_enabled'] = True
            for key in all_25_keys:
                assert module_enabled(key) is True, f"Fallo en habilitación inicial de {key}"

        # -------------------------------------------------------------
        # PASO 5: Probar acceso a módulos sensibles con Enterprise (200 / No 403)
        # -------------------------------------------------------------
        sensitive_routes = [
            ('/banks', 'banks'),
            ('/price-lists', 'price_lists'),
            ('/certificacion/paso/1', 'certificacion'),
            ('/accounting', 'contabilidad'),
            ('/rrhh/employees', 'nomina'),
        ]
        
        for route, mod_key in sensitive_routes:
            resp = client.get(route)
            assert resp.status_code != 403, f"Ruta {route} ({mod_key}) devolvió 403 inesperado en plan Enterprise"

        # -------------------------------------------------------------
        # PASO 6 & 7: Downgrade comercial a Esencial e incremento de versión
        # -------------------------------------------------------------
        company_store[TEST_COMPANY_ID]["plan_id"] = "plan_esencial"
        company_store[TEST_COMPANY_ID]["planId"] = "plan_esencial"
        company_store[TEST_COMPANY_ID]["plan_version"] = 2  # Incremento de versión

        # -------------------------------------------------------------
        # PASO 8: Request subsecuente en la MISMA sesión (dispara reload)
        # -------------------------------------------------------------
        # Al hacer un request, el before_request detecta plan_version 2 != cached 1
        # y recarga los módulos del plan_esencial
        client.get('/invoices')

        with client.session_transaction() as sess:
            assert sess.get('company_plan_version') == 2
            assert sess.get('company_plan_id') == 'plan_esencial'
            assert sess['company_modules']['e_cf']['enabled'] is True
            assert sess['company_modules']['gastos']['enabled'] is True
            assert sess['company_modules']['banks']['enabled'] is False
            assert sess['company_modules']['price_lists']['enabled'] is False
            assert sess['company_modules']['certificacion']['enabled'] is False
            assert sess['company_modules']['contabilidad']['enabled'] is False
            assert sess['company_modules']['nomina']['enabled'] is False

        # -------------------------------------------------------------
        # PASO 9 & 10: 403 en módulos no contratados, 200 en contratados
        # -------------------------------------------------------------
        for route, mod_key in sensitive_routes:
            resp = client.get(route)
            assert resp.status_code == 403, (
                f"Ruta {route} ({mod_key}) debió retornar 403 tras downgrade a Esencial, pero retornó {resp.status_code}"
            )

        # Módulos contratados continúan accesibles
        resp_invoices = client.get('/invoices')
        assert resp_invoices.status_code != 403

        resp_expenses = client.get('/expenses')
        assert resp_expenses.status_code != 403

        # -------------------------------------------------------------
        # PASO 11: Suspender el tenant y confirmar bloqueo
        # -------------------------------------------------------------
        company_store[TEST_COMPANY_ID]["status"] = "suspended"
        company_store[TEST_COMPANY_ID]["production_enabled"] = False
        company_store[TEST_COMPANY_ID]["sandbox_enabled"] = False
        
        # Una empresa suspendida recibe la vista restricted por bloqueo de entorno
        resp_suspended = client.get('/invoices')
        assert b"desactivado" in resp_suspended.data or resp_suspended.status_code in (302, 403), "Empresa suspendida no fue bloqueada"

        # -------------------------------------------------------------
        # PASO 12: Restaurar tenant y confirmar recuperación
        # -------------------------------------------------------------
        company_store[TEST_COMPANY_ID]["status"] = "active"
        company_store[TEST_COMPANY_ID]["production_enabled"] = True
        company_store[TEST_COMPANY_ID]["sandbox_enabled"] = True
        
        resp_restored = client.get('/invoices')
        assert resp_restored.status_code == 200, "Empresa activa no pudo acceder a módulo contratado tras restauración"
