import unittest
from unittest.mock import patch
from flask import Flask
from app.utils.security import generate_portal_token, decode_portal_token
from app.web.portal import portal_bp

class TestPortalSecurity(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test-secret-key-12345'
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_token_lifecycle(self):
        owner_uid = "owner-123"
        client_id = "client-456"
        sandbox = True

        # 1. Generar token
        token = generate_portal_token(owner_uid, client_id, sandbox=sandbox)
        self.assertIsNotNone(token)
        self.assertIsInstance(token, str)

        # 2. Decodificar token
        decoded = decode_portal_token(token)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded['owner_uid'], owner_uid)
        self.assertEqual(decoded['client_id'], client_id)
        self.assertEqual(decoded['sandbox'], sandbox)

    def test_token_includes_company(self):
        token = generate_portal_token('owner-123', 'client-456', sandbox=True, company_id='company-789')
        decoded = decode_portal_token(token)
        self.assertEqual(decoded['company_id'], 'company-789')

    def test_invalid_token(self):
        # Intentar decodificar basura
        decoded = decode_portal_token("invalid-garbage-token")
        self.assertIsNone(decoded)

    def test_tampered_token(self):
        owner_uid = "owner-123"
        client_id = "client-456"
        
        token = generate_portal_token(owner_uid, client_id, sandbox=True)
        # Modificar el token
        tampered_token = token + "modified"
        decoded = decode_portal_token(tampered_token)
        self.assertIsNone(decoded)

    @patch('app.web.portal.DatabaseService.get_company_profile', return_value=None)
    @patch('app.web.portal.PortalDbService.get_client_by_id', return_value={'id': 'client-456'})
    def test_portal_main_does_not_require_selected_company_id(self, mock_client, mock_company):
        self.app.register_blueprint(portal_bp)
        with self.app.test_client() as client:
            with client.session_transaction() as current_session:
                current_session['portal_owner_uid'] = 'owner-123'
                current_session['portal_client_id'] = 'client-456'
                current_session['portal_sandbox'] = True

            response = client.get('/portal')

        self.assertEqual(response.status_code, 200)
        mock_company.assert_called_once_with('owner-123')

if __name__ == '__main__':
    unittest.main()
