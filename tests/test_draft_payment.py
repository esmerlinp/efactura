from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from contextlib import ExitStack
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
    'posEnabled': True,
    'productionEnabled': True,
    'sandboxEnabled': True,
    'sandboxIndefinite': True,
    'planId': 'plan123',
    'country': 'DO',
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
        'gastos': {'enabled': True},
        'inventario': {'enabled': True},
        'contabilidad': {'enabled': True},
        'bancos': {'enabled': True},
        'cxc': {'enabled': True},
        'cxp': {'enabled': True},
    }}),
)

def mock_login(client, owner_uid='test-owner', company_id='test-owner'):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': owner_uid,
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canInvoice': True, 'canManageCXC': True},
        }
        sess['selected_company_id'] = company_id
        sess['selected_owner_uid'] = owner_uid
        sess['company_country'] = 'DO'
        sess['company_modules'] = {
            'e_cf': {'enabled': True},
            'reportes': {'enabled': True},
            'gastos': {'enabled': True},
            'inventario': {'enabled': True},
            'contabilidad': {'enabled': True},
            'bancos': {'enabled': True},
            'cxc': {'enabled': True},
            'cxp': {'enabled': True},
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

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoice', return_value=mock_invoice))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_cost_centers', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=[]))
         
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

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoice', return_value=mock_invoice))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_cost_centers', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=[]))
        mock_register = stack.enter_context(patch('app.services.db_service.DatabaseService.register_invoice_payment'))
         
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

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_company_profile', return_value=mock_company))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoice', return_value=mock_invoice))
        stack.enter_context(patch('app.web.invoices.check_document_limit_exceeded', return_value=(False, None)))
        stack.enter_context(patch('app.services.db_service.DatabaseService.consume_next_sequence', return_value=("E320000000002", "log-1")))
        stack.enter_context(patch('app.services.ecf_emission.EcfEmissionService.emit_electronic_comprobante', return_value=mock_dgii_response))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_sequence_logs', return_value=[]))
        stack.enter_context(patch('app.services.dgii.DGIIService.check_tolerancia_cuadratura', return_value={"within_tolerance": True, "warnings": []}))
        mock_audit = stack.enter_context(patch('app.services.audit_service.AuditService.log_from_request'))
        mock_save = stack.enter_context(patch('app.services.db_service.DatabaseService.save_invoice'))
         
        resp = client.post('/invoices/inv-1/sign')
        assert resp.status_code == 302
        mock_save.assert_called_once()
        saved_invoice = mock_save.call_args[0][2]
        assert saved_invoice["status"] == "Cobrada"
        assert saved_invoice["encf"] == "E320000000002"

def test_invoice_preview_success(client):
    mock_login(client)
    
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_items', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_clients', return_value=[]))
        
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
    
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        
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

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_invoices))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_sequence_logs', return_value=[]))
         
        resp = client.get('/invoices')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'NCF/Número' in html
        assert 'Cliente' in html
        assert 'Creación' in html
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

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoices', return_value=mock_notes))
         
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


def test_pay_rejected_invoice_blocked(client):
    """Verifica que no se permita registrar cobro a una factura rechazada por la DGII."""
    mock_login(client)
    mock_invoice = {
        "id": "inv-rejected",
        "status": "Emitida",
        "subtotal": 1000.00,
        "totalITBIS": 0.0,
        "netPayable": 1000.00,
        "remainingBalance": 1000.00,
        "totalPaid": 0.0,
        "invoiceNumber": "E3100000001",
        "encf": "E3100000001",
        "ecfType": "Factura de Crédito Fiscal (E31)",
        "dgiiStatus": "REJECTED",
        "isQuotation": False,
        "clientName": "Cliente Rechazado",
        "clientRNC": "131880681",
        "date": "2026-10-07 10:00:00",
        "dueDate": "2026-10-07",
        "total": 1000.00,
        "retainedISR": 0.0,
        "retainedITBIS": 0.0,
        "items": []
    }

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoice', return_value=mock_invoice))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_team_members', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoice_payments', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_invoice_comments', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_bank_accounts', return_value=[]))
        mock_register = stack.enter_context(patch('app.services.db_service.DatabaseService.register_invoice_payment'))

        # 1. GET /invoices/<id>/pay/advanced debe redirigir al detalle con error
        resp_get = client.get('/invoices/inv-rejected/pay/advanced', follow_redirects=True)
        assert resp_get.status_code == 200
        html = resp_get.data.decode('utf-8')
        assert 'rechazado por la DGII' in html
        mock_register.assert_not_called()

        # 2. POST /invoices/<id>/pay/advanced debe ser bloqueado
        resp_post_adv = client.post('/invoices/inv-rejected/pay/advanced', data={
            "bankAccountId": "bank-1",
            "paymentDate": "2026-10-07",
            "paymentMethod": "Efectivo",
            "monto_recibido": "1000.00"
        }, follow_redirects=True)
        assert 'rechazado por la DGII' in resp_post_adv.data.decode('utf-8')
        mock_register.assert_not_called()

        # 3. POST /invoices/<id>/pay debe ser bloqueado
        resp_pay = client.post('/invoices/inv-rejected/pay', data={
            "amount": "1000.00",
            "paymentMethod": "Efectivo"
        }, follow_redirects=True)
        assert 'rechazado por la DGII' in resp_pay.data.decode('utf-8')
        mock_register.assert_not_called()


def test_db_service_blocks_rejected_invoice_payment():
    """Verifica que DatabaseService.register_invoice_payment lance ValueError si dgiiStatus es REJECTED."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "status": "Emitida",
        "netPayable": 5000.0,
        "remainingBalance": 5000.0,
        "totalPaid": 0.0,
        "dgiiStatus": "REJECTED"
    }

    with patch('app.services.db_service.firebase_initialized', True), \
         patch('app.services.db_service._company_coll') as mock_coll:
        mock_coll.return_value.document.return_value.get.return_value = mock_doc

        import pytest
        with pytest.raises(ValueError, match="rechazado por la DGII"):
            DatabaseService.register_invoice_payment(
                "owner-1", "inv-1", {"amount": 1000.0, "paymentMethod": "Efectivo"}, sandbox=True
            )


def test_save_draft_invoice_with_exempt_item(client):
    mock_login(client)
    
    saved_invoice_dict = {}
    def fake_save_invoice(owner_uid, invoice_id, invoice_dict, company_id=None, sandbox=True):
        saved_invoice_dict.update(invoice_dict)
        return invoice_id

    exempt_item = {
        "id": "prod-exento-1",
        "name": "Servicio de Capacitación Exento",
        "code": "CAP-01",
        "price": 10000.0,
        "itbisRate": 0.0,
        "isActive": True
    }

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_items', return_value=[exempt_item]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_clients', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_warehouses', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_price_lists', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.save_invoice', side_effect=fake_save_invoice))
        stack.enter_context(patch('app.services.audit_service.AuditService.log_from_request'))

        post_data = {
            "action": "guardar",
            "ecfType": "Factura de Consumo (E32)",
            "clientId": "client-1",
            "clientName": "Juan Perez",
            "clientRNC": "00100000000",
            "currency": "DOP",
            "paymentMethod": "Efectivo",
            "dueDate": "2026-10-12",
            "items[0][catalog_id]": "prod-exento-1",
            "items[0][name]": "Servicio de Capacitación Exento",
            "items[0][price]": "10000.00",
            "items[0][quantity]": "1",
            "items[0][itbisRate]": "0.0",
            "items[0][discountRate]": "0.0"
        }

        resp = client.post('/invoices/new', data=post_data, follow_redirects=False)
        assert resp.status_code == 302
        assert '/invoices/' in resp.headers['Location']

        assert saved_invoice_dict["status"] == "Borrador"
        assert saved_invoice_dict["totalITBIS"] == 0.0
        assert saved_invoice_dict["montoExento"] == 10000.0
        assert saved_invoice_dict["subtotal"] == 10000.0
        assert saved_invoice_dict["total"] == 10000.0
        assert saved_invoice_dict["items"][0]["itbisRate"] == 0.0
        assert saved_invoice_dict["items"][0]["itbisAmount"] == 0.0


def test_save_draft_invoice_with_exempt_item_from_catalog_fallback(client):
    mock_login(client)
    
    saved_invoice_dict = {}
    def fake_save_invoice(owner_uid, invoice_id, invoice_dict, company_id=None, sandbox=True):
        saved_invoice_dict.update(invoice_dict)
        return invoice_id

    exempt_item = {
        "id": "prod-exento-2",
        "name": "Pan Integral Exento",
        "code": "PAN-01",
        "price": 200.0,
        "itbisRate": 0.0,
        "isActive": True
    }

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_items', return_value=[exempt_item]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_clients', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_warehouses', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.get_price_lists', return_value=[]))
        stack.enter_context(patch('app.services.db_service.DatabaseService.save_invoice', side_effect=fake_save_invoice))
        stack.enter_context(patch('app.services.audit_service.AuditService.log_from_request'))

        post_data = {
            "action": "guardar",
            "ecfType": "Factura de Consumo (E32)",
            "clientId": "client-1",
            "clientName": "Maria Gomez",
            "clientRNC": "00100000000",
            "currency": "DOP",
            "paymentMethod": "Efectivo",
            "dueDate": "2026-10-12",
            "items[0][catalog_id]": "prod-exento-2",
            "items[0][name]": "Pan Integral Exento",
            "items[0][price]": "200.00",
            "items[0][quantity]": "2",
            "items[0][discountRate]": "0.0"
        }

        resp = client.post('/invoices/new', data=post_data, follow_redirects=False)
        assert resp.status_code == 302
        assert '/invoices/' in resp.headers['Location']

        assert saved_invoice_dict["status"] == "Borrador"
        assert saved_invoice_dict["totalITBIS"] == 0.0
        assert saved_invoice_dict["montoExento"] == 400.0
        assert saved_invoice_dict["subtotal"] == 400.0
        assert saved_invoice_dict["total"] == 400.0
        assert saved_invoice_dict["items"][0]["itbisRate"] == 0.0
        assert saved_invoice_dict["items"][0]["itbisAmount"] == 0.0


def test_new_invoice_excludes_inactive_catalog_items(client):
    mock_login(client)

    active_item = {
        "id": "prod-active",
        "name": "Producto activo",
        "code": "ACT-01",
        "price": 100.0,
        "itbisRate": 0.18,
        "isActive": True,
    }
    inactive_item = {
        "id": "prod-inactive",
        "name": "Producto inactivo",
        "code": "INA-01",
        "price": 200.0,
        "itbisRate": 0.18,
        "isActive": False,
    }

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        stack.enter_context(patch(
            'app.services.db_service.DatabaseService.get_items',
            return_value=[active_item, inactive_item],
        ))
        stack.enter_context(patch(
            'app.services.db_service.DatabaseService.get_clients',
            return_value=[],
        ))
        stack.enter_context(patch(
            'app.services.db_service.DatabaseService.get_warehouses',
            return_value=[],
        ))
        stack.enter_context(patch(
            'app.services.db_service.DatabaseService.get_price_lists',
            return_value=[],
        ))

        response = client.get('/invoices/new')

    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Producto activo' in html
    assert 'Producto inactivo' not in html


def test_register_invoice_payment_updates_selected_bank_account_with_company_scope():
    """El cobro debe acreditar el saldo en la cuenta bancaria seleccionada,
    guardándola en el ámbito de la empresa activa (company_id)."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "status": "Emitida",
        "documentType": "invoice",
        "netPayable": 1000.0,
        "remainingBalance": 1000.0,
        "totalPaid": 0.0,
        "invoiceNumber": "E3100000001",
        "isQuotation": False,
        "dgiiStatus": "ACCEPTED",
        "isSyncedWithDGII": True,
        "stockReduced": True,
        "items": [],
    }
    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_doc

    saved = {}

    def fake_save_bank_account(owner_uid, account_id, account_dict, sandbox=True, company_id=None):
        saved["account_id"] = account_id
        saved["company_id"] = company_id
        saved["currentBalance"] = account_dict["currentBalance"]
        return account_dict

    with patch('app.services.db_service.firebase_initialized', True), \
         patch('app.services.db_service._company_coll') as mock_coll, \
         patch('app.services.db_service.DatabaseService.get_bank_account',
               return_value={"id": "bank-1", "currentBalance": 500.0}), \
         patch('app.services.db_service.DatabaseService.save_bank_account',
               side_effect=fake_save_bank_account):
        mock_coll.return_value.document.return_value = mock_ref

        DatabaseService.register_invoice_payment(
            "owner-1",
            "inv-1",
            {
                "amount": 300.0,
                "paymentMethod": "Transferencia",
                "bank": "Banco Popular",
                "referenceNumber": "REF-1",
                "bankAccountId": "bank-1",
            },
            sandbox=True,
            company_id="company-1",
        )

    assert saved["account_id"] == "bank-1"
    assert saved["company_id"] == "company-1"
    assert saved["currentBalance"] == 800.0


def test_bank_detail_reads_payments_without_collection_group_indexes(client):
    """El detalle de banco obtiene pagos desde cada factura/gasto y no usa
    consultas collection_group que requieran índices de Firestore."""
    from app.web import banks as banks_module

    account_id = "bank-1"
    invoice = {"id": "inv-1", "invoiceNumber": "E3100000001", "clientName": "Cliente Demo"}
    expense = {"id": "exp-1", "concept": "Compra Demo"}
    invoice_payment = {
        "id": "pmt-1", "amount": 300.0, "paymentDate": "2026-11-01",
        "referenceNumber": "REF-1", "bankAccountId": account_id,
    }
    cxp_payment = {
        "id": "cxp-1", "amount": 125.0, "paymentDate": "2026-11-02",
        "bankAccountId": account_id,
    }
    account = {"id": account_id, "name": "Cuenta Operativa", "type": "banco", "currentBalance": 800.0}

    with patch.object(
        banks_module.DatabaseService, 'get_invoices', return_value=[invoice]
    ), patch.object(
        banks_module.DatabaseService, 'get_invoice_payments', return_value=[invoice_payment]
    ), patch.object(
        banks_module.DatabaseService, 'get_expenses', return_value=[expense]
    ), patch.object(
        banks_module.DatabaseService, 'get_cxp_payments', return_value=[cxp_payment]
    ):
        transactions = banks_module._load_account_payment_transactions(
            "test-owner", account_id, True, "company-1"
        )

    assert transactions == [
        {
            "date": "2026-11-01",
            "type": "income",
            "concept": "Pago E3100000001 — Cliente Demo",
            "amount": 300.0,
            "reference": "REF-1",
            "invoiceId": "inv-1",
        },
        {
            "date": "2026-11-02",
            "type": "expense",
            "concept": "Pago CxP: Compra Demo",
            "amount": -125.0,
            "reference": "",
            "expenseId": "exp-1",
            "invoiceId": "",
        },
    ]


def test_bank_detail_includes_proforma_payment():
    from app.web import banks as banks_module

    payment = {
        "id": "pmt-proforma",
        "amount": 450.0,
        "paymentDate": "2026-11-03",
        "referenceNumber": "PRO-REF",
        "bankAccountId": "bank-1",
    }
    with patch.object(
        banks_module.DatabaseService, 'get_invoices', return_value=[{
            "id": "pro-1",
            "invoiceNumber": "PRO-0001",
            "clientName": "Cliente Proforma",
            "documentType": "proforma",
        }]
    ), patch.object(
        banks_module.DatabaseService, 'get_invoice_payments', return_value=[payment]
    ):
        transactions = banks_module._load_account_payment_transactions(
            "test-owner", "bank-1", True, "company-1"
        )

    assert transactions == [{
        "date": "2026-11-03",
        "type": "income",
        "concept": "Pago PRO-0001 — Cliente Proforma",
        "amount": 450.0,
        "reference": "PRO-REF",
        "invoiceId": "pro-1",
        "documentType": "proforma",
    }]


def test_bank_detail_includes_proforma_collection():
    from app.web import banks as banks_module

    proforma = {
        "id": "proforma-337272",
        "invoiceNumber": "PRO-337272",
        "clientName": "Colectivo Salud Mental (COSALUME)",
        "documentType": "proforma",
        "isQuotation": True,
    }
    payment = {
        "amount": 17000.0,
        "paymentDate": "2026-11-16",
        "referenceNumber": "Recibo de Caja No. 1",
        "bankAccountId": "961b1f6b-cc43-4bb6-badc-af176b3659be",
    }

    with patch.object(
        banks_module.DatabaseService, 'get_invoices', return_value=[proforma]
    ) as get_invoices, patch.object(
        banks_module.DatabaseService, 'get_invoice_payments', return_value=[payment]
    ):
        transactions = banks_module._load_account_payment_transactions(
            "test-owner",
            "961b1f6b-cc43-4bb6-badc-af176b3659be",
            False,
            "company-1",
        )

    get_invoices.assert_called_once_with(
        "test-owner",
        sandbox=False,
        include_all=True,
        company_id="company-1",
    )
    assert transactions[0]["concept"] == "Pago PRO-337272 — Colectivo Salud Mental (COSALUME)"
    assert transactions[0]["amount"] == 17000.0
    assert transactions[0]["type"] == "income"


def test_bank_detail_includes_cxp_payment_as_expense():
    from app.web import banks as banks_module

    payment = {
        "id": "cxp-2",
        "amount": 275.0,
        "paymentDate": "2026-11-04",
        "bankAccountId": "bank-1",
    }
    with patch.object(
        banks_module.DatabaseService, 'get_invoices', return_value=[]
    ), patch.object(
        banks_module.DatabaseService, 'get_expenses', return_value=[{
            "id": "exp-2", "concept": "Factura proveedor", "bankAccountId": ""
        }]
    ), patch.object(
        banks_module.DatabaseService, 'get_cxp_payments', return_value=[payment]
    ):
        transactions = banks_module._load_account_payment_transactions(
            "test-owner", "bank-1", True, "company-1"
        )

    assert transactions == [{
        "date": "2026-11-04",
        "type": "expense",
        "concept": "Pago CxP: Factura proveedor",
        "amount": -275.0,
        "reference": "",
        "expenseId": "exp-2",
        "invoiceId": "",
    }]


def test_bank_detail_includes_supplier_invoice_payment():
    from app.web import banks as banks_module

    supplier_payment = {
        "id": "supplier-pmt-1",
        "amount": 12750.0,
        "paymentDate": "2026-11-17",
        "reference": "FI-REF-1",
        "bankAccountId": "bank-1",
    }
    supplier_invoice = {
        "id": "supplier-inv-1",
        "invoiceNumber": "FI-2026-0001",
        "supplierName": "Dargys Sanchez Martinez",
    }
    with patch.object(
        banks_module.DatabaseService, 'get_invoices', return_value=[]
    ), patch.object(
        banks_module.DatabaseService, 'get_expenses', return_value=[]
    ), patch.object(
        banks_module.SupplierInvoiceService, 'get_all', return_value=[supplier_invoice]
    ), patch.object(
        banks_module.SupplierInvoiceService, 'get_payments', return_value=[supplier_payment]
    ):
        transactions = banks_module._load_account_payment_transactions(
            "test-owner", "bank-1", True, "company-1"
        )

    assert transactions == [{
        "date": "2026-11-17",
        "type": "expense",
        "concept": "Pago proveedor FI-2026-0001 — Dargys Sanchez Martinez",
        "amount": -12750.0,
        "reference": "FI-REF-1",
        "expenseId": "supplier-inv-1",
        "invoiceId": "",
    }]


def test_bank_detail_base_data_is_cached():
    from app.web import banks as banks_module

    cache = MagicMock()
    cache.get.return_value = None
    cache_service = MagicMock()
    cache_service.get_cache.return_value = cache
    expected = [{"date": "2026-11-01", "type": "income", "amount": 100.0}]

    with patch.object(
        banks_module, '_load_account_payment_transactions', return_value=expected
    ) as load_payments, patch.object(
        banks_module.DatabaseService, 'get_expenses', return_value=[]
    ), patch.object(
        banks_module.DatabaseService, 'get_bank_transfers', return_value=[]
    ):
        first = banks_module._load_bank_detail_data(
            "owner", "bank-1", True, "company-1", cache_service
        )
        cache.get.return_value = expected
        second = banks_module._load_bank_detail_data(
            "owner", "bank-1", True, "company-1", cache_service
        )

    assert first == expected
    assert second == expected
    assert cache.set.call_count == 1
    load_payments.assert_called_once()


def test_bank_detail_uses_persisted_ledger_before_legacy_sources():
    from app.web import banks as banks_module

    cache = MagicMock()
    cache.get.return_value = None
    cache_service = MagicMock()
    cache_service.get_cache.return_value = cache
    ledger = [{
        "createdAt": "2026-11-01T12:00:00+00:00",
        "sourceType": "invoice_payment",
        "sourceId": "payment-1",
        "description": "Cobro E3100000001",
        "amount": 250.0,
    }]

    with patch.object(
        banks_module.DatabaseService, 'get_bank_movements', return_value=ledger
    ), patch.object(
        banks_module, '_load_account_payment_transactions'
    ) as load_payments:
        result = banks_module._load_bank_detail_data(
            "owner", "bank-1", True, "company-1", cache_service
        )

    assert result[0]["paymentId"] == "payment-1"
    assert result[0]["amount"] == 250.0
    load_payments.assert_not_called()


def test_persisted_bank_movement_keeps_filterable_origin():
    from app.web import banks as banks_module

    cache = MagicMock()
    cache.get.return_value = None
    cache_service = MagicMock()
    cache_service.get_cache.return_value = cache
    ledger = [{
        "createdAt": "2026-11-01T12:00:00+00:00",
        "sourceType": "bank_transfer",
        "sourceId": "transfer-1",
        "description": "Transferencia interna",
        "amount": -100.0,
        "type": "transfer_out",
    }]

    with patch.object(
        banks_module.DatabaseService, 'get_bank_movements', return_value=ledger
    ):
        result = banks_module._load_bank_detail_data(
            "owner", "bank-1", True, "company-1", cache_service
        )

    assert result[0]["type"] == "transfer_out"
    assert result[0]["origin"] == "bank_transfer"


def test_movement_date_prefers_payment_date_and_falls_back_to_created_at():
    from app.web import banks as banks_module

    assert banks_module._movement_date({
        "paymentDate": "2026-11-03T10:00:00+00:00",
        "createdAt": "2026-11-04T10:00:00+00:00",
    }) == "2026-11-03"
    assert banks_module._movement_date({
        "createdAt": "2026-11-04T10:00:00+00:00",
    }) == "2026-11-04"


def test_bank_detail_combines_ledger_adjustments_with_legacy_transactions():
    from app.web import banks as banks_module

    cache = MagicMock()
    cache.get.return_value = None
    cache_service = MagicMock()
    cache_service.get_cache.return_value = cache
    ledger = [{
        "createdAt": "2026-11-24T12:00:00+00:00",
        "sourceType": "bank_adjustment",
        "sourceId": "adjustment-1",
        "description": "Ajuste histórico",
        "amount": 25000.0,
        "type": "adjustment",
    }]
    legacy = [{
        "date": "2026-11-20",
        "type": "income",
        "concept": "Cobro histórico",
        "amount": 500.0,
        "reference": "PAY-1",
        "paymentId": "PAY-1",
        "invoiceId": "INV-1",
    }]

    with patch.object(
        banks_module.DatabaseService, 'get_bank_movements', return_value=ledger
    ), patch.object(
        banks_module, '_load_account_payment_transactions', return_value=legacy
    ), patch.object(
        banks_module.DatabaseService, 'get_expenses', return_value=[]
    ), patch.object(
        banks_module.DatabaseService, 'get_bank_transfers', return_value=[]
    ):
        result = banks_module._load_bank_detail_data(
            "owner", "bank-1", True, "company-1", cache_service
        )

    assert {row["concept"] for row in result} == {
        "Ajuste histórico", "Cobro histórico"
    }
