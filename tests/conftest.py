import os
import sys
import json
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('FIREBASE_API_KEY', 'test-firebase-api-key')
os.environ.setdefault('FIELD_ENCRYPTION_KEY', 'wiS1GMquP_CvSrlBn7iOy-CalDQsPt7n1Pg_snPGluk=')
os.environ.setdefault('DGII_SANDBOX_MODE', 'local')
os.environ.setdefault('DGII_ALLOW_SIMULATION', 'true')
os.environ.setdefault('DGII_SIGNING_MODE', 'mock')

# Mock native-ext modules BEFORE any app module imports them
# The entire cryptography module tree must be mocked because:
#   1. _rust.abi3.so has dlopen arch mismatch on this system
#   2. google.cloud.firestore → google.auth.crypt.es → cryptography.hazmat.primitives.asymmetric.utils
_sys_modules_patch = patch.dict('sys.modules', {
    'cryptography': MagicMock(),
    'cryptography.fernet': MagicMock(),
    'cryptography.exceptions': MagicMock(),
    'cryptography.hazmat': MagicMock(),
    'cryptography.hazmat.backends': MagicMock(),
    'cryptography.hazmat.bindings': MagicMock(),
    'cryptography.hazmat.bindings._rust': MagicMock(),
    'cryptography.hazmat.primitives': MagicMock(),
    'cryptography.hazmat.primitives.asymmetric': MagicMock(),
    'cryptography.hazmat.primitives.asymmetric.utils': MagicMock(),
    'cryptography.hazmat.primitives.asymmetric.padding': MagicMock(),
    'cryptography.hazmat.primitives.asymmetric.rsa': MagicMock(),
    'cryptography.hazmat.primitives.asymmetric.ec': MagicMock(),
    'cryptography.hazmat.primitives.ciphers': MagicMock(),
    'cryptography.hazmat.primitives.hashes': MagicMock(),
    'cryptography.hazmat.primitives.kdf': MagicMock(),
    'cryptography.hazmat.primitives.serialization': MagicMock(),
    'cryptography.x509': MagicMock(),
    'firebase_admin': MagicMock(),
    'firebase_admin.credentials': MagicMock(),
    'firebase_admin.firestore': MagicMock(),
    'google.cloud': MagicMock(),
    'google.cloud.firestore': MagicMock(),
    'google.cloud.firestore_v1': MagicMock(),
})
_sys_modules_patch.start()


@pytest.fixture(scope='session')
def app():
    from app import create_app
    application = create_app()
    application.config['TESTING'] = True
    application.config['WTF_CSRF_ENABLED'] = False
    application.config['RATELIMIT_ENABLED'] = False
    return application


@pytest.fixture
def app_context(app):
    with app.app_context():
        yield


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sample_company_profile():
    return {
        "companyRNC": "132-10912-2",
        "companyName": "Tecnología Dominicana SRL",
        "tradeName": "TecnoDom",
        "companyAddress": "Av. Winston Churchill #1012, Santo Domingo",
        "companyPhone": "809-555-0199",
        "companyEmail": "facturacion@tecnodom.com.do",
        "municipality": "Santo Domingo Este",
        "province": "Santo Domingo",
        "regimenFiscal": "ordinary",
        "certificateContent": "",
        "certificatePassword": "",
        "country": "DO",
    }


@pytest.fixture
def sample_invoice_items():
    return [
        {
            "id": "item-1",
            "code": "ART-001",
            "name": "Laptop Pro",
            "type": "Bien",
            "price": 50000.00,
            "quantity": 2,
            "unit": "Unidad",
            "itbisRate": 0.18,
            "discountRate": 0.0,
            "codigoImpuesto": "",
            "tasaImpuestoAdicional": 0.0,
            "gradosAlcohol": 0.0,
            "cantidadReferencia": 0.0,
            "subcantidad": 1.0,
            "precioReferencia": 0.0,
        },
        {
            "id": "item-2",
            "code": "SERV-001",
            "name": "Consultoría TI",
            "type": "Servicio",
            "price": 15000.00,
            "quantity": 1,
            "unit": "Unidad",
            "itbisRate": 0.18,
            "discountRate": 0.0,
            "codigoImpuesto": "",
            "tasaImpuestoAdicional": 0.0,
            "gradosAlcohol": 0.0,
            "cantidadReferencia": 0.0,
            "subcantidad": 1.0,
            "precioReferencia": 0.0,
        },
    ]


@pytest.fixture
def sample_invoice_dict(sample_company_profile, sample_invoice_items):
    from app.services.dgii import DGIIService
    calcs = DGIIService.calculate_invoice_totals(sample_invoice_items)
    return {
        "ecfType": "Factura de Consumo (E32)",
        "clientRNC": "000000000",
        "clientName": "Consumidor Final",
        "currency": "DOP",
        "paymentMethod": "Efectivo",
        "subtotal": calcs["subtotal"],
        "totalITBIS": calcs["total_itbis"],
        "totalISCEspecifico": calcs["total_isc_especifico"],
        "totalISCAdValorem": calcs["total_isc_advalorem"],
        "totalOtrosImpuestos": calcs["total_otros_impuestos"],
        "total": calcs["total"],
        "retainedISR": calcs["retained_isr"],
        "retainedITBIS": calcs["retained_itbis"],
        "netPayable": calcs["net_payable"],
        "discountRate": 0.0,
        "items": calcs["items"],
    }
