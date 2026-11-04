import pytest

from app.services.aggregation_service import AggregationService
from app.services.budget_service import BudgetService
from app.services.company_authorization import CompanyAuthorizationError
from app.services.webhook_service import WebhookService


@pytest.mark.parametrize("call", [
    lambda: AggregationService._summary_path("owner-a", 2026, 1),
    lambda: BudgetService._path("owner-a", 2026),
    lambda: WebhookService._path("owner-a"),
    lambda: WebhookService._dlq_path("owner-a"),
])
def test_remaining_storage_paths_require_company_scope(call):
    with pytest.raises(CompanyAuthorizationError):
        call()
