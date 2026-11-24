"""Migrate historical bank movements into the unified ledger."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.services import db_service
from app.services.db_service import DatabaseService
from app.services.bank_ledger_rebuild_service import BankLedgerRebuildService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company")
    parser.add_argument("--account")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    app = create_app()
    rows = []
    with app.app_context():
        companies = list(db_service.db_firestore.collection("companies").stream())
        for company_doc in companies:
            if args.company and company_doc.id != args.company:
                continue
            company = company_doc.to_dict() or {}
            owner = company.get("owner_uid", "")
            for collection in ("sandbox_bank_accounts", "bank_accounts"):
                sandbox = collection.startswith("sandbox_")
                if args.production != (not sandbox):
                    continue
                for account_doc in db_service.db_firestore.collection("companies").document(company_doc.id).collection(collection).stream():
                    if args.account and account_doc.id != args.account:
                        continue
                    account = account_doc.to_dict() or {}
                    movements = BankLedgerRebuildService.build_candidates(DatabaseService, owner, company_doc.id, account_doc.id, sandbox=sandbox)
                    migration = BankLedgerRebuildService.persist_candidates(DatabaseService, owner, company_doc.id, movements, sandbox=sandbox, apply=args.apply)
                    rows.append({"company": company.get("company_name") or company.get("name"), "company_id": company_doc.id, "environment": "sandbox" if sandbox else "production", "account": account.get("name"), "account_id": account_doc.id, "candidates": len(movements), "migration": migration})
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
