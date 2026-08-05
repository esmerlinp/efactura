import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate("/Users/esmerlinpaniagua/Develop/e-Factura/firebase-adminsdk.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
companies = list(db.collection("companies").stream())
print("Total companies:", len(companies))
