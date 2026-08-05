import firebase_admin
from firebase_admin import credentials, auth
cred = credentials.Certificate("/Users/esmerlinpaniagua/Develop/e-Factura/firebase-adminsdk.json")
firebase_admin.initialize_app(cred)
page = auth.list_users()
print("Total users in Auth:", len(page.users))
for u in page.users:
    print(u.uid, u.email)
