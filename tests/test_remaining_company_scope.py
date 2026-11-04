import pytest

from app.services.company_authorization import CompanyAuthorizationError
from app.services.fixed_asset_service import FixedAssetService
from app.services.herramientas_service import _coll_path
from app.services.ledger_audit_service import LedgerAuditService
from app.services.purchase_credit_note_service import PurchaseCreditNoteService


@pytest.mark.parametrize("call", [
    lambda: _coll_path("owner-a", "assets"),
    lambda: LedgerAuditService._audit_path("owner-a", "entry-a"),
    lambda: PurchaseCreditNoteService._coll_ref(owner_uid="owner-a"),
    lambda: PurchaseCreditNoteService._counter_ref(owner_uid="owner-a"),
    lambda: FixedAssetService.register_asset("owner-a", {"name": "Equipo"}),
])
def test_remaining_services_reject_missing_company_scope(call):
    with pytest.raises(CompanyAuthorizationError):
        call()
