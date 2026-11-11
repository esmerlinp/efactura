from datetime import datetime, timezone, timedelta, date
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from app.services.quotation_expiry_service import (
    quotation_expiry,
    apply_expiry_status,
    persist_quotation_vencida,
)

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


class TestApplyExpiryStatus:
    def test_marks_pending_quotation_as_vencida_when_expired(self):
        invoice = {
            "isQuotation": True,
            "status": "Pendiente Aut. Cliente",
            "date": _days_ago(20),
            "professionalData": {"validityDays": 15},
        }
        changed = apply_expiry_status(invoice, today=date.today())
        assert changed is True
        assert invoice["status"] == "Vencida"

    def test_does_not_touch_valid_pending_quotation(self):
        invoice = {
            "isQuotation": True,
            "status": "Pendiente Aut. Cliente",
            "date": _days_ago(3),
            "professionalData": {"validityDays": 15},
        }
        changed = apply_expiry_status(invoice, today=date.today())
        assert changed is False
        assert invoice["status"] == "Pendiente Aut. Cliente"

    def test_ignores_non_quotation_documents(self):
        invoice = {
            "isQuotation": False,
            "status": "Pendiente Aut. Cliente",
            "date": _days_ago(20),
            "professionalData": {"validityDays": 15},
        }
        changed = apply_expiry_status(invoice, today=date.today())
        assert changed is False
        assert invoice["status"] == "Pendiente Aut. Cliente"

    def test_never_modifies_terminal_states(self):
        for terminal in ("Aprobada", "Rechazada", "Cancelada", "Anulada", "Borrador"):
            invoice = {
                "isQuotation": True,
                "status": terminal,
                "date": _days_ago(20),
                "professionalData": {"validityDays": 15},
            }
            changed = apply_expiry_status(invoice, today=date.today())
            assert changed is False
            assert invoice["status"] == terminal

    def test_idempotent_on_already_vencida(self):
        invoice = {
            "isQuotation": True,
            "status": "Vencida",
            "date": _days_ago(20),
            "professionalData": {"validityDays": 15},
        }
        changed = apply_expiry_status(invoice, today=date.today())
        assert changed is False
        assert invoice["status"] == "Vencida"

    def test_none_invoice_is_false(self):
        assert apply_expiry_status(None, today=date.today()) is False


class TestPersistQuotationVencida:
    def test_partial_update_status_only(self):
        fake_doc = MagicMock()
        fake_coll = MagicMock()
        fake_coll.document.return_value = fake_doc
        fake_companies = MagicMock()
        fake_companies.document.return_value.collection.return_value = fake_coll
        fake_db = MagicMock()
        fake_db.collection.return_value = fake_companies

        with patch("app.services.db_service.db_firestore", fake_db), \
             patch("app.services.db_service.firebase_initialized", True), \
             patch("app.services.db_service._invalidate_invoices") as mock_invalidate:
            ok = persist_quotation_vencida("owner-1", "quote-1", sandbox=True, company_id="company-1")

        assert ok is True
        fake_db.collection.assert_called_once_with("companies")
        fake_companies.document.assert_called_once_with("company-1")
        fake_companies.document.return_value.collection.assert_called_once_with("sandbox_invoices")
        fake_coll.document.assert_called_once_with("quote-1")
        fake_doc.update.assert_called_once_with({"status": "Vencida"})
        assert not fake_doc.set.called
        mock_invalidate.assert_called_once_with("owner-1", company_id="company-1")

    def test_returns_false_when_firestore_unavailable(self):
        with patch("app.services.db_service.firebase_initialized", False):
            ok = persist_quotation_vencida("owner-1", "quote-1", sandbox=True, company_id="company-1")
        assert ok is False

    def test_returns_false_without_ids(self):
        assert persist_quotation_vencida(None, "quote-1") is False
        assert persist_quotation_vencida("owner-1", None) is False


@pytest.mark.usefixtures('app')
class TestPortalRejectsExpiredQuotation:
    @patch('app.web.portal.persist_quotation_vencida')
    @patch('app.web.portal.PortalDbService.save_invoice')
    @patch('app.web.portal.PortalDbService.get_invoice')
    @patch('app.web.portal.PortalDbService.get_client_by_id')
    def test_sign_quotation_expired(self, mock_client, mock_invoice, mock_save, mock_persist, app):
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
            mock_persist.assert_called_once_with('owner-123', 'quote-123', sandbox=True, company_id='company-789')


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
             patch('app.web.invoices.DatabaseService.save_invoice') as mock_save, \
             patch('app.web.invoices.persist_quotation_vencida') as mock_persist:
            client = app.test_client()
            mock_login(client)
            response = client.post('/quotations/quote-123/approve', follow_redirects=False)
            assert response.status_code == 302
            mock_save.assert_not_called()
            mock_persist.assert_called_once()
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
             patch('app.web.invoices.DatabaseService.save_invoice') as mock_save, \
             patch('app.web.invoices.persist_quotation_vencida') as mock_persist:
            client = app.test_client()
            mock_login(client)
            response = client.post('/quotations/quote-123/approve', follow_redirects=False)
            assert response.status_code == 302
            mock_save.assert_called_once()
            mock_persist.assert_not_called()
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_approve_proforma_persists_approved_status(app):
    for p in DB_PATCHES:
        p.start()
    try:
        proforma_data = {
            'id': 'proforma-123',
            'invoiceNumber': 'PRO-001',
            'isQuotation': True,
            'documentType': 'proforma',
            'status': 'Pendiente de pago',
            'total': 15000.0,
            'date': _days_ago(3),
        }
        with patch('app.web.invoices.check_permission', return_value=True), \
             patch('app.web.invoices.DatabaseService.get_invoice', return_value=dict(proforma_data)), \
             patch('app.web.invoices.DatabaseService.save_invoice') as mock_save, \
             patch('app.web.invoices.persist_quotation_vencida') as mock_persist:
            client = app.test_client()
            mock_login(client)
            response = client.post('/quotations/proforma-123/approve', follow_redirects=False)

            assert response.status_code == 302
            mock_save.assert_called_once()
            saved = mock_save.call_args.args[2]
            assert saved['status'] == 'Aprobada'
            assert saved['isQuotation'] is True
            assert saved['documentType'] == 'proforma'
            mock_persist.assert_not_called()
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_legacy_partially_paid_proforma_is_approved_for_conversion(app):
    for p in DB_PATCHES:
        p.start()
    try:
        proforma_data = {
            'id': 'proforma-paid',
            'invoiceNumber': 'PRO-PAID',
            'isQuotation': True,
            'documentType': 'proforma',
            'status': 'Pago parcial',
            'total': 15000.0,
            'totalPaid': 5000.0,
            'remainingBalance': 10000.0,
            'clientRNC': '131880681',
            'items': [],
        }
        saved = {}

        with patch('app.web.invoices.check_permission', return_value=True), \
             patch('app.web.invoices.DatabaseService.get_invoice', return_value=dict(proforma_data)), \
             patch('app.web.invoices.DatabaseService.get_invoice_payments', return_value=[]), \
             patch('app.web.invoices.DatabaseService.save_invoice', side_effect=lambda owner, doc_id, data, **kwargs: saved.update({doc_id: dict(data)})), \
             patch('app.web.invoices.DatabaseService.get_client_advances', return_value=[]):
            client = app.test_client()
            mock_login(client)
            response = client.post('/proformas/proforma-paid/convert', data={
                'targetEcfType': 'Factura de Consumo (E32)'
            }, follow_redirects=False)

            assert response.status_code == 302
            assert saved['proforma-paid']['status'] == 'Facturada'
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_quotations_list_excludes_proformas(app):
    for p in DB_PATCHES:
        p.start()
    try:
        documents = [
            {'id': 'quote-1', 'isQuotation': True, 'documentType': 'quotation', 'status': 'Borrador', 'invoiceNumber': 'COT-1', 'total': 100.0, 'date': '2026-11-11'},
            {'id': 'proforma-1', 'isQuotation': True, 'documentType': 'proforma', 'status': 'Aprobada', 'invoiceNumber': 'PRO-1', 'total': 100.0, 'date': '2026-11-11'},
        ]
        with patch('app.web.invoices.check_permission', return_value=True), \
             patch('app.web.invoices.DatabaseService.get_invoices', return_value=documents):
            client = app.test_client()
            mock_login(client)
            response = client.get('/quotations?per_page=all')
            assert response.status_code == 200
            body = response.get_data(as_text=True)
            assert 'COT-1' in body
            assert 'PRO-1' not in body
    finally:
        for p in DB_PATCHES:
            p.stop()
