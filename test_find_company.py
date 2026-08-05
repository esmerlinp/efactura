import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate("/Users/esmerlinpaniagua/Develop/e-Factura/firebase-adminsdk.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
docs = db.collection("companies").where(filter=firestore.FieldFilter("owner_uid", "==", "e0oQFofbZtbjdJW0nz1XkWRHQ6n1")).stream()
docs_list = list(docs)
print("Companies for e0oQFofbZtbjdJW0nz1XkWRHQ6n1:", len(docs_list))
