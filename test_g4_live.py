import json
import sys
import os
from flask import Flask
from app import create_app
from app.services.dgii_cert_service import DgiiCertService
from datetime import datetime

app = create_app()
with app.app_context():
    with open('/Users/esmerlinpaniagua/Develop/e-Factura/e-FacturaWeb/uploads/certificacion/fa3abfc7-5e4c-410b-bde5-b101e1a8ea10/step2/run34/parsed_data.json', 'r') as f:
        parsed_data = json.load(f)
    
    profile = {"rnc": "133753652", "key_path": "/Users/esmerlinpaniagua/Develop/e-Factura/e-FacturaWeb/uploads/certificacion/test_company/cert.p12", "key_password": "password", "test_mode": True}
    
    # We force dry_run=True, resume_run=False so it creates a NEW run
    res = DgiiCertService.process_step2_generate(1, profile, parsed_data, ["4"], True, 999, False, True)
    
    xml_path = '/Users/esmerlinpaniagua/Develop/e-Factura/e-FacturaWeb/uploads/certificacion/test_company/step2/run999/xml/E320000000011_manual_signed.xml'
    if os.path.exists(xml_path):
        with open(xml_path, 'r') as f:
            content = f.read()
            print("ROOT:", content[:50])
            print("COMPRADOR:", "<Comprador" in content)
    else:
        print("XML not found:", xml_path)
