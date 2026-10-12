import pytest
from unittest.mock import patch, MagicMock

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
        'reportes': {'enabled': True},
    }}),
)

def mock_login(client):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': 'test-owner',
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canInvoice': True},
        }
        sess['selected_company_id'] = 'test-owner'
        sess['selected_owner_uid'] = 'test-owner'
        sess['company_country'] = 'DO'
        sess['company_plan_id'] = 'plan-1'
        sess['company_modules'] = {'e_cf': {'enabled': True}}
        sess['is_sandbox_mode'] = True


def test_convert_quotation_success(app):
    for p in DB_PATCHES:
        p.start()

    try:
        quotation_data = {
            "id": "quote-123",
            "invoiceNumber": "COT-000123",
            "isQuotation": True,
            "status": "Aprobada",
            "total": 1000.0,
            "clientRNC": "131880681",
            "clientName": "Cliente Test",
            "items": [
                {
                    "code": "SRV1",
                    "name": "Servicio de Consultoria",
                    "price": 1000.0,
                    "quantity": 1,
                    "itbisRate": 0.18,
                    "subtotal": 1000.0,
                    "catalogId": "cat-1"
                }
            ]
        }

        saved_docs = {}

        def mock_get_invoice(owner_uid, invoice_id, company_id=None, sandbox=True):
            if invoice_id == "quote-123":
                return dict(saved_docs.get("quote-123", quotation_data))
            return saved_docs.get(invoice_id)

        def mock_save_invoice(owner_uid, invoice_id, data, company_id=None, sandbox=True):
            saved_docs[invoice_id] = dict(data)
            return True

        with patch("app.services.db_service.DatabaseService.get_invoice", side_effect=mock_get_invoice), \
             patch("app.services.db_service.DatabaseService.save_invoice", side_effect=mock_save_invoice), \
             patch("app.services.db_service.DatabaseService.get_client_advances", return_value=[]), \
             patch("app.web.invoices.check_permission", return_value=True):

            client = app.test_client()
            mock_login(client)

            response = client.post("/invoices/quote-123/convert", data={
                "targetEcfType": "Factura de Consumo (E32)"
            }, follow_redirects=False)

            assert response.status_code == 302
            assert "/invoices/" in response.headers["Location"]

            # Check that original quotation status was updated
            assert saved_docs["quote-123"]["status"] == "Facturada"
            assert "convertedToInvoiceId" in saved_docs["quote-123"]
            new_inv_id = saved_docs["quote-123"]["convertedToInvoiceId"]

            # Check created invoice
            new_inv = saved_docs[new_inv_id]
            assert new_inv["isQuotation"] is False
            assert new_inv["isConvertedToInvoice"] is True
            assert new_inv["status"] == "Borrador"
            assert new_inv["invoiceNumber"].startswith("FAC-")
            assert new_inv["quotationId"] == "quote-123"
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_convert_quotation_alias_route(app):
    for p in DB_PATCHES:
        p.start()

    try:
        quotation_data = {
            "id": "quote-456",
            "invoiceNumber": "COT-000456",
            "isQuotation": True,
            "status": "Aprobada",
            "total": 500.0,
            "clientRNC": "",
            "items": []
        }

        with patch("app.services.db_service.DatabaseService.get_invoice", return_value=dict(quotation_data)), \
             patch("app.services.db_service.DatabaseService.save_invoice", return_value=True), \
             patch("app.services.db_service.DatabaseService.get_client_advances", return_value=[]), \
             patch("app.web.invoices.check_permission", return_value=True):

            client = app.test_client()
            mock_login(client)

            # Test both routes exist and do not return 404
            res1 = client.post("/invoices/quote-456/convert", data={"targetEcfType": "Factura de Consumo (E32)"})
            assert res1.status_code != 404

            res2 = client.post("/quotations/quote-456/convert", data={"targetEcfType": "Factura de Consumo (E32)"})
            assert res2.status_code != 404
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_convert_quotation_e31_requires_rnc(app):
    for p in DB_PATCHES:
        p.start()

    try:
        quotation_data = {
            "id": "quote-789",
            "invoiceNumber": "COT-000789",
            "isQuotation": True,
            "status": "Aprobada",
            "total": 500.0,
            "clientRNC": "",  # Sin RNC
            "items": []
        }

        with patch("app.services.db_service.DatabaseService.get_invoice", return_value=dict(quotation_data)), \
             patch("app.services.db_service.DatabaseService.save_invoice") as mock_save, \
             patch("app.web.invoices.check_permission", return_value=True):

            client = app.test_client()
            mock_login(client)

            res = client.post("/invoices/quote-789/convert", data={"targetEcfType": "Factura de Crédito Fiscal (E31)"})
            # Should redirect back to detail without saving
            assert res.status_code == 302
            assert "quote-789" in res.headers["Location"]
            mock_save.assert_not_called()
    finally:
        for p in DB_PATCHES:
            p.stop()
