from app import create_app
from app.services.db_service import DatabaseService
from app.services.dgii_xml_builder import DgiiXmlBuilder
from app.services.dgii_signer import DgiiSigner

app = create_app()
with app.app_context():
    owner_uid = 'ZofD4g0kX7T3oA0Gv9v84Oq0FkS2'  # We need the real ownerUID
    # Let's just find the first company profile
    docs = DatabaseService.db.collection('companies').limit(1).stream()
    company = None
    for d in docs:
        company = d.to_dict()
        owner_uid = d.id
        break
        
    if company:
        # Get first invoice
        inv_docs = DatabaseService.db.collection('users').document(owner_uid).collection('invoices_sandbox').limit(1).stream()
        invoice = None
        for d in inv_docs:
            invoice = d.to_dict()
            break
            
        if invoice:
            raw_xml = DgiiXmlBuilder.build_invoice_xml(company, invoice)
            signed_xml_bytes = DgiiSigner.sign_xml(raw_xml, company)
            print(signed_xml_bytes.decode('utf-8')[:200])
        else:
            print("No invoice found")
