from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import pytest
import json
from app.services.db_service import DatabaseService

MOCK_USER_PROFILE = {
    'uid': 'test-uid',
    'email': 'admin@test.com',
    'name': 'Admin',
    'role': 'owner',
    'ownerUID': 'test-owner',
    'status': 'active',
    'permissions': {'canInvoice': True, 'canManageCXC': True}
}

MOCK_COMPANY = {
    'companyRNC': '132-10912-2',
    'companyName': 'Test Co',
    'configured': True,
}

def mock_login(client, owner_uid='test-owner'):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': owner_uid,
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canInvoice': True, 'canManageCXC': True},
        }
        sess['is_sandbox_mode'] = True

@patch('app.services.db_service.firebase_initialized', True)
@patch('app.services.db_service.db_firestore')
def test_db_service_draft_payment(mock_firestore):
    mock_doc_ref = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = True
    
    mock_invoice_data = {
        "status": "Borrador",
        "netPayable": 15000.00,
        "remainingBalance": 15000.00,
        "totalPaid": 0.0,
        "invoiceNumber": "B0100000002",
        "isQuotation": False,
        "clientName": "Consumidor Final"
    }
    
    mock_doc.to_dict.return_value = mock_invoice_data
    mock_doc_ref.get.return_value = mock_doc
    mock_firestore.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref

    payment_dict = {
        "paymentMethod": "Efectivo",
        "bank": "Caja Efectivo",
        "referenceNumber": "Pago en Efectivo",
        "paymentDate": datetime.now(timezone.utc).isoformat(),
        "registeredBy": "admin@test.com",
        "amount": 15000.00,
        "bankAccountId": "acc-1"
    }

    DatabaseService.register_invoice_payment("test-owner", "inv-1", payment_dict, sandbox=True)

    mock_doc_ref.update.assert_called_once()
    called_args = mock_doc_ref.update.call_args[0][0]
    
    assert called_args["status"] == "Pagado pero no emitido"
    assert called_args["totalPaid"] == 15000.00
    assert called_args["remainingBalance"] == 0.0

def test_pay_advanced_route_get(client):
    mock_login(client)
    mock_invoice = {
        "id": "inv-1",
        "status": "Borrador",
        "netPayable": 15000.00,
        "remainingBalance": 15000.00,
        "totalPaid": 0.0,
        "invoiceNumber": "B0100000002",
        "isQuotation": False,
        "clientName": "Consumidor Final",
        "dueDate": "2026-07-05",
        "total": 15000.00
    }

    with patch('app.services.db_service.DatabaseService.get_invoice', return_value=mock_invoice), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_cost_centers', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=[]):
         
        resp = client.get('/invoices/inv-1/pay/advanced')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Nuevo pago recibido' in html
        assert 'Recibo de caja' in html
        assert 'Consumidor Final' in html
        assert 'B0100000002' in html

def test_pay_advanced_route_post(client):
    mock_login(client)
    mock_invoice = {
        "id": "inv-1",
        "status": "Borrador",
        "netPayable": 15000.00,
        "remainingBalance": 15000.00,
        "totalPaid": 0.0,
        "invoiceNumber": "B0100000002",
        "isQuotation": False,
        "clientName": "Consumidor Final",
        "dueDate": "2026-07-05",
        "total": 15000.00
    }

    with patch('app.services.db_service.DatabaseService.get_invoice', return_value=mock_invoice), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_cost_centers', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=[]), \
         patch('app.services.db_service.DatabaseService.register_invoice_payment') as mock_register:
         
        post_data = {
            "bankAccountId": "bank-1",
            "paymentDate": "2026-07-05",
            "paymentMethod": "Efectivo",
            "costCenterId": "cc-1",
            "incomeType": "Pago a factura de cliente",
            "monto_recibido": "15000.00",
            "retenciones": "0.00",
            "notes": "Test notes"
        }
        
        resp = client.post('/invoices/inv-1/pay/advanced', data=post_data)
        assert resp.status_code == 302
        mock_register.assert_called_once()
        payment_dict = mock_register.call_args[0][2]
        assert payment_dict["amount"] == 15000.00
        assert payment_dict["paymentMethod"] == "Efectivo"
        assert payment_dict["notes"] == "Test notes"

def test_sign_invoice_with_payment(client):
    mock_login(client)
    mock_invoice = {
        "id": "inv-1",
        "status": "Pagado pero no emitido",
        "netPayable": 15000.00,
        "remainingBalance": 0.0,
        "totalPaid": 15000.00,
        "invoiceNumber": "B0100000002",
        "isQuotation": False,
        "clientName": "Consumidor Final",
        "dueDate": "2026-07-05",
        "total": 15000.00,
        "ecfType": "Factura de Consumo (E32)",
        "clientRNC": "000000000",
        "currency": "DOP",
        "paymentMethod": "Efectivo",
        "items": []
    }
    
    mock_company = MOCK_COMPANY.copy()
    mock_company["certificateContent"] = "fake-cert"
    mock_company["certificatePassword"] = "fake-pass"
    mock_company["configured"] = True
    
    mock_dgii_response = {
        "success": True,
        "trackId": "fake-track-id",
        "xmlSignature": "fake-xml-signature",
        "encf": "E320000000002",
        "mode": "API",
        "status": "ACCEPTED"
    }

    with patch('app.services.db_service.DatabaseService.get_invoice', return_value=mock_invoice), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=mock_company), \
         patch('app.web.invoices.check_document_limit_exceeded', return_value=(False, None)), \
         patch('app.services.db_service.DatabaseService.consume_next_sequence', return_value=("E320000000002", "log-1")), \
         patch('app.services.ecf_emission.EcfEmissionService.emit_electronic_comprobante', return_value=mock_dgii_response), \
         patch('app.services.db_service.DatabaseService.get_sequence_logs', return_value=[]), \
         patch('app.services.dgii.DGIIService.check_tolerancia_cuadratura', return_value={"within_tolerance": True, "warnings": []}), \
         patch('app.services.audit_service.AuditService.log_from_request') as mock_audit, \
         patch('app.services.db_service.DatabaseService.save_invoice') as mock_save:
         
        resp = client.post('/invoices/inv-1/sign')
        assert resp.status_code == 302
        mock_save.assert_called_once()
        saved_invoice = mock_save.call_args[0][2]
        assert saved_invoice["status"] == "Cobrada"
        assert saved_invoice["encf"] == "E320000000002"

def test_invoice_preview_success(client):
    mock_login(client)
    
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_items', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_clients', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]):
        
        post_data = {
            "ecfType": "Factura de Consumo (E32)",
            "clientId": "",
            "clientRNC": "000000000",
            "currency": "DOP",
            "paymentMethod": "Efectivo",
            "dueDate": "2026-07-05",
            "items[0][name]": "Laptop Pro",
            "items[0][price]": "50000.00",
            "items[0][quantity]": "1",
            "items[0][itbisRate]": "0.18",
            "items[0][discountRate]": "0.0"
        }
        
        resp = client.post('/invoices/preview', data=post_data)
        assert resp.status_code == 200
        assert resp.content_type in ['text/html; charset=utf-8', 'application/pdf']

def test_invoice_preview_no_items(client):
    mock_login(client)
    
    with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY):
        
        post_data = {
            "ecfType": "Factura de Consumo (E32)",
            "clientId": "",
            "clientRNC": "000000000",
            "currency": "DOP",
            "paymentMethod": "Efectivo",
            "dueDate": "2026-07-05"
        }
        
        resp = client.post('/invoices/preview', data=post_data)
        assert resp.status_code == 400
        assert b"Debes" in resp.data

def test_list_invoices_grid(client):
    mock_login(client)
    mock_invoices = [
        {
            "id": "inv-1",
            "invoiceNumber": "B0100000002",
            "isQuotation": False,
            "clientName": "Consumidor Final",
            "date": "2026-07-05 12:00:00",
            "dueDate": "2026-07-05",
            "total": 15000.00,
            "netPayable": 15000.00,
            "remainingBalance": 15000.00,
            "totalPaid": 0.0,
            "status": "Borrador",
            "encf": ""
        },
        {
            "id": "inv-2",
            "invoiceNumber": "B0100000001",
            "isQuotation": False,
            "clientName": "Consumidor Final",
            "date": "2026-07-04 12:00:00",
            "dueDate": "2026-07-04",
            "total": 15000.00,
            "netPayable": 15000.00,
            "remainingBalance": 0.0,
            "totalPaid": 15000.00,
            "status": "Pagado pero no emitido",
            "encf": ""
        }
    ]

    with patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_sequence_logs', return_value=[]):
         
        resp = client.get('/invoices')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert '# Interno' in html
        assert 'NCF/Número' in html
        assert 'Cliente' in html
        assert 'Creación' in html
        assert 'Vencimiento' in html
        assert 'Total' in html
        assert 'Por cobrar' in html
        assert 'Estado' in html
        assert 'B0100000002' in html
        assert 'B0100000001' in html
        assert 'Consumidor Final' in html
        assert 'Por cobrar' in html
        assert 'Cobrada' in html

def test_list_fiscal_notes_grid(client):
    mock_login(client)
    mock_notes = [
        {
            "id": "note-1",
            "invoiceNumber": "E340000000001",
            "isQuotation": False,
            "clientName": "Consumidor Final",
            "date": "2026-07-05 12:00:00",
            "dueDate": "2026-07-05",
            "total": 5000.00,
            "netPayable": 5000.00,
            "remainingBalance": 5000.00,
            "totalPaid": 0.0,
            "status": "Emitida",
            "encf": "E340000000001",
            "ecfType": "Nota de Crédito (E34)",
            "informationReference": {"ncfModified": "E320000000002"}
        }
    ]

    with patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_notes), \
         patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE), \
         patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
         patch('app.services.db_service.DatabaseService.get_associated_companies', return_value=[]), \
         patch('app.services.db_service.DatabaseService.get_branches', return_value=[]):
         
        resp = client.get('/fiscal-notes')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert '# Interno' in html
        assert 'NCF/Número' in html
        assert 'Cliente' in html
        assert 'NCF Ref.' in html
        assert 'Creación' in html
        assert 'Total' in html
        assert 'Estado' in html
        assert 'E340000000001' in html
        assert 'Consumidor Final' in html
        assert 'E320000000002' in html
        assert 'Emitida' in html
