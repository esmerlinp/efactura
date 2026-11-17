"""Create missing accounting entries for recorded proforma payments."""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import firebase_admin
from firebase_admin import credentials, firestore


def _initialize_firebase(path):
    if firebase_admin._apps:
        return
    bucket = os.getenv("FIREBASE_STORAGE_BUCKET", "e-factura-c2b78.firebasestorage.app")
    firebase_admin.initialize_app(
        credentials.Certificate(path),
        {"projectId": os.getenv("FIREBASE_PROJECT_ID", "e-factura-c2b78"), "storageBucket": bucket},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--sandbox", action="store_true")
    args = parser.parse_args()
    path = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "../firebase-adminsdk.json")
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    _initialize_firebase(path)
    db = firestore.client()
    coll = "sandbox_invoices" if args.sandbox else "invoices"
    root = db.collection("companies").document(args.company).collection(coll)
    from app.services.db_service import firebase_initialized
    if not firebase_initialized:
        raise SystemExit("Firebase no está disponible; se aborta para evitar escribir en SQLite/local.")
    from app.services.accounting_service import AccountingService
    found = applied = 0
    for doc in root.stream():
        invoice = doc.to_dict()
        if invoice.get("documentType") != "proforma" and not (invoice.get("isQuotation") and str(invoice.get("invoiceNumber", "")).startswith("PRO-")):
            continue
        for payment_doc in doc.reference.collection("payments").stream():
            payment = payment_doc.to_dict()
            found += 1
            if not args.apply:
                print("DRY-RUN", invoice.get("invoiceNumber"), payment_doc.id, payment.get("amount"))
                continue
            entry = AccountingService.auto_generate_proforma_payment_entry(args.company, {**invoice, "id": doc.id}, payment, sandbox=args.sandbox)
            if entry:
                applied += 1
                print("APPLIED", invoice.get("invoiceNumber"), payment_doc.id)
    print(f"payments={found} entries_created={applied} mode={'apply' if args.apply else 'dry-run'}")


if __name__ == "__main__":
    main()
