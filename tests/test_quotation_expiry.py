from datetime import datetime, timezone, timedelta, date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.quotation_expiry_service import quotation_expiry

MOCK_USER_PROFILE = {
    'uid': 'test-uid',
    'ownerUID': 'test-owner',
    'role': 'owner',
    'email': 'admin@test.com',
    'name': 'Admin',
    'default_company_id': 'test-owner',
    'isOnboardingComplete': True,
}

DB_PATCHES = (
    patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE),
    patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]),
    patch('app.services.db_service.DatabaseService.get_company_profile', return_value={'id': 'test-owner', 'ownerUID': 'test-owner', 'planId': 'plan-1'}),
    patch('app.services.db_service.DatabaseService.get_company', return_value={'id': 'test-owner', 'owner_uid': 'test-owner', 'plan_id': 'plan-1', 'configured': True, 'status': 'active', 'country': 'DO', 'sandbox_enabled': True, 'production_enabled': True}),
    patch('app.services.db_service.DatabaseService.get_company_context', return_value={'permissions': {}, 'company_name': 'Test Co', 'role': 'owner', 'owner_uid': 'test-owner'}),
    patch('app.services.db_service.DatabaseService.get_plan', return_value={'plan_version': 0, 'modules': {'cotizaciones': {'enabled': True}, 'e_cf': {'enabled': True}}}),
    patch('app.services.db_service.DatabaseService.get_branches', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_projects', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active'}),
    patch('app.services.production_agreement_guard.ProductionAgreementGuard.evaluate', return_value=SimpleNamespace(blocked=False, reason='ok')),
)


def _days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def mock_login(client):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': 'test-owner',
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canManageQuotations': True},
        }
        sess['selected_company_id'] = 'test-owner'
        sess['selected_owner_uid'] = 'test-owner'
        sess['company_country'] = 'DO'
        sess['company_plan_id'] = 'plan-1'
        sess['company_modules'] = {'cotizaciones': {'enabled': True}, 'e_cf': {'enabled': True}}
        sess['is_sandbox_mode'] = True


class TestQuotationExpiryHelper:
    def test_not_expired_when_within_validity(self):
        invoice = {"date": _days_ago(3), "professionalData": {"validityDays": 15}}
        info = quotation_expiry(invoice, today=date.today())
        assert info["expired"] is False
        assert info["validity_days"] == 15
        assert info["expiry_date"] is not None

    def test_expired_when_past_validity(self):
        invoice = {"date": _days_ago(20), "professionalData": {"validityDays": 15}}
        info = quotation_expiry(invoice, today=date.today())
        assert info["expired"] is True

    def test_no_validity_means_not_expired(self):
        invoice = {"date": _days_ago(30)}
        info = quotation_expiry(invoice, today=date.today())
        assert info["expired"] is False
        assert info["expiry_date"] is None

    def test_zero_validity_means_not_expired(self):
        invoice = {"date": _days_ago(5), "professionalData": {"validityDays": 0}}
        info = quotation_expiry(invoice, today=date.today())
        assert info["expired"] is False

    def test_top_level_validity_days_fallback(self):
        invoice = {"date": _days_ago(20), "validityDays": 10}
        info = quotation_expiry(invoice, today=date.today())
        assert info["expired"] is True

    def test_missing_date_means_not_expired(self):
        invoice = {"professionalData": {"validityDays": 15}}
        info = quotation_expiry(invoice, today=date.today())
        assert info["expired"] is False


@pytest.mark.usefixtures('app')
class TestPortalRejectsExpiredQuotation:
    @patch('app.web.portal.PortalDbService.save_invoice')
    @patch('app.web.portal.PortalDbService.get_invoice')
    @patch('app.web.portal.PortalDbService.get_client_by_id')
    def test_sign_quotation_expired(self, mock_client, mock_invoice, mock_save, app):
        mock_client.return_value = {
            'id': 'client-456', 'name': 'Empresa Cliente SRL', 'rnc': '101010101',
        }
        mock_invoice.return_value = {
            'id': 'quote-123',
            'invoiceNumber': 'COT-001',
            'isQuotation': True,
            'status': 'Pendiente Aut. Cliente',
            'total': 15000.0,
            'clientName': 'Empresa Cliente SRL',
            'date': _days_ago(30),
            'professionalData': {'validityDays': 15},
        }

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['portal_owner_uid'] = 'owner-123'
                sess['portal_client_id'] = 'client-456'
                sess['portal_sandbox'] = True
                sess['portal_company_id'] = 'company-789'
                sess['verified_client_client-456'] = True

            response = client.post('/portal/cotizacion/quote-123/firmar', json={'action': 'accept'})

            assert response.status_code == 400
            data = response.get_json()
            assert data['success'] is False
            assert 'vencido' in data['error'].lower()
            mock_save.assert_not_called()


def test_approve_quotation_expired(app):
    for p in DB_PATCHES:
        p.start()
    try:
        quotation_data = {
            'id': 'quote-123',
            'invoiceNumber': 'COT-001',
            'isQuotation': True,
            'status': 'Pendiente Aut. Cliente',
            'total': 15000.0,
            'date': _days_ago(30),
            'professionalData': {'validityDays': 15},
        }
        with patch('app.web.invoices.check_permission', return_value=True), \
             patch('app.web.invoices.DatabaseService.get_invoice', return_value=dict(quotation_data)), \
             patch('app.web.invoices.DatabaseService.save_invoice') as mock_save:
            client = app.test_client()
            mock_login(client)
            response = client.post('/quotations/quote-123/approve', follow_redirects=False)
            assert response.status_code == 302
            mock_save.assert_not_called()
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_approve_quotation_still_allowed_when_valid(app):
    for p in DB_PATCHES:
        p.start()
    try:
        quotation_data = {
            'id': 'quote-123',
            'invoiceNumber': 'COT-001',
            'isQuotation': True,
            'status': 'Pendiente Aut. Cliente',
            'total': 15000.0,
            'date': _days_ago(3),
            'professionalData': {'validityDays': 15},
        }
        with patch('app.web.invoices.check_permission', return_value=True), \
             patch('app.web.invoices.DatabaseService.get_invoice', return_value=dict(quotation_data)), \
             patch('app.web.invoices.DatabaseService.save_invoice') as mock_save:
            client = app.test_client()
            mock_login(client)
            response = client.post('/quotations/quote-123/approve', follow_redirects=False)
            assert response.status_code == 302
            mock_save.assert_called_once()
    finally:
        for p in DB_PATCHES:
            p.stop()
