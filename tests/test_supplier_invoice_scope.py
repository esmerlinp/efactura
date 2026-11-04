import pytest

from app.services.company_authorization import CompanyAuthorizationError
from app.services.supplier_invoice_service import SupplierInvoiceService


def test_supplier_invoice_collection_requires_company_id():
    with pytest.raises(CompanyAuthorizationError):
        SupplierInvoiceService._coll_ref(owner_uid="owner-a")


def test_supplier_invoice_counter_requires_company_id():
    with pytest.raises(CompanyAuthorizationError):
        SupplierInvoiceService._counter_ref(owner_uid="owner-a")
