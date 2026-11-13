"""Regresión del endpoint que crea la identidad global desde el perfil del cliente."""

from unittest.mock import patch

from flask import session

from app.web import contacts as contacts_module


def _call_ensure(app, contact_id, payload=None):
    with app.test_request_context(
        f'/contacts/{contact_id}/ensure_customer_account',
        method='POST',
        json=payload or {},
    ):
        session['user'] = {'ownerUID': 'u1', 'uid': 'u1', 'role': 'owner', 'email': 'owner@x.com'}
        session['selected_company_id'] = 'comp-1'
        session['is_sandbox_mode'] = True
        result = contacts_module.ensure_customer_account(contact_id)
    if isinstance(result, tuple):
        resp, status = result
    else:
        resp, status = result, 200
    return resp.get_json(), status


def _gates():
    return (
        patch('app.utils.module_gate.module_enabled', return_value=True),
        patch('app.web.contacts.check_permission', return_value=True),
    )


def test_ensure_customer_account_creates_and_links(app):
    contact = {'id': 'c1', 'types': ['cliente'], 'rnc': '131880681', 'razonSocial': 'X', 'email': 'x@y.com'}
    with _gates()[0], _gates()[1], \
         patch.object(contacts_module.ContactService, 'get_contact', return_value=contact), \
         patch.object(contacts_module.ContactService, 'save_contact', return_value={**contact, 'customerId': 'acct-1'}):
        data, status = _call_ensure(app, 'c1', {'email': 'x@y.com'})

    assert status == 200
    assert data['success'] is True
    assert data['customerId'] == 'acct-1'


def test_ensure_customer_account_requires_email(app):
    contact = {'id': 'c1', 'types': ['cliente'], 'rnc': '131880681', 'razonSocial': 'X', 'email': ''}
    with _gates()[0], _gates()[1], \
         patch.object(contacts_module.ContactService, 'get_contact', return_value=contact), \
         patch('app.services.customer_account_service.CustomerAccountService.valid_email', return_value=False):
        data, status = _call_ensure(app, 'c1', {})

    assert status == 400
    assert data['success'] is False
    assert data.get('needEmail') is True


def test_ensure_customer_account_rejects_invalid_email(app):
    contact = {'id': 'c1', 'types': ['cliente'], 'rnc': '131880681', 'razonSocial': 'X', 'email': ''}
    with _gates()[0], _gates()[1], \
         patch.object(contacts_module.ContactService, 'get_contact', return_value=contact), \
         patch('app.services.customer_account_service.CustomerAccountService.valid_email', return_value=False):
        data, status = _call_ensure(app, 'c1', {'email': 'no-es-correo'})

    assert status == 400
    assert data['success'] is False
    assert data.get('needEmail') is True
