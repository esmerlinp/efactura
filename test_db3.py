import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate("/Users/esmerlinpaniagua/Develop/e-Factura/firebase-adminsdk.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection("users").document("Z3vdMmbE6GaLmn5sgeh50qvrxkF2").collection("config").document("user_profile").get()
print("Exists:", doc.exists)
if doc.exists:
    print(doc.to_dict().get("companyName"))
