from app import create_app
from app.services.db_service import DatabaseService
from app.services.dgii_direct import DgiiDirectService
import time

app = create_app()
with app.app_context():
    def test_filename(filename, encf="E310000000004"):
        company = DatabaseService.get_company("eG1D24i5oYvT6i9M4BIf")
        if not company:
            # Let's get the FIRST company in sandbox_companies that has dgiiProfile
            from firebase_admin import firestore
            db = firestore.client()
            docs = db.collection('sandbox_companies').where("companyRNC", "==", "133753652").limit(1).stream()
            for d in docs:
                company = d.to_dict()
                break
        
        company_profile = company.get("dgiiProfile", {})
        token = DgiiDirectService.get_dgii_token(company_profile, sandbox=True)
        
        xml_data = b"<ECF></ECF>" 
        with open(f"evidencia_fase2/xml/{encf}_signed.xml", "rb") as f:
            xml_data = f.read()

        endpoints = DgiiDirectService._resolve_endpoints(sandbox=True)
        recepcion_url = endpoints["recepcion"]
        cert_path = DgiiDirectService._prepare_tls_cert(company_profile)
        
        print(f"\n--- Testing filename: {filename} ---")
        response = DgiiDirectService._multipart_post(recepcion_url, xml_data, token=token, filename=filename, cert_path=cert_path)
        
        DgiiDirectService._cleanup_tls_cert(cert_path)
        
        data = DgiiDirectService._safe_json(response)
        text = response.text
        track_id = DgiiDirectService._extract_track_id(data, text)
        print(f"Track ID: {track_id}, status: {response.status_code}")
        
        if track_id:
            print("Waiting 5s for async processing...")
            time.sleep(5)
            poll_res = DgiiDirectService.check_status(company_profile, track_id, sandbox=True)
            print(f"Poll result: {poll_res.get('dgiiStatus')} | mensajes: {poll_res.get('mensajes')}")
        else:
            print(f"No track id. Error: {text}")

    test_filename("133753652E310000000004.xml", "E310000000004")
    test_filename("22900013305E310000000004.xml", "E310000000004")
    test_filename("E310000000004.xml", "E310000000004")
