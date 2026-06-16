import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate('firebase-adminsdk.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

docs = db.collection("users").get()
for doc in docs:
    uid = doc.id
    config_doc = db.collection("users").document(uid).collection("config").document("user_profile").get()
    if config_doc.exists:
        data = config_doc.to_dict()
        print(f"UID: {uid}, Name: {data.get('name')}, profileImageUrl: '{data.get('profileImageUrl')}'")
