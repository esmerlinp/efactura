from datetime import date

import pytest

from app.models.recurring_contract import ContractTermsVersion, RecurringContract, RecurringContractLine, RecurringContractStatus
from app.services.recurring_contract_admin_service import RecurringContractAdminService


class Repo:
    def __init__(self):
        self.saved = []

    def create(self, contract):
        self.saved.append(contract)
        return contract

    def update(self, contract):
        self.saved.append(contract)
        return contract


def make():
    line = RecurringContractLine(name="Servicio", unit_price=100)
    value = RecurringContract(owner_uid="owner", company_id="company", client_id="client", start_date=date(2026, 1, 1), billing_anchor_date=date(2026, 1, 1), billing_day=1, status="active", auto_renew=True, ecf_type="E31", lines=(line,))
    return value.add_terms_version(ContractTermsVersion(version=1, effective_from=date(2026, 1, 1), ecf_type="E31", lines=(line,)))


def test_update_terms_closes_previous_version_without_mutating_original():
    repo = Repo()
    original = make()
    updated = RecurringContractAdminService(repo).update_terms(original, effective_from=date(2026, 7, 1), ecf_type="E31", currency="DOP", payment_type="Credito", payment_method="transferencia", credit_days=30, billing_mode=original.billing_mode, lines=original.lines)
    assert len(original.terms_versions) == 1
    assert original.terms_versions[0].effective_to is None
    assert updated.terms_versions[0].effective_to == date(2026, 7, 1)
    assert len(updated.terms_versions) == 2


def test_fiscal_review_requires_valid_elegible_type():
    repo = Repo()
    pending = make().model_copy(update={"needs_fiscal_review": True, "ecf_type": None})
    with pytest.raises(ValueError):
        RecurringContractAdminService(repo).resolve_fiscal_review(pending, ecf_type="E43")
    resolved = RecurringContractAdminService(repo).resolve_fiscal_review(pending, ecf_type="E31")
    assert not resolved.needs_fiscal_review
    assert resolved.ecf_type == "E31"


def test_suspend_reactivate_and_cancel_follow_domain_transitions():
    repo = Repo()
    service = RecurringContractAdminService(repo)
    suspended = service.transition(make(), RecurringContractStatus.SUSPENDED)
    active = service.transition(suspended, RecurringContractStatus.ACTIVE)
    requested = service.request_cancellation(active, "Cliente solicita cancelación")
    assert requested.status == RecurringContractStatus.ACTIVE
    assert requested.model_dump().get("cancellation_requested") is True


def test_renewal_requires_auto_renew_and_extends_end_date():
    repo = Repo()
    contract = make().model_copy(update={"end_date": date(2026, 12, 31)})
    renewed = RecurringContractAdminService(repo).renew(contract, new_end_date=date(2027, 12, 31))
    assert renewed.end_date == date(2027, 12, 31)


def test_fiscal_review_resolution_fills_versions_without_fiscal_type():
    from app.services.recurring_contract_billing_service import RecurringContractBillingService

    repo = Repo()
    line = RecurringContractLine(name="Servicio", unit_price=100)
    pending = RecurringContract(
        owner_uid="owner", company_id="company", client_id="client",
        start_date=date(2026, 1, 1), billing_anchor_date=date(2026, 1, 1),
        billing_day=1, status="active", ecf_type=None, lines=(line,),
    ).add_terms_version(
        ContractTermsVersion(version=1, effective_from=date(2026, 1, 1), ecf_type=None, lines=(line,))
    ).model_copy(update={"needs_fiscal_review": True})

    resolved = RecurringContractAdminService(repo).resolve_fiscal_review(pending, ecf_type="E31")

    assert resolved.ecf_type == "E31"
    assert resolved.terms_versions[0].ecf_type == "E31"
    prepared = RecurringContractBillingService.prepare_invoice(
        resolved, occurrence_date=date(2026, 1, 1)
    )
    assert prepared.snapshot.ecf_type == "E31"
