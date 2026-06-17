import unittest
from flask import Flask
from app.utils.security import generate_portal_token, decode_portal_token

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

if __name__ == '__main__':
    unittest.main()
