"""
AccountingRepository — acceso a datos contables: catálogo de cuentas, asientos, activos fijos, períodos fiscales.
Opera sobre companies/{company_id}/...
"""
from typing import Optional

from app.repositories.base import BaseRepository


class AccountingRepository(BaseRepository):
    """Repositorio para el bounded context de Contabilidad."""

    # ── Chart of Accounts ──────────────────────────────────────────────
    def get_chart_of_accounts(self) -> list:
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return []
        docs = db_firestore.collection("companies").document(self.company_id).collection("chart_of_accounts").get()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

    def save_account(self, account_id: str, data: dict) -> str:
        from app.services.db_service import db_firestore, firebase_initialized
        data["id"] = account_id
        if firebase_initialized:
            db_firestore.collection("companies").document(self.company_id).collection("chart_of_accounts").document(account_id).set(data)
        return account_id

    # ── Journal Entries ────────────────────────────────────────────────
    def get_accounting_entries(self, sandbox: bool = True) -> list:
        self.collection_prefix = "accounting_entries"
        return self._get_all(sandbox=sandbox)

    def get_accounting_entry(self, entry_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "accounting_entries"
        return self._get_one(entry_id, sandbox=sandbox)

    def save_accounting_entry(self, entry_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "accounting_entries"
        return self._save(entry_id, data, sandbox=sandbox)

    def delete_accounting_entry(self, entry_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "accounting_entries"
        return self._delete(entry_id, sandbox=sandbox)

    def get_next_entry_number(self, prefix: str = "A", sandbox: bool = True) -> str:
        """Obtiene el siguiente número de asiento contable usando una transacción atómica."""
        from app.services.db_service import db_firestore, firebase_initialized, firestore
        from datetime import datetime
        if firebase_initialized:
            transaction = db_firestore.transaction()

            @firestore.transactional
            def run_in_transaction(transaction):
                counter_ref = db_firestore.collection("companies").document(self.company_id).collection("config").document("entry_counter")
                counter = counter_ref.get(transaction=transaction)
                if counter.exists:
                    data = counter.to_dict()
                    next_num = data.get("nextNumber", 1)
                else:
                    next_num = 1
                transaction.set(counter_ref, {"nextNumber": next_num + 1})
                return next_num

            next_num = run_in_transaction(transaction)
            return f"{prefix}-{next_num:05d}"
        return f"{prefix}-{int(datetime.now().timestamp())}"

    # ── Fixed Assets ───────────────────────────────────────────────────
    def get_fixed_assets(self, sandbox: bool = True) -> list:
        self.collection_prefix = "fixed_assets"
        return self._get_all(sandbox=sandbox)

    def get_fixed_asset(self, asset_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "fixed_assets"
        return self._get_one(asset_id, sandbox=sandbox)

    def save_fixed_asset(self, asset_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "fixed_assets"
        return self._save(asset_id, data, sandbox=sandbox)

    def delete_fixed_asset(self, asset_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "fixed_assets"
        return self._delete(asset_id, sandbox=sandbox)

    # ── Fiscal Periods ─────────────────────────────────────────────────
    def get_fiscal_periods(self) -> list:
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return []
        docs = db_firestore.collection("companies").document(self.company_id).collection("fiscal_periods").get()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

    def save_fiscal_period(self, period_id: str, data: dict) -> str:
        from app.services.db_service import db_firestore, firebase_initialized
        data["id"] = period_id
        if firebase_initialized:
            db_firestore.collection("companies").document(self.company_id).collection("fiscal_periods").document(period_id).set(data)
        return period_id

    # ── Entry Types ────────────────────────────────────────────────────
    def get_entry_types(self) -> list:
        from app.services.db_service import db_firestore, firebase_initialized
        types = []
        if firebase_initialized:
            docs = db_firestore.collection("companies").document(self.company_id).collection("config").document("entry_types").collection("types").get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                types.append(data)
        return types

    def save_entry_type(self, type_id: str, data: dict) -> str:
        from app.services.db_service import db_firestore, firebase_initialized
        if firebase_initialized:
            db_firestore.collection("companies").document(self.company_id).collection("config").document("entry_types").collection("types").document(type_id).set(data)
        return type_id

    # ── Cost Centers ───────────────────────────────────────────────────
    def get_cost_centers(self, sandbox: bool = True) -> list:
        self.collection_prefix = "cost_centers"
        return self._get_all(sandbox=sandbox)

    def get_cost_center(self, center_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "cost_centers"
        return self._get_one(center_id, sandbox=sandbox)

    def save_cost_center(self, center_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "cost_centers"
        return self._save(center_id, data, sandbox=sandbox)

    def delete_cost_center(self, center_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "cost_centers"
        return self._delete(center_id, sandbox=sandbox)
