"""Dry-run historical bank ledger reconstruction. Never writes Firestore."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.db_service import DatabaseService
from app.services.bank_ledger_rebuild_service import BankLedgerRebuildService
from app import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    sandbox = not args.production
    app = create_app()
    with app.app_context():
        account = DatabaseService.get_bank_account(args.owner, args.account, sandbox=sandbox, company_id=args.company)
        if not account:
            raise SystemExit("Cuenta no encontrada")
        movements = BankLedgerRebuildService.build_candidates(DatabaseService, args.owner, args.company, args.account, sandbox=sandbox)
        print(json.dumps(BankLedgerRebuildService.summarize(account, movements), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
