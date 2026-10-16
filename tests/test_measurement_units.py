import pytest
from flask import session
from unittest.mock import patch, MagicMock
from app.services.db_service import DatabaseService
from app.services.dgii_xml_builder import DgiiXmlBuilder

MOCK_USER_PROFILE = {
    'uid': 'user123',
    'email': 'test@example.com',
    'role': 'owner',
    'ownerUID': 'user123'
}

MOCK_COMPANY = {
    'id': 'comp123',
    'owner_uid': 'user123',
    'companyName': 'Empresa Test',
    'plan_id': 'pro',
    'status': 'active',
    'configured': True
}

MOCK_PLAN = {
    'id': 'pro',
    'name': 'Plan Pro',
    'plan_version': 1,
    'modules': {'catalogo': {'enabled': True}, 'e_cf': {'enabled': True}}
}

MOCK_CONTEXT = {
    'role': 'owner',
    'plan_id': 'pro',
    'plan_name': 'Plan Pro',
    'permissions': {'canManageCatalog': True}
}


def test_standard_measurement_units_format():
    """Verifica que las unidades estándar tengan la estructura requerida y formato Nombre (símbolo)."""
    units = DatabaseService.get_standard_measurement_units()
    assert len(units) >= 35

    # 'Unidad' debe existir y tener código DGII 43
    unidad = next((u for u in units if u["id"] == "unidad"), None)
    assert unidad is not None
    assert unidad["name"] == "Unidad"
    assert unidad["symbol"] == "ud"
    assert unidad["display"] == "Unidad (ud)"
    assert unidad["dgiiCode"] == "43"

    # 'Libra'
    libra = next((u for u in units if u["id"] == "libra"), None)
    assert libra is not None
    assert libra["display"] == "Libra (lb)"
    assert libra["dgiiCode"] == "23"

    # 'Galón'
    galon = next((u for u in units if u["id"] == "galon"), None)
    assert galon is not None
    assert galon["display"] == "Galón (gl)"
    assert galon["dgiiCode"] == "15"


def test_dgii_official_units_table():
    """Verifica que la tabla oficial DGII contenga los 62 códigos del estándar e-CF."""
    official = DatabaseService.get_dgii_official_units()
    assert len(official) == 62
    codes = {u["code"] for u in official}
    for i in range(1, 63):
        assert str(i) in codes


def test_get_measurement_units_ordering():
    """Verifica que get_measurement_units coloque 'Unidad' de primero y ordene el resto alfabéticamente."""
    units = DatabaseService.get_measurement_units(owner_uid="dummy_uid", sandbox=True)
    assert len(units) >= 35
    assert units[0]["name"] == "Unidad"

    # Verificar que el resto esté ordenado alfabéticamente por name
    rest_names = [u["name"].lower() for u in units[1:]]
    assert rest_names == sorted(rest_names)


def test_dgii_xml_builder_mapping():
    """Verifica la resolución de códigos DGII para nombres, abreviaturas y formatos con paréntesis."""
    # Nombres directos
    assert DgiiXmlBuilder.map_unit_of_measure("Unidad") == "43"
    assert DgiiXmlBuilder.map_unit_of_measure("Libra") == "23"
    assert DgiiXmlBuilder.map_unit_of_measure("Kilogramo") == "21"
    assert DgiiXmlBuilder.map_unit_of_measure("Litro") == "24"
    assert DgiiXmlBuilder.map_unit_of_measure("Galón") == "15"
    assert DgiiXmlBuilder.map_unit_of_measure("galon") == "15"
    assert DgiiXmlBuilder.map_unit_of_measure("Caja") == "6"
    assert DgiiXmlBuilder.map_unit_of_measure("Hora") == "19"
    assert DgiiXmlBuilder.map_unit_of_measure("Servicio") == "43"

    # Abreviaturas
    assert DgiiXmlBuilder.map_unit_of_measure("lb") == "23"
    assert DgiiXmlBuilder.map_unit_of_measure("kg") == "21"
    assert DgiiXmlBuilder.map_unit_of_measure("lt") == "24"
    assert DgiiXmlBuilder.map_unit_of_measure("gl") == "15"
    assert DgiiXmlBuilder.map_unit_of_measure("cj") == "6"
    assert DgiiXmlBuilder.map_unit_of_measure("paq") == "31"
    assert DgiiXmlBuilder.map_unit_of_measure("sac") == "46"
    assert DgiiXmlBuilder.map_unit_of_measure("doc") == "13"
    assert DgiiXmlBuilder.map_unit_of_measure("pza") == "34"

    # Formatos 'Nombre (símbolo)'
    assert DgiiXmlBuilder.map_unit_of_measure("Libra (lb)") == "23"
    assert DgiiXmlBuilder.map_unit_of_measure("Kilogramo (kg)") == "21"
    assert DgiiXmlBuilder.map_unit_of_measure("Litro (lt)") == "24"
    assert DgiiXmlBuilder.map_unit_of_measure("Galón (gl)") == "15"
    assert DgiiXmlBuilder.map_unit_of_measure("Caja (cj)") == "6"

    # Código numérico directo válido
    assert DgiiXmlBuilder.map_unit_of_measure("23") == "23"
    assert DgiiXmlBuilder.map_unit_of_measure("15") == "15"

    # Desconocido cae en fallback 43 (Unidad)
    assert DgiiXmlBuilder.map_unit_of_measure("UnidadInexistenteXYZ") == "43"
    assert DgiiXmlBuilder.map_unit_of_measure("") == "43"
    assert DgiiXmlBuilder.map_unit_of_measure(None) == "43"


def test_ajax_create_measurement_unit_unauthorized(client):
    """Verifica que /units/ajax_create requiera autenticación."""
    res = client.post('/units/ajax_create', json={'name': 'Paila'})
    assert res.status_code == 401
    data = res.get_json()
    assert data['success'] is False


def test_ajax_create_measurement_unit_validation(client):
    """Verifica que el nombre sea obligatorio al crear una unidad."""
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value=MOCK_PLAN), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value=MOCK_CONTEXT), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]):
        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user123', 'email': 'test@example.com', 'role': 'owner', 'ownerUID': 'user123'}
            sess['selected_company_id'] = 'comp123'
            sess['is_sandbox_mode'] = True

        res = client.post('/units/ajax_create', json={'name': '   ', 'symbol': 'pl'})
        assert res.status_code == 400
        data = res.get_json()
        assert data['success'] is False
        assert 'obligatorio' in data['error']


def test_ajax_create_measurement_unit_success(client):
    """Verifica la creación exitosa de una unidad de medida vía AJAX con homologación DGII."""
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value=MOCK_PLAN), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value=MOCK_CONTEXT), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]), \
         patch.object(DatabaseService, 'save_measurement_unit') as mock_save:
        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user123', 'email': 'test@example.com', 'role': 'owner', 'ownerUID': 'user123'}
            sess['selected_company_id'] = 'comp123'
            sess['is_sandbox_mode'] = True

        res = client.post('/units/ajax_create', json={
            'name': 'Paila de 5 Galones',
            'symbol': 'paila',
            'dgiiCode': '15'
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['name'] == 'Paila de 5 Galones'
        assert data['symbol'] == 'paila'
        assert data['dgiiCode'] == '15'
        assert data['display'] == 'Paila de 5 Galones (paila)'
        assert mock_save.called


def test_ajax_create_measurement_unit_already_exists(client):
    """Verifica que si la unidad ya existe (ej: 'Libra'), retorne el registro sin error."""
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_plan', return_value=MOCK_PLAN), \
         patch('app.services.db_service.DatabaseService.get_company_context', return_value=MOCK_CONTEXT), \
         patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner'}), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_projects', return_value=[]):
        with client.session_transaction() as sess:
            sess['user'] = {'uid': 'user123', 'email': 'test@example.com', 'role': 'owner', 'ownerUID': 'user123'}
            sess['selected_company_id'] = 'comp123'
            sess['is_sandbox_mode'] = True

        res = client.post('/units/ajax_create', json={'name': 'libra'})
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data.get('already_existed') is True
        assert data['name'] == 'Libra'
        assert data['dgiiCode'] == '23'
