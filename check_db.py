from app import create_app
from app.services.db_service import db_firestore

app = create_app()
with app.app_context():
    docs = db_firestore.collection("users").limit(10).get()
    for doc in docs:
        uid = doc.id
        config_doc = db_firestore.collection("users").document(uid).collection("config").document("user_profile").get()
        if config_doc.exists:
            data = config_doc.to_dict()
            print(f"UID: {uid}, Email: {data.get('email')}, Name: {data.get('name')}, profileImageUrl: {data.get('profileImageUrl')}")
