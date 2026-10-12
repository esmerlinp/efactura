import pytest
from flask import Flask, session
from unittest.mock import patch
from app.web.invoices import web_invoices_bp
from app.services.db_service import DatabaseService


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    app.register_blueprint(web_invoices_bp)
    return app


def test_ajax_create_category_unauthorized(app):
    client = app.test_client()
    res = client.post('/categories/ajax_create', json={'name': 'Tecnología'})
    assert res.status_code == 401
    assert res.get_json()['success'] is False


def test_ajax_create_category_forbidden_permission(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user'] = {'ownerUID': 'user_123', 'role': 'viewer'}
        sess['selected_company_id'] = 'comp_123'
        sess['is_sandbox_mode'] = True

    with patch('app.web.invoices.module_enabled', return_value=True), \
         patch('app.web.invoices.check_permission', return_value=False):
        res = client.post('/categories/ajax_create', json={'name': 'Tecnología'})
        assert res.status_code == 403
        assert res.get_json()['success'] is False


def test_ajax_create_category_empty_name(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user'] = {'ownerUID': 'user_123', 'role': 'admin'}
        sess['selected_company_id'] = 'comp_123'
        sess['is_sandbox_mode'] = True

    with patch('app.web.invoices.module_enabled', return_value=True), \
         patch('app.web.invoices.check_permission', return_value=True):
        res = client.post('/categories/ajax_create', json={'name': '   '})
        assert res.status_code == 400
        assert res.get_json()['success'] is False
        assert "obligatorio" in res.get_json()['error']


def test_ajax_create_category_success_new(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user'] = {'ownerUID': 'user_123', 'role': 'admin'}
        sess['selected_company_id'] = 'comp_123'
        sess['is_sandbox_mode'] = True

    with patch('app.web.invoices.module_enabled', return_value=True), \
         patch('app.web.invoices.check_permission', return_value=True), \
         patch.object(DatabaseService, 'get_categories', return_value=[]), \
         patch.object(DatabaseService, 'save_category') as mock_save:
        res = client.post('/categories/ajax_create', json={'name': 'Ferretería Industrial', 'description': 'Herramientas pesadas'})
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['name'] == 'Ferretería Industrial'
        assert data['id'] == 'ferreteria-industrial'
        assert mock_save.called


def test_ajax_create_category_already_exists(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user'] = {'ownerUID': 'user_123', 'role': 'admin'}
        sess['selected_company_id'] = 'comp_123'
        sess['is_sandbox_mode'] = True

    existing = [{'id': 'alimentos', 'name': 'Alimentos y Bebidas'}]
    with patch('app.web.invoices.module_enabled', return_value=True), \
         patch('app.web.invoices.check_permission', return_value=True), \
         patch.object(DatabaseService, 'get_categories', return_value=existing), \
         patch.object(DatabaseService, 'save_category') as mock_save:
        res = client.post('/categories/ajax_create', json={'name': 'alimentos y bebidas'})
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['id'] == 'alimentos'
        assert data['already_existed'] is True
        assert not mock_save.called
