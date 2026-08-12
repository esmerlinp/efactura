import json
import sys
from flask import Flask
from app import create_app
from app.services.dgii_cert_service import DgiiCertService

app = create_app()
with app.app_context():
    # simulate what happens for group 4
    with open('/Users/esmerlinpaniagua/Develop/e-Factura/e-FacturaWeb/uploads/certificacion/fa3abfc7-5e4c-410b-bde5-b101e1a8ea10/step2/run34/parsed_data.json', 'r') as f:
        parsed_data = json.load(f)
    profile = {"rnc": "133753652", "key_path": "/Users/esmerlinpaniagua/Develop/e-Factura/e-FacturaWeb/uploads/certificacion/test_company/cert.p12", "key_password": "password", "test_mode": True}
    res = DgiiCertService.process_step2_generate(1, profile, parsed_data, False, [4], False, True)
    print(res)
