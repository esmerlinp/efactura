"""
InvoiceRepository — facturas, gastos, pagos, items del catálogo.
"""
from typing import Optional

from app.repositories.base import BaseRepository


class InvoiceRepository(BaseRepository):
    """Repositorio para el bounded context de Facturación y Ventas."""

    # ── Invoices ────────────────────────────────────────────────────────
    def get_invoices(self, sandbox: bool = True, quotations_only: bool = False) -> list:
        self.collection_prefix = "invoices"
        return self._get_all(sandbox=sandbox)

    def get_invoice(self, invoice_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "invoices"
        return self._get_one(invoice_id, sandbox=sandbox)

    def save_invoice(self, invoice_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "invoices"
        return self._save(invoice_id, data, sandbox=sandbox)

    def delete_invoice(self, invoice_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "invoices"
        return self._delete(invoice_id, sandbox=sandbox)

    # ── Quotations ──────────────────────────────────────────────────────
    def get_quotations(self, sandbox: bool = True) -> list:
        self.collection_prefix = "quotations"
        return self._get_all(sandbox=sandbox)

    def save_quotation(self, quotation_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "quotations"
        return self._save(quotation_id, data, sandbox=sandbox)

    # ── Expenses ────────────────────────────────────────────────────────
    def get_expenses(self, sandbox: bool = True) -> list:
        self.collection_prefix = "expenses"
        return self._get_all(sandbox=sandbox)

    def get_expense(self, expense_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "expenses"
        return self._get_one(expense_id, sandbox=sandbox)

    def save_expense(self, expense_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "expenses"
        return self._save(expense_id, data, sandbox=sandbox)

    def delete_expense(self, expense_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "expenses"
        return self._delete(expense_id, sandbox=sandbox)

    # ── Catalog Items ───────────────────────────────────────────────────
    def get_items(self, sandbox: bool = True) -> list:
        self.collection_prefix = "items"
        return self._get_all(sandbox=sandbox)

    def get_item(self, item_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "items"
        return self._get_one(item_id, sandbox=sandbox)

    def save_item(self, item_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "items"
        return self._save(item_id, data, sandbox=sandbox)

    def delete_item(self, item_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "items"
        return self._delete(item_id, sandbox=sandbox)

    # ── Invoice Comments ────────────────────────────────────────────────
    def get_invoice_comments(self, invoice_id: str, sandbox: bool = True) -> list:
        from app.services.db_service import db_firestore, firebase_initialized
        comments = []
        if not firebase_initialized:
            return comments
        coll_name = "sandbox_invoices" if sandbox else "invoices"
        docs = db_firestore.collection("users").document(self.owner_uid).collection(coll_name).document(invoice_id).collection("comments").get()
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            comments.append(data)
        return comments

    # ── Price Lists ─────────────────────────────────────────────────────
    def get_price_lists(self, sandbox: bool = True) -> list:
        self.collection_prefix = "price_lists"
        return self._get_all(sandbox=sandbox)

    def save_price_list(self, list_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "price_lists"
        return self._save(list_id, data, sandbox=sandbox)

    # ── Warehouses ──────────────────────────────────────────────────────
    def get_warehouses(self, sandbox: bool = True) -> list:
        self.collection_prefix = "warehouses"
        return self._get_all(sandbox=sandbox)

    def save_warehouse(self, warehouse_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "warehouses"
        return self._save(warehouse_id, data, sandbox=sandbox)

    # ── Branches ────────────────────────────────────────────────────────
    def get_branches(self, sandbox: bool = True) -> list:
        self.collection_prefix = "branches"
        return self._get_all(sandbox=sandbox)

    def save_branch(self, branch_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "branches"
        return self._save(branch_id, data, sandbox=sandbox)
