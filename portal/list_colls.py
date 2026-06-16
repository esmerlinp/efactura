import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate('firebase-adminsdk.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

print([col.id for col in db.collections()])
