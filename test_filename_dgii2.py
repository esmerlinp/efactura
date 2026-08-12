from app import create_app
from app.services.db_service import DbService
from app.services.dgii_direct import DgiiDirectService
import time

app = create_app()
with app.app_context():
    def test_filename(filename, encf="E310000000004"):
        company = DbService.get_company("eG1D24i5oYvT6i9M4BIf")
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

    print("Testing standard RNC (9 digits): 133753652")
    test_filename("133753652E310000000004.xml", "E310000000004")
    
    print("\nTesting Certificate RNC (11 digits): 22900013305")
    test_filename("22900013305E310000000004.xml", "E310000000004")
    
    print("\nTesting ONLY eNCF (17 chars)")
    test_filename("E310000000004.xml", "E310000000004")

