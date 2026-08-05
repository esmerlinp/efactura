import sys
sys.path.append('.')
from app.services.db_service import db_firestore

req_id = '61921586-a43e-4ac6-b4fd-98ed76aac602'
found = False

users = db_firestore.collection('companies').stream()
for user_doc in users:
    owner_uid = user_doc.id
    companies = db_firestore.collection('companies').document(owner_uid).collection('company').stream()
    for comp_doc in companies:
        company_id = comp_doc.id
        # Check authorization requests
        req_ref = db_firestore.collection('companies').document(owner_uid).collection('company').document(company_id).collection('sandbox_hr_authorization_requests').document(req_id).get()
        if req_ref.exists:
            print("FOUND REQUEST:")
            req_data = req_ref.to_dict()
            print("STATUS:", req_data.get("status"))
            print("STEPS:")
            for s in req_data.get("approvalSteps", []):
                print(s)
            found = True
            break
    if found:
        break
