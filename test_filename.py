import sys
from app import create_app
from app.services.dgii_cert_service import DgiiCertService
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
from app.services.dgii_direct import DgiiDirectService
from app.services.dgii_signer import DgiiSigner

app = create_app()
with app.app_context():
    db = firestore.Client()
    company_id = "fa3abfc7-5e4c-410b-bde5-b101e1a8ea10"
    company = db.collection("companies").document(company_id).get().to_dict()
    profile = company.get("dgii_profile", {})
    process = DgiiCertService.get_process(company_id)
    
    last_run = process.get("steps", {}).get("2", {}).get("runs", [])[-1]
    case = next(c for c in last_run["cases"] if str(c.get("grupo")) == "1")
    encf = case["encf"].strip()
    
    with open(case["raw_xml_path"], "rb") as f:
        raw_xml = f.read()
    signed_xml = DgiiSigner.sign_xml(raw_xml, profile)
    
    token, _ = DgiiCertService._get_cert_token(profile)
    endpoints = DgiiCertService._cert_endpoints()
    url = endpoints.get("recepcion")
    cert_path = DgiiDirectService._prepare_tls_cert(profile)
    
    company_rnc = str(profile.get("companyRNC", "")).replace("-", "").strip()
    
    print("\n--- TEST 1: filename = eNCF.xml ---")
    filename1 = f"{encf}.xml"
    print(f"Testing {filename1} (len: {len(filename1)})...")
    res1 = DgiiDirectService._multipart_post(url, signed_xml, token=token, filename=filename1, cert_path=cert_path)
    print("Res1 Code:", res1.status_code)
    print("Res1 Text:", res1.text)
    
    print("\n--- TEST 2: filename = RNC + eNCF.xml ---")
    filename2 = f"{company_rnc}{encf}.xml"
    print(f"Testing {filename2} (len: {len(filename2)})...")
    res2 = DgiiDirectService._multipart_post(url, signed_xml, token=token, filename=filename2, cert_path=cert_path)
    print("Res2 Code:", res2.status_code)
    print("Res2 Text:", res2.text)

