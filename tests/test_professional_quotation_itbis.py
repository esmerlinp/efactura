import pytest
import json
from unittest.mock import patch

MOCK_USER_PROFILE = {
    'uid': 'test-uid',
    'ownerUID': 'test-owner',
    'role': 'owner',
    'email': 'admin@test.com',
    'name': 'Admin',
    'default_company_id': 'test-owner',
    'isOnboardingComplete': True,
}

MOCK_COMPANY = {
    'id': 'test-owner',
    'ownerUID': 'test-owner',
    'companyName': 'Test Co',
    'rnc': '131880681',
    'isVerified': True,
    'sandboxIndefinite': True,
    'country': 'DO',
    'planId': 'plan-1',
    'configured': True,
}

DB_PATCHES = (
    patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE),
    patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]),
    patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY),
    patch('app.services.db_service.DatabaseService.get_company', return_value=None),
    patch('app.services.db_service.DatabaseService.get_company_context', return_value={'permissions': {}, 'company_name': 'Test Co'}),
    patch('app.services.db_service.DatabaseService.get_branches', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_projects', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active'}),
    patch('app.services.db_service.DatabaseService.get_plan', return_value={'modules': {
        'e_cf': {'enabled': True},
        'cotizaciones': {'enabled': True},
        'reportes': {'enabled': True},
    }}),
    patch('app.services.db_service.DatabaseService.get_items', return_value=[]),
)

def mock_login(client):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': 'test-owner',
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canManageQuotations': True, 'canInvoice': True},
        }
        sess['selected_company_id'] = 'test-owner'
        sess['selected_owner_uid'] = 'test-owner'
        sess['company_country'] = 'DO'
        sess['company_plan_id'] = 'plan-1'
        sess['company_modules'] = {'e_cf': {'enabled': True}, 'cotizaciones': {'enabled': True}}
        sess['is_sandbox_mode'] = True


def test_quotation_preview_itbis_zero(app):
    for p in DB_PATCHES:
        p.start()

    try:
        client = app.test_client()
        mock_login(client)

        payload = {
            "items": [
                {
                    "code": "PROD0",
                    "name": "Servicio Exento",
                    "price": 1000.0,
                    "quantity": 1,
                    "itbisRate": 0,
                    "discountRate": 0
                }
            ],
            "subject": "Propuesta Exenta"
        }

        resp = client.post('/api/quotations/preview', json=payload)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Total ITBIS must be 0.00, NOT 180.00
        assert "Total ITBIS:" in html
        assert "RD$ 0.00" in html
        assert "RD$ 180.00" not in html
        # Total must be 1,000.00, NOT 1,180.00
        assert "RD$ 1,000.00" in html
        assert "RD$ 1,180.00" not in html
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_quotation_preview_itbis_eighteen(app):
    for p in DB_PATCHES:
        p.start()

    try:
        client = app.test_client()
        mock_login(client)

        payload = {
            "items": [
                {
                    "code": "PROD18",
                    "name": "Servicio Gravado",
                    "price": 1000.0,
                    "quantity": 1,
                    "itbisRate": 0.18,
                    "discountRate": 0
                }
            ],
            "subject": "Propuesta Gravada"
        }

        resp = client.post('/api/quotations/preview', json=payload)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert "RD$ 180.00" in html
        assert "RD$ 1,180.00" in html
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_professional_quotation_save_itbis_zero(app):
    for p in DB_PATCHES:
        p.start()

    saved_docs = {}

    def mock_save_invoice(owner_uid, invoice_id, data, company_id=None, sandbox=True):
        saved_docs[invoice_id] = dict(data)
        return {"id": invoice_id}

    try:
        with patch("app.services.db_service.DatabaseService.save_invoice", side_effect=mock_save_invoice), \
             patch("app.web.invoices.check_permission", return_value=True):

            client = app.test_client()
            mock_login(client)

            payload = {
                "clientName": "Cliente de Prueba",
                "clientRNC": "131880681",
                "items": [
                    {
                        "code": "EX01",
                        "name": "Consultoría Exenta",
                        "price": 5000.0,
                        "quantity": 2,
                        "itbisRate": 0,
                        "discountRate": 0
                    }
                ],
                "subject": "Cotización Exenta"
            }

            resp = client.post('/quotations/new/professional', json=payload)
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            doc_id = data["id"]

            saved = saved_docs[doc_id]
            assert saved["isProfessional"] is True
            assert saved["isQuotation"] is True
            assert saved["totalITBIS"] == 0.0
            assert saved["subtotal"] == 10000.0
            assert saved["total"] == 10000.0
            assert saved["items"][0]["itbisRate"] == 0.0
            assert saved["items"][0]["itbis_amount"] == 0.0
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_professional_quotation_edit_loads_itbis_zero(app):
    for p in DB_PATCHES:
        p.start()

    existing_quote = {
        "id": "quote-999",
        "invoiceNumber": "COT-000999",
        "isQuotation": True,
        "isProfessional": True,
        "status": "Borrador",
        "clientName": "Cliente Test",
        "professionalData": {"subject": "Proyecto 0% ITBIS"},
        "items": [
            {
                "code": "EX99",
                "name": "Partida con ITBIS 0%",
                "price": 2500.0,
                "quantity": 1,
                "itbisRate": 0.0,
                "discountRate": 0,
                "subtotal": 2500.0
            }
        ]
    }

    try:
        with patch("app.services.db_service.DatabaseService.get_invoice", return_value=existing_quote), \
             patch("app.web.invoices.check_permission", return_value=True):

            client = app.test_client()
            mock_login(client)

            resp = client.get('/quotations/new/professional?edit=quote-999')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)

            # Check that initial data json has itbisRate == 0.0 and id == quote-999
            start_tag = '<div id="wz-initial-data-json" style="display:none;">'
            assert start_tag in html
            json_str = html.split(start_tag)[1].split('</div>')[0]
            initial_data = json.loads(json_str)

            assert initial_data["id"] == "quote-999"
            assert initial_data["isEdit"] is True
            assert len(initial_data["items"]) == 1
            assert initial_data["items"][0]["itbisRate"] == 0.0
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_professional_quotation_edit_save_updates_draft(app):
    for p in DB_PATCHES:
        p.start()

    saved_docs = {
        "quote-999": {
            "id": "quote-999",
            "invoiceNumber": "COT-000999",
            "isQuotation": True,
            "isProfessional": True,
            "status": "Borrador",
            "clientName": "Cliente Original",
            "createdAt": "2026-01-01T00:00:00Z",
            "items": []
        }
    }

    def mock_get_invoice(owner_uid, invoice_id, company_id=None, sandbox=True):
        return saved_docs.get(invoice_id)

    def mock_save_invoice(owner_uid, invoice_id, data, company_id=None, sandbox=True):
        saved_docs[invoice_id] = dict(data)
        return {"id": invoice_id}

    try:
        with patch("app.services.db_service.DatabaseService.get_invoice", side_effect=mock_get_invoice), \
             patch("app.services.db_service.DatabaseService.save_invoice", side_effect=mock_save_invoice), \
             patch("app.web.invoices.check_permission", return_value=True):

            client = app.test_client()
            mock_login(client)

            payload = {
                "id": "quote-999",
                "clientName": "Cliente Actualizado",
                "clientRNC": "131880681",
                "items": [
                    {
                        "code": "EX99",
                        "name": "Partida Editada 0%",
                        "price": 3000.0,
                        "quantity": 1,
                        "itbisRate": 0,
                        "discountRate": 0
                    }
                ],
                "subject": "Cotización Editada"
            }

            resp = client.post('/quotations/new/professional', json=payload)
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert data["id"] == "quote-999"

            updated = saved_docs["quote-999"]
            assert updated["invoiceNumber"] == "COT-000999"
            assert updated["clientName"] == "Cliente Actualizado"
            assert updated["items"][0]["itbisRate"] == 0.0
            assert updated["totalITBIS"] == 0.0
            assert updated["total"] == 3000.0
    finally:
        for p in DB_PATCHES:
            p.stop()
