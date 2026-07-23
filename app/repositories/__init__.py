"""
Repositories — capa de acceso a datos tipada por bounded context.

Uso:
    from app.repositories import get_repos

    repos = get_repos(company_id)
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
    """Contenedor de repositorios para un company_id específico."""

    def __init__(self, company_id: str):
        self.company_id = company_id
        self._accounting: AccountingRepository | None = None
        self._contacts: ContactRepository | None = None
        self._invoices: InvoiceRepository | None = None
        self._banks: BankRepository | None = None

    @property
    def accounting(self) -> AccountingRepository:
        if self._accounting is None:
            self._accounting = AccountingRepository(self.company_id)
        return self._accounting

    @property
    def contacts(self) -> ContactRepository:
        if self._contacts is None:
            self._contacts = ContactRepository(self.company_id)
        return self._contacts

    @property
    def invoices(self) -> InvoiceRepository:
        if self._invoices is None:
            self._invoices = InvoiceRepository(self.company_id)
        return self._invoices

    @property
    def banks(self) -> BankRepository:
        if self._banks is None:
            self._banks = BankRepository(self.company_id)
        return self._banks


def get_repos(company_id: str) -> RepositoryContainer:
    """Factory function para obtener todos los repositorios de una compañía."""
    return RepositoryContainer(company_id)
