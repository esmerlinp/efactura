import unittest
from unittest.mock import patch
from flask import Flask
from app.utils.security import generate_portal_token, decode_portal_token
from app.web.portal import portal_bp

class TestPortalSecurity(unittest.TestCase):
    def setUp(self):
        from app import create_app
        self.app = create_app()
        self.app.config['SECRET_KEY'] = 'test-secret-key-12345'
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
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

    def test_token_includes_doc_id(self):
        token = generate_portal_token('owner-123', 'client-456', sandbox=True, company_id='company-789', doc_id='quote-999')
        decoded = decode_portal_token(token)
        self.assertEqual(decoded['company_id'], 'company-789')
        self.assertEqual(decoded['doc_id'], 'quote-999')

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

    def test_portal_entry_with_doc_id(self):
        token = generate_portal_token('owner-123', 'client-456', sandbox=True, company_id='company-789', doc_id='quote-999')
        with self.app.test_client() as client:
            response = client.get(f'/portal/p/{token}')
            self.assertEqual(response.status_code, 302)
            self.assertIn('/portal', response.location)
            with client.session_transaction() as sess:
                self.assertEqual(sess.get('portal_owner_uid'), 'owner-123')
                self.assertEqual(sess.get('portal_client_id'), 'client-456')
                self.assertEqual(sess.get('portal_company_id'), 'company-789')
                self.assertEqual(sess.get('portal_next_url'), '/portal/documento/quote-999')

    @patch('app.web.portal.DatabaseService.get_company_profile', return_value=None)
    @patch('app.web.portal.PortalDbService.get_client_by_id', return_value={'id': 'client-456'})
    def test_portal_main_does_not_require_selected_company_id(self, mock_client, mock_company):
        with self.app.test_client() as client:
            with client.session_transaction() as current_session:
                current_session['portal_owner_uid'] = 'owner-123'
                current_session['portal_client_id'] = 'client-456'
                current_session['portal_sandbox'] = True

            response = client.get('/portal')

        self.assertEqual(response.status_code, 200)
        mock_company.assert_called_once_with('owner-123')

    @patch('app.web.portal.PortalDbService.save_invoice')
    @patch('app.web.portal._notify_portal_action')
    @patch('app.web.portal.PortalDbService.get_invoice')
    @patch('app.web.portal.PortalDbService.get_client_by_id')
    def test_accept_quotation_without_certificate(self, mock_client, mock_invoice, mock_notify, mock_save):
        mock_client.return_value = {
            'id': 'client-456',
            'name': 'Empresa Cliente SRL',
            'rnc': '101010101',
            'email': 'cliente@test.com'
        }
        mock_invoice.return_value = {
            'id': 'quote-123',
            'invoiceNumber': 'COT-001',
            'isQuotation': True,
            'status': 'Pendiente Aut. Cliente',
            'total': 15000.0,
            'clientName': 'Empresa Cliente SRL'
        }

        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['portal_owner_uid'] = 'owner-123'
                sess['portal_client_id'] = 'client-456'
                sess['portal_sandbox'] = True
                sess['portal_company_id'] = 'company-789'
                sess['verified_client_client-456'] = True

            # POST a la ruta de aceptación sin archivo de certificado digital
            response = client.post('/portal/cotizacion/quote-123/firmar', json={
                'action': 'accept'
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data['success'])
            self.assertIn('exitosa', data['message'])

            # Verificar que se guardó la cotización con status 'Aprobada' y método 'confirmacion_portal'
            mock_save.assert_called_once()
            saved_inv = mock_save.call_args[0][2]
            self.assertEqual(saved_inv['status'], 'Aprobada')
            self.assertEqual(saved_inv['signatureInfo']['method'], 'confirmacion_portal')
            self.assertEqual(saved_inv['signatureInfo']['signedByName'], 'Empresa Cliente SRL')
            self.assertTrue(saved_inv.get('acceptedAt'))

    @patch('app.web.portal.PortalDbService.get_invoice')
    @patch('app.web.portal.PortalDbService.get_client_by_id')
    def test_accept_quotation_already_approved(self, mock_client, mock_invoice):
        mock_client.return_value = {'id': 'client-456', 'rnc': '101010101'}
        mock_invoice.return_value = {
            'id': 'quote-123',
            'isQuotation': True,
            'status': 'Aprobada'
        }

        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['portal_owner_uid'] = 'owner-123'
                sess['portal_client_id'] = 'client-456'
                sess['verified_client_client-456'] = True

            response = client.post('/portal/cotizacion/quote-123/firmar', json={})
            self.assertEqual(response.status_code, 400)
            data = response.get_json()
            self.assertFalse(data['success'])
            self.assertIn('ya fue aprobada', data['error'])

    @patch('app.web.portal.PortalDbService.save_invoice')
    @patch('app.services.notifications.NotificationService.send_portal_action_notification')
    @patch('app.services.db_service.DatabaseService.get_team_members', return_value=[])
    @patch('app.web.portal.PortalDbService.get_invoice')
    @patch('app.web.portal.PortalDbService.get_client_by_id')
    def test_sign_quotation_full_flow_with_notification(self, mock_client, mock_invoice, mock_team, mock_send_notif, mock_save):
        mock_client.return_value = {
            'id': 'client-456',
            'name': 'Empresa Cliente SRL',
            'rnc': '101010101',
            'email': 'cliente@test.com',
            'responsibleId': 'resp-1'
        }
        mock_invoice.return_value = {
            'id': 'quote-123',
            'invoiceNumber': 'COT-001',
            'isQuotation': True,
            'status': 'Pendiente Aut. Cliente',
            'total': 15000.0,
            'clientName': 'Empresa Cliente SRL'
        }

        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['portal_owner_uid'] = 'owner-123'
                sess['portal_client_id'] = 'client-456'
                sess['portal_sandbox'] = True
                sess['portal_company_id'] = 'company-789'
                sess['verified_client_client-456'] = True

            response = client.post('/portal/cotizacion/quote-123/firmar', json={'action': 'accept'})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data['success'])

if __name__ == '__main__':
    unittest.main()


