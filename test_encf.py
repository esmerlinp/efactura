import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
import json

app = firebase_admin.initialize_app()
db = firestore.Client()
company_id = "fa3abfc7-5e4c-410b-bde5-b101e1a8ea10"
process = db.collection("companies").document(company_id).collection("certificacion_dgii").document("process").get().to_dict()
cases = process.get("steps", {}).get("2", {}).get("runs", [])
if cases:
    run = cases[-1]
    for c in run.get("cases", []):
        print(f"eNCF: '{c['encf']}' (length {len(c['encf'])})")
        break
