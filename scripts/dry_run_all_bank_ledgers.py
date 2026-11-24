"""Dry-run all company bank ledger reconciliations; never writes Firestore."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.services.db_service import DatabaseService
from app.services import db_service
from app.services.bank_ledger_rebuild_service import BankLedgerRebuildService


def main():
    app = create_app()
    with app.app_context():
        rows = []
        for company_doc in db_service.db_firestore.collection("companies").stream():
            company = company_doc.to_dict() or {}
            owner = company.get("owner_uid", "")
            for coll in ("sandbox_bank_accounts", "bank_accounts"):
                sandbox = coll.startswith("sandbox_")
                for account_doc in db_service.db_firestore.collection("companies").document(company_doc.id).collection(coll).stream():
                    account = account_doc.to_dict() or {}
                    account["id"] = account_doc.id
                    movements = BankLedgerRebuildService.build_candidates(DatabaseService, owner, company_doc.id, account_doc.id, sandbox=sandbox)
                    result = BankLedgerRebuildService.summarize(account, movements)
                    migration = BankLedgerRebuildService.persist_candidates(DatabaseService, owner, company_doc.id, movements, sandbox=sandbox, apply=False)
                    rows.append({"company": company.get("company_name") or company.get("name"), "company_id": company_doc.id, "environment": "sandbox" if sandbox else "production", "account": account.get("name"), "account_id": account_doc.id, "difference": result["difference"], "movement_count": result["movement_count"], "stored_balance": result["stored_balance"], "reconstructed_balance": result["reconstructed_balance"], "candidate_movements": len(movements), "migration": migration})
        print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
