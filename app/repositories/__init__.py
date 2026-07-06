"""
Repositories — capa de acceso a datos tipada por bounded context.

Uso:
    from app.repositories import get_repos

    repos = get_repos(owner_uid)
    accounts = repos.accounting.get_chart_of_accounts()
    clients = repos.contacts.get_clients()
    invoices = repos.invoices.get_invoices()
    banks = repos.banks.get_bank_accounts()
"""
from app.repositories.accounting_repository import AccountingRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.bank_repository import BankRepository


class RepositoryContainer:
    """Contenedor de repositorios para un owner_uid específico."""

    def __init__(self, owner_uid: str):
        self.owner_uid = owner_uid
        self._accounting: AccountingRepository | None = None
        self._contacts: ContactRepository | None = None
        self._invoices: InvoiceRepository | None = None
        self._banks: BankRepository | None = None

    @property
    def accounting(self) -> AccountingRepository:
        if self._accounting is None:
            self._accounting = AccountingRepository(self.owner_uid)
        return self._accounting

    @property
    def contacts(self) -> ContactRepository:
        if self._contacts is None:
            self._contacts = ContactRepository(self.owner_uid)
        return self._contacts

    @property
    def invoices(self) -> InvoiceRepository:
        if self._invoices is None:
            self._invoices = InvoiceRepository(self.owner_uid)
        return self._invoices

    @property
    def banks(self) -> BankRepository:
        if self._banks is None:
            self._banks = BankRepository(self.owner_uid)
        return self._banks


def get_repos(owner_uid: str) -> RepositoryContainer:
    """Factory function para obtener todos los repositorios de un owner."""
    return RepositoryContainer(owner_uid)
