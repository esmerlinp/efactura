import os
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import time

cred = credentials.Certificate('firebase-adminsdk.json')
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

docs = db.collection('companies').where("companyRNC", "==", "133753652").limit(1).stream()
company = None
for d in docs:
    company = d.to_dict()
    break

if not company or 'dgiiProfile' not in company:
    print("Could not find company 133753652 with dgiiProfile!")
    exit(1)

profile = company['dgiiProfile']

from app.services.dgii_direct import DgiiDirectService
token = DgiiDirectService.get_dgii_token(profile, sandbox=True)

with open('evidencia_fase2/xml/E310000000004_signed.xml', 'rb') as f:
    xml_bytes = f.read()

recepcion_url = "https://ecf.dgii.gov.do/testecf/api/eCF/v1.0/recepcion"
cert_path = DgiiDirectService._prepare_tls_cert(profile)

def test_file(filename):
    print(f"\n--- Testing {filename} ({len(filename)} chars) ---")
    headers = {"Authorization": f"Bearer {token}"}
    files = {"xml": (filename, xml_bytes, "text/xml")}
    res = requests.post(recepcion_url, headers=headers, files=files, cert=cert_path)
    print(f"POST status: {res.status_code}")
    data = res.json() if res.text else {}
    track_id = data.get('trackId')
    
    if track_id:
        print(f"TrackId: {track_id}")
        time.sleep(5)
        status_url = f"https://ecf.dgii.gov.do/testecf/api/eCF/v1.0/estado?trackId={track_id}"
        poll_res = requests.get(status_url, headers=headers, cert=cert_path)
        print(f"Poll status: {poll_res.status_code}")
        print(f"Poll response: {poll_res.text}")
    else:
        print(f"No TrackId. Response: {res.text}")

test_file("E310000000004.xml")
test_file("133753652E310000000004.xml")
test_file("22900013305E310000000004.xml")

DgiiDirectService._cleanup_tls_cert(cert_path)
