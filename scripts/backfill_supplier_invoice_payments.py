"""Backfill missing supplier-invoice payment details.

Dry-run is the default. Use --apply only after reviewing the report.
"""
import argparse
import os

import firebase_admin
from firebase_admin import credentials, firestore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--sandbox", action="store_true")
    args = parser.parse_args()

    cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "../firebase-adminsdk.json")
    if not os.path.isabs(cred_path):
        cred_path = os.path.abspath(cred_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
    db = firestore.client()
    coll = "sandbox_supplier_invoices" if args.sandbox else "supplier_invoices"
    root = db.collection("companies").document(args.company).collection(coll)

    found = applied = 0
    for doc in root.stream():
        data = doc.to_dict()
        if data.get("cxpStatus") != "Pagado" or list(doc.reference.collection("cxp_payments").limit(1).stream()):
            continue
        found += 1
        amount = float(data.get("netPayable", data.get("total", 0)) or 0)
        report = f"{doc.id} {data.get('invoiceNumber', '')} amount={amount:.2f} bank={data.get('bankAccountId', '')}"
        if not args.apply:
            print("DRY-RUN", report)
            continue
        payment_id = f"cash-{doc.id}"
        doc.reference.collection("cxp_payments").document(payment_id).set({
            "id": payment_id,
            "amount": round(amount, 2),
            "paymentDate": data.get("date", data.get("createdAt", "")),
            "registeredBy": data.get("createdBy", "Migración"),
            "createdAt": data.get("updatedAt", data.get("createdAt", "")),
            "method": data.get("paymentMethod", ""),
            "reference": data.get("paymentReference", ""),
            "bankAccountId": data.get("bankAccountId", ""),
            "source": "legacy_supplier_invoice_backfill",
        })
        applied += 1
        print("APPLIED", report)
    print(f"missing={found} applied={applied} mode={'apply' if args.apply else 'dry-run'}")


if __name__ == "__main__":
    main()
