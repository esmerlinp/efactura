"""Apply an explicit, idempotent bank-balance correction."""
import argparse
import os
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--amount", required=True, type=float)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "../firebase-adminsdk.json")
    if not os.path.isabs(cred_path):
        cred_path = os.path.abspath(cred_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
    db = firestore.client()
    company_ref = db.collection("companies").document(args.company)
    account_ref = company_ref.collection("bank_accounts").document(args.account)
    account = account_ref.get()
    if not account.exists:
        raise SystemExit("Cuenta bancaria no encontrada")
    data = account.to_dict()
    before = float(data.get("currentBalance", 0.0))
    after = round(before + args.amount, 2)
    marker = f"bank-balance-adjustment-{args.account}-{args.amount:.2f}-{args.reason}"
    marker_ref = company_ref.collection("bank_balance_adjustments").document(marker)
    print(f"Cuenta: {data.get('name', args.account)}")
    print(f"Saldo actual: {before:.2f}")
    print(f"Ajuste: {args.amount:.2f}")
    print(f"Saldo resultante: {after:.2f}")
    print(f"Motivo: {args.reason}")
    if marker_ref.get().exists:
        print("Ajuste ya aplicado; no se modifica nada.")
        return
    if not args.apply:
        print("DRY-RUN: no se modificó Firestore.")
        return
    now = datetime.now(timezone.utc).isoformat()
    account_ref.update({"currentBalance": after, "updatedAt": now})
    marker_ref.set({
        "id": marker,
        "accountId": args.account,
        "amount": args.amount,
        "beforeBalance": before,
        "afterBalance": after,
        "reason": args.reason,
        "createdAt": now,
        "source": "manual_bank_balance_adjustment",
    })
    print("APPLIED")


if __name__ == "__main__":
    main()
