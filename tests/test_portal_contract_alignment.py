"""Test de integración y alineación de contrato entre e-FacturaWeb y el Portal Administrativo.

Verifica de forma estricta:
1. e-FacturaWeb y Portal definen exactamente las mismas 25 claves canónicas (1:1).
2. Las categorías de módulos coinciden entre ambos sistemas.
3. No existen aliases ni nombres no canónicos en ningún repositorio.
4. Un plan generado por el Portal (Enterprise) habilita los 25 módulos en el motor de e-FacturaWeb.
5. Los planes restringidos (Esencial, Pro) aplican fail-closed en e-FacturaWeb para los módulos no contratados.
"""

import os
import sys
import pytest
from flask import Flask, session

from app.utils.module_gate import MODULE_DEFS as ERP_MODULE_DEFS, module_enabled, MODULE_MAP

# Importar DatabaseService del Portal
PORTAL_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'portal'))
if PORTAL_ROOT not in sys.path:
    sys.path.insert(0, PORTAL_ROOT)

from database_service import DatabaseService as PortalDatabaseService

PROHIBITED_ALIASES = {
    "rh",
    "facturacion",
    "accounting",
    "sales",
    "billing",
    "inventory",
    "payroll",
    "recursos_humanos",
    "cuentas_por_cobrar",
    "cuentas_por_pagar",
}


def test_catalogue_exact_25_keys_1_to_1():
    """e-FacturaWeb y Portal Administrativo deben tener exactamente 25 claves canónicas 1:1."""
    erp_keys = [m["key"] for m in ERP_MODULE_DEFS]
    portal_keys = [m["key"] for m in PortalDatabaseService.MODULE_DEFS]

    assert len(erp_keys) == 25, f"e-FacturaWeb debe tener 25 módulos, tiene {len(erp_keys)}"
    assert len(portal_keys) == 25, f"Portal debe tener 25 módulos, tiene {len(portal_keys)}"

    assert erp_keys == portal_keys, "El orden y las claves canónicas difieren entre ERP y Portal"
    assert set(erp_keys) == set(portal_keys)


def test_module_categories_match():
    """Las categorías de cada módulo deben coincidir entre ambos sistemas."""
    erp_cat_map = {m["key"]: m["category"] for m in ERP_MODULE_DEFS}
    portal_cat_map = {m["key"]: m["category"] for m in PortalDatabaseService.MODULE_DEFS}

    for key, erp_cat in erp_cat_map.items():
        assert key in portal_cat_map, f"Clave {key} no encontrada en Portal"
        assert portal_cat_map[key] == erp_cat, (
            f"Categoría para {key} difiere: ERP={erp_cat}, Portal={portal_cat_map[key]}"
        )


def test_no_aliases_across_both_systems():
    """Ninguno de los dos sistemas debe contener aliases prohibidos."""
    erp_keys = set(m["key"] for m in ERP_MODULE_DEFS)
    portal_keys = set(m["key"] for m in PortalDatabaseService.MODULE_DEFS)

    assert not erp_keys.intersection(PROHIBITED_ALIASES)
    assert not portal_keys.intersection(PROHIBITED_ALIASES)


def test_portal_enterprise_plan_activates_all_25_modules_in_erp(app):
    """Un plan Enterprise generado por el Portal debe habilitar los 25 módulos en e-FacturaWeb."""
    all_keys = [m["key"] for m in PortalDatabaseService.MODULE_DEFS]
    portal_enterprise_modules = PortalDatabaseService.default_modules(all_keys)

    with app.test_request_context():
        session['company_modules'] = portal_enterprise_modules
        session['company_profile_pos_enabled'] = True

        for mod_key in all_keys:
            assert module_enabled(mod_key) is True, f"Módulo {mod_key} no habilitado con plan Enterprise del Portal"


def test_portal_restricted_plan_fails_closed_in_erp(app):
    """Un plan limitado generado por el Portal debe bloquear con fail-closed los módulos no contratados."""
    # Plan con solo e_cf y gastos
    portal_limited_modules = PortalDatabaseService.default_modules(["e_cf", "gastos"])

    with app.test_request_context():
        session['company_modules'] = portal_limited_modules
        session['company_profile_pos_enabled'] = True

        # Contratados -> True
        assert module_enabled("e_cf") is True
        assert module_enabled("gastos") is True

        # No contratados -> False
        assert module_enabled("banks") is False
        assert module_enabled("price_lists") is False
        assert module_enabled("certificacion") is False
        assert module_enabled("contabilidad") is False
        assert module_enabled("nomina") is False
        assert module_enabled("inventario") is False
