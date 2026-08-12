from app import create_app
from app.services.dgii_cert_service import DgiiCertService
from app.services.db_service import DbService
from app.services.company_service import CompanyService

app = create_app()
with app.app_context():
    company_id = "fa3abfc7-5e4c-410b-bde5-b101e1a8ea10"
    company = CompanyService.get_company(company_id)
    profile = company.get("dgii_profile", {})
    process = DgiiCertService.get_process(company_id)
    
    # We will simulate exactly what process_step2_generate does for the first case of Group 1
    steps = process.get("steps", {})
    step2 = steps.get("2", {})
    runs = step2.get("runs", [])
    if runs:
        last_run = runs[-1]
        
        for c in last_run.get("cases", []):
            if str(c.get("grupo")) == "1":
                print(f"Testing case: {c.get('encf')}")
                encf = c["encf"]
                
                # Fetch raw xml from the path in case to sign it
                import os
                raw_path = c.get("raw_xml_path")
                if not raw_path or not os.path.exists(raw_path):
                    print(f"Missing raw_path: {raw_path}")
                    break
                    
                with open(raw_path, "rb") as f:
                    raw_xml = f.read()
                    
                from app.services.dgii_signer import DgiiSigner
                signed_xml = DgiiSigner.sign_xml(raw_xml, profile)
                
                token, err = DgiiCertService._get_cert_token(profile)
                if err:
                    print(f"Token error: {err}")
                    break
                    
                res = DgiiCertService._send_ecf(profile, signed_xml, token, c)
                print(f"Result: {res}")
                break
