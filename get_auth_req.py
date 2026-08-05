import sys
sys.path.append('.')
from app.services.db_service import db_firestore
req_id = '61921586-a43e-4ac6-b4fd-98ed76aac602'
docs = db_firestore.collection_group('sandbox_hr_authorization_requests').where('id', '==', req_id).get()
for d in docs:
    print('FOUND:', d.reference.path)
    print(d.to_dict().get("approvalSteps"))
