import sys
import json
import logging
sys.path.append('.')

from flask import Flask
app = Flask(__name__)

with app.app_context():
    import firebase_admin
    from firebase_admin import credentials, firestore
    
    # ensure initialized
    try:
        from app.services.db_service import db_firestore
    except:
        pass
    
    from app.services.hr_authorization_service import get_authorization_request
    
    # We need company_id. Let's find the request by querying all company_ids?
    # Or just query all authorization_requests in the entire DB where id == ...
    docs = db_firestore.collection_group('sandbox_hr_authorization_requests').where('id', '==', '61921586-a43e-4ac6-b4fd-98ed76aac602').get()
    # Ah wait, collection_group failed!
