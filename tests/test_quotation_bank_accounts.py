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
    'companyName': 'Empresa Dominicana SRL',
    'rnc': '131880681',
    'isVerified': True,
    'sandboxIndefinite': True,
    'country': 'DO',
    'planId': 'plan-1',
    'configured': True,
}

MOCK_BANK_ACCOUNTS = [
    {
        'id': 'bank-acc-1',
        'name': 'Banco Popular Corriente DOP',
        'type': 'banco',
        'accountNumber': '798123456',
        'description': 'Cuenta corriente principal'
    },
    {
        'id': 'bank-acc-2',
        'name': 'Banco BHD Ahorros USD',
        'type': 'banco',
        'accountNumber': '987654321',
        'description': 'Cuenta ahorros dólares'
    }
]

DB_PATCHES = (
    patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE),
    patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[{'ownerUID': 'test-owner', 'companyName': 'Empresa Dominicana SRL', 'role': 'owner'}]),
    patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY),
    patch('app.services.db_service.DatabaseService.get_company', return_value=None),
    patch('app.services.db_service.DatabaseService.get_company_context', return_value={'permissions': {}, 'company_name': 'Empresa Dominicana SRL'}),
    patch('app.services.db_service.DatabaseService.get_branches', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_projects', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active'}),
    patch('app.services.db_service.DatabaseService.get_plan', return_value={'modules': {
        'e_cf': {'enabled': True},
        'cotizaciones': {'enabled': True},
        'reportes': {'enabled': True},
    }}),
    patch('app.services.db_service.DatabaseService.get_items', return_value=[]),
    patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=MOCK_BANK_ACCOUNTS),
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


def test_quotation_preview_with_bank_accounts(app):
    for p in DB_PATCHES:
        p.start()

    try:
        client = app.test_client()
        mock_login(client)

        payload = {
            "items": [
                {
                    "code": "SRV1",
                    "name": "Consultoría Especializada",
                    "price": 50000.0,
                    "quantity": 1,
                    "itbisRate": 0.18,
                    "discountRate": 0
                }
            ],
            "subject": "Implementación de Sistema ERP",
            "bankAccounts": [
                {
                    "bank": "Banco Popular Dominicano",
                    "accountNumber": "798123456",
                    "accountType": "Corriente",
                    "currency": "DOP",
                    "holderName": "Empresa Dominicana SRL",
                    "holderRnc": "131880681",
                    "notes": "Favor colocar no. de cotización como referencia"
                },
                {
                    "bank": "Banreservas",
                    "accountNumber": "2409876543",
                    "accountType": "Ahorros",
                    "currency": "USD",
                    "holderName": "Empresa Dominicana SRL",
                    "holderRnc": "131880681",
                    "notes": ""
                }
            ]
        }

        resp = client.post('/api/quotations/preview', json=payload)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert "Cuentas Bancarias para Depósito o Transferencia:" in html
        assert "Banco Popular Dominicano" in html
        assert "798123456" in html
        assert "Banreservas" in html
        assert "2409876543" in html
        assert "Empresa Dominicana SRL" in html
        assert "131880681" in html
        assert "Favor colocar no. de cotización como referencia" in html
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_professional_quotation_save_bank_accounts(app):
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
                "clientName": "Cliente VIP SA",
                "clientRNC": "101010101",
                "subject": "Desarrollo a la Medida",
                "items": [
                    {
                        "code": "DEV01",
                        "name": "Módulo de Facturación",
                        "price": 25000.0,
                        "quantity": 1,
                        "itbisRate": 0.18,
                        "discountRate": 0
                    }
                ],
                "bankAccounts": [
                    {
                        "bank": "Banco BHD",
                        "accountNumber": "1234567890",
                        "accountType": "Corriente",
                        "currency": "DOP",
                        "holderName": "Empresa Dominicana SRL",
                        "holderRnc": "131880681",
                        "notes": "Notificar a cobros@empresa.com"
                    }
                ]
            }

            resp = client.post('/quotations/new/professional', json=payload)
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            saved_id = data["id"]
            assert saved_id in saved_docs

            saved_invoice = saved_docs[saved_id]
            assert "professionalData" in saved_invoice
            pd = saved_invoice["professionalData"]
            assert "bankAccounts" in pd
            accounts = pd["bankAccounts"]
            assert len(accounts) == 1
            assert accounts[0]["bank"] == "Banco BHD"
            assert accounts[0]["accountNumber"] == "1234567890"
            assert accounts[0]["accountType"] == "Corriente"
            assert accounts[0]["currency"] == "DOP"
            assert accounts[0]["holderName"] == "Empresa Dominicana SRL"
            assert accounts[0]["holderRnc"] == "131880681"
            assert accounts[0]["notes"] == "Notificar a cobros@empresa.com"
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_professional_quotation_edit_loads_bank_accounts(app):
    for p in DB_PATCHES:
        p.start()

    mock_existing_invoice = {
        "id": "draft-quotation-bank-999",
        "invoiceNumber": "COT-000999",
        "status": "Borrador",
        "isQuotation": True,
        "isProfessional": True,
        "clientId": "client-123",
        "clientName": "Acme Corp",
        "clientRNC": "131880681",
        "items": [
            {
                "code": "ITEM1",
                "name": "Servicio A",
                "quantity": 1,
                "price": 1000.0,
                "itbisRate": 0.18,
                "discountRate": 0,
                "subtotal": 1000.0,
                "total": 1180.0
            }
        ],
        "professionalData": {
            "subject": "Cotización de Prueba Cuentas",
            "scopeIncluded": ["Fase 1"],
            "scopeExcluded": [],
            "deliverables": [],
            "timeline": [],
            "paymentSchedule": [],
            "bankAccounts": [
                {
                    "bank": "Banco Popular Dominicano",
                    "accountNumber": "798123456",
                    "accountType": "Corriente",
                    "currency": "DOP",
                    "holderName": "Empresa Dominicana SRL",
                    "holderRnc": "131880681",
                    "notes": "Ref: COT-000999"
                }
            ],
            "validityDays": 30
        }
    }

    try:
        with patch("app.services.db_service.DatabaseService.get_invoice", return_value=mock_existing_invoice), \
             patch("app.web.invoices.check_permission", return_value=True):

            client = app.test_client()
            mock_login(client)

            resp = client.get('/quotations/new/professional?edit=draft-quotation-bank-999')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)

            assert '<div id="wz-initial-data-json" style="display:none;">' in html
            start_tag = '<div id="wz-initial-data-json" style="display:none;">'
            end_tag = '</div>'
            start_idx = html.find(start_tag) + len(start_tag)
            end_idx = html.find(end_tag, start_idx)
            json_str = html[start_idx:end_idx]

            data = json.loads(json_str)
            assert "bankAccounts" in data
            assert len(data["bankAccounts"]) == 1
            account = data["bankAccounts"][0]
            assert account["bank"] == "Banco Popular Dominicano"
            assert account["accountNumber"] == "798123456"
            assert account["accountType"] == "Corriente"
            assert account["currency"] == "DOP"
            assert account["holderName"] == "Empresa Dominicana SRL"
            assert account["notes"] == "Ref: COT-000999"

            # Check that registered bank accounts are passed
            assert '<div id="wz-bank-accounts-data-json" style="display:none;">' in html
            ba_start_tag = '<div id="wz-bank-accounts-data-json" style="display:none;">'
            ba_start_idx = html.find(ba_start_tag) + len(ba_start_tag)
            ba_end_idx = html.find(end_tag, ba_start_idx)
            ba_json_str = html[ba_start_idx:ba_end_idx]
            registered_banks = json.loads(ba_json_str)
            assert len(registered_banks) == 2
            assert any(b["accountNumber"] == "798123456" for b in registered_banks)
            assert any(b["accountNumber"] == "987654321" for b in registered_banks)
    finally:
        for p in DB_PATCHES:
            p.stop()


def test_portal_document_detail_renders_bank_accounts(app):
    from flask import render_template
    with app.test_request_context():
        invoice = {
            "invoiceNumber": "COT-001234",
            "isQuotation": True,
            "isProfessional": True,
            "total": 100000.0,
            "subtotal": 100000.0,
            "netPayable": 100000.0,
            "totalITBIS": 0.0,
            "items": [],
            "professionalData": {
                "subject": "Portal Test",
                "bankAccounts": [
                    {
                        "bank": "Banco BHD",
                        "accountNumber": "0987654321",
                        "accountType": "Corriente",
                        "currency": "DOP",
                        "holderName": "Empresa Portal SRL",
                        "holderRnc": "131880681",
                        "notes": "Indicar referencia al transferir"
                    }
                ]
            }
        }
        company = {
            "companyName": "Empresa Portal SRL",
            "companyRNC": "131880681"
        }
        rendered = render_template(
            'portal/document_detail.html',
            invoice=invoice,
            company=company,
            client={"razonSocial": "Cliente Portal"},
            branch=None,
            today_str="2026-10-27",
            owner_uid="test-owner",
            sandbox=True,
            paypal_configured=False,
            comments=[]
        )
        assert "Cuentas Bancarias para Depósito o Transferencia:" in rendered
        assert "Banco BHD" in rendered
        assert "0987654321" in rendered
        assert "Empresa Portal SRL" in rendered
        assert "Indicar referencia al transferir" in rendered


def test_invoice_detail_renders_bank_accounts(app):
    from flask import render_template
    with app.test_request_context():
        invoice = {
            "id": "inv-detail-123",
            "invoiceNumber": "COT-005678",
            "isQuotation": True,
            "isProfessional": True,
            "status": "Borrador",
            "date": "2026-10-27",
            "dueDate": "2026-11-27",
            "clientName": "Cliente Test",
            "clientRNC": "131880681",
            "total": 50000.0,
            "subtotal": 50000.0,
            "netPayable": 50000.0,
            "totalPaid": 0.0,
            "remainingBalance": 50000.0,
            "totalITBIS": 0.0,
            "items": [],
            "professionalData": {
                "bankAccounts": [
                    {
                        "bank": "Banco Santa Cruz",
                        "accountNumber": "555666777",
                        "accountType": "Ahorros",
                        "currency": "USD",
                        "holderName": "Titular Test",
                        "holderRnc": "40200000000",
                        "notes": "Transferencia en USD"
                    }
                ]
            }
        }
        company = {
            "companyName": "Empresa Test",
            "companyRNC": "131880681"
        }
        rendered = render_template(
            'invoices/detail.html',
            invoice=invoice,
            company=company,
            client_email="cliente@test.com",
            client_phone="809-555-5555",
            show_actions=True,
            can_edit=True,
            branches=[],
            projects=[],
            cost_centers=[],
            price_lists=[],
            payment_agreements=[],
            payment_receipts=[],
            audit_logs=[],
            comments=[]
        )
        assert "Cuentas Bancarias para Depósito / Transferencia:" in rendered
        assert "Banco Santa Cruz" in rendered
        assert "555666777" in rendered
        assert "Titular Test" in rendered
        assert "40200000000" in rendered

