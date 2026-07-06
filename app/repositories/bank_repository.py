"""
BankRepository — cuentas bancarias, cajas, conciliaciones.
"""
from typing import Optional

from app.repositories.base import BaseRepository


class BankRepository(BaseRepository):
    """Repositorio para el bounded context de Tesorería y Bancos."""

    # ── Bank Accounts ───────────────────────────────────────────────────
    def get_bank_accounts(self, sandbox: bool = True) -> list:
        self.collection_prefix = "bank_accounts"
        return self._get_all(sandbox=sandbox)

    def get_bank_account(self, account_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "bank_accounts"
        return self._get_one(account_id, sandbox=sandbox)

    def save_bank_account(self, account_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "bank_accounts"
        return self._save(account_id, data, sandbox=sandbox)

    def delete_bank_account(self, account_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "bank_accounts"
        return self._delete(account_id, sandbox=sandbox)

    # ── Reconciliations ─────────────────────────────────────────────────
    def get_reconciliations(self, sandbox: bool = True) -> list:
        self.collection_prefix = "reconciliations"
        return self._get_all(sandbox=sandbox)

    def get_reconciliation(self, recon_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "reconciliations"
        return self._get_one(recon_id, sandbox=sandbox)

    def save_reconciliation(self, recon_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "reconciliations"
        return self._save(recon_id, data, sandbox=sandbox)
