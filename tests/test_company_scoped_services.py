import pytest

from app.services.company_authorization import CompanyAuthorizationError
from app.services.purchase_order_service import PurchaseOrderService
from app.services.supplier_service import SupplierService


@pytest.mark.parametrize("method, kwargs", [
    (SupplierService.get_suppliers, {"owner_uid": "owner-a"}),
    (SupplierService.get_supplier, {"owner_uid": "owner-a", "supplier_id": "supplier-a"}),
    (PurchaseOrderService.get_purchase_orders, {"owner_uid": "owner-a"}),
    (PurchaseOrderService.get_purchase_order, {"owner_uid": "owner-a", "po_id": "po-a"}),
])
def test_business_services_reject_missing_company_scope(method, kwargs):
    with pytest.raises(CompanyAuthorizationError):
        method(**kwargs)
