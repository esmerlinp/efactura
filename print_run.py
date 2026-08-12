import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
import json

app = firebase_admin.initialize_app()
db = firestore.Client()
company_id = "fa3abfc7-5e4c-410b-bde5-b101e1a8ea10"
# Run 1 or whatever is latest? Let's get the latest run.
runs_ref = db.collection(f"companies/{company_id}/certificacion_dgii/process/runs")
runs = list(runs_ref.where("step", "==", 2).order_by("run_number", direction=firestore.Query.DESCENDING).limit(1).stream())
for run in runs:
    data = run.to_dict()
    for case in data.get("cases", []):
        if case.get("grupo") == 1:
            print(json.dumps({
                "encf": case.get("encf"),
                "success": case.get("success"),
                "dgii_status": case.get("dgii_status"),
                "error_message": case.get("error_message"),
                "response_data": case.get("response_data")
            }))
            break
