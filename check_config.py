import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate('../firebase-adminsdk.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

docs = db.collection_group("config").get()
for doc in docs:
    if doc.id == "user_profile":
        data = doc.to_dict()
        print(f"Path: {doc.reference.path}, Name: {data.get('name')}, profileImageUrl: '{data.get('profileImageUrl')}'")
