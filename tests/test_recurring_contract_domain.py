from datetime import date

import pytest

from app.models.recurring_contract import (
    BillingFrequency,
    BillingMode,
    ContractTermsVersion,
    DueDatePolicy,
    PeriodEndPolicy,
    ProrationPolicy,
    RecurringContract,
    RecurringContractLine,
    RecurringContractStatus,
)
from app.services.recurring_contract_fiscal_service import RecurringContractFiscalService
from app.services.recurring_contract_schedule_service import RecurringContractScheduleService


def contract(**overrides):
    data = {
        "owner_uid": "owner-1",
        "company_id": "company-1",
        "client_id": "client-1",
        "start_date": date(2026, 1, 31),
        "billing_anchor_date": date(2026, 1, 31),
        "billing_day": 31,
        "frequency": BillingFrequency.MONTHLY,
    }
    data.update(overrides)
    return RecurringContract(**data)


def terms(**overrides):
    data = {
        "version": 1,
        "effective_from": date(2026, 1, 31),
        "ecf_type": "E31",
        "lines": (RecurringContractLine(name="Soporte", unit_price=1000),),
    }
    data.update(overrides)
    return ContractTermsVersion(**data)


def test_contract_is_separate_and_has_canonical_status():
    value = contract(status=RecurringContractStatus.ACTIVE)
    assert value.status == RecurringContractStatus.ACTIVE
    assert value.is_active
    assert value.company_id == "company-1"


@pytest.mark.parametrize(
    ("source", "target", "allowed"),
    [
        ("draft", "active", True),
        ("active", "suspended", True),
        ("suspended", "active", True),
        ("active", "cancelled", True),
        ("cancelled", "active", False),
        ("draft", "expired", False),
    ],
)
def test_status_transitions(source, target, allowed):
    value = contract(status=source)
    assert value.can_transition_to(target) is allowed
    if allowed:
        assert value.transition_to(target).status.value == target
    else:
        with pytest.raises(ValueError):
            value.transition_to(target)


def test_frequency_handles_short_months_deterministically():
    result = RecurringContractScheduleService.add_frequency(
        date(2026, 1, 31), BillingFrequency.MONTHLY
    )
    assert result == date(2026, 2, 28)
    assert RecurringContractScheduleService.add_frequency(
        result, BillingFrequency.MONTHLY
    ) == date(2026, 3, 28)


def test_last_day_policy_preserves_month_end_anchor():
    value = contract(period_end_policy=PeriodEndPolicy.LAST_DAY_OF_MONTH)
    assert RecurringContractScheduleService.next_billing_date(value, date(2026, 1, 31)) == date(2026, 2, 28)


def test_advance_period_is_inclusive():
    value = contract(billing_mode=BillingMode.ADVANCE)
    period = RecurringContractScheduleService.calculate_period(value, date(2026, 1, 31))
    assert period.period_start == date(2026, 1, 31)
    assert period.period_end == date(2026, 2, 27)
    assert period.key.startswith(f"{value.id}:2026-01-31:2026-02-27")


def test_arrears_period_is_inclusive():
    value = contract(billing_mode=BillingMode.ARREARS)
    period = RecurringContractScheduleService.calculate_period(value, date(2026, 2, 28))
    assert period.period_start == date(2026, 1, 29)
    assert period.period_end == date(2026, 2, 28)


def test_due_date_policies_are_independent_from_contract_end():
    value = contract(billing_mode=BillingMode.ADVANCE)
    period = RecurringContractScheduleService.calculate_period(value, date(2026, 1, 31))
    assert RecurringContractScheduleService.calculate_due_date(
        period, 30, DueDatePolicy.OCCURRENCE_PLUS_CREDIT_DAYS
    ) == date(2026, 3, 2)
    assert RecurringContractScheduleService.calculate_due_date(
        period, 30, DueDatePolicy.PERIOD_END_PLUS_CREDIT_DAYS
    ) == date(2026, 3, 29)
    assert RecurringContractScheduleService.calculate_due_date(
        period, 30, DueDatePolicy.SAME_DAY
    ) == date(2026, 1, 31)


def test_proration_includes_start_and_end_days():
    value = contract(
        start_date=date(2026, 1, 1),
        billing_anchor_date=date(2026, 1, 1),
        billing_day=1,
    )
    period = RecurringContractScheduleService.calculate_period(value, date(2026, 1, 1))
    assert RecurringContractScheduleService.prorated_amount(
        3100, period, date(2026, 1, 16), ProrationPolicy.DAILY
    ) == 1600


def test_schedule_is_deterministic_for_same_inputs():
    value = contract()
    first = RecurringContractScheduleService.calculate_period(value, date(2026, 1, 31))
    second = RecurringContractScheduleService.calculate_period(value, date(2026, 1, 31))
    assert first == second
    assert RecurringContractScheduleService.calculate_due_date(
        first, 30, DueDatePolicy.OCCURRENCE_PLUS_CREDIT_DAYS
    ) == date(2026, 3, 2)


def test_renewal_uses_explicit_renewal_period():
    value = contract(renewal_period=BillingFrequency.QUARTERLY)
    assert RecurringContractScheduleService.renewal_end_date(value, date(2026, 1, 31)) == date(2026, 4, 30)


def test_terms_versions_are_temporal_and_non_overlapping():
    value = contract().add_terms_version(terms())
    updated = value.add_terms_version(
        terms(version=2, effective_from=date(2026, 7, 1), credit_days=30)
    )
    assert updated.terms_for(date(2026, 6, 30)).version == 1
    assert updated.terms_for(date(2026, 7, 1)).version == 2
    assert updated.terms_versions[0].effective_to == date(2026, 7, 1)


def test_terms_version_requires_consecutive_version():
    with pytest.raises(ValueError):
        contract().add_terms_version(terms(version=2))


def test_snapshot_freezes_terms_for_period():
    value = contract().add_terms_version(terms())
    period = RecurringContractScheduleService.calculate_period(value, date(2026, 1, 31))
    snapshot = value.snapshot_for(period, RecurringContractScheduleService)
    assert snapshot.contract_version == 1
    assert snapshot.ecf_type == "E31"
    assert snapshot.lines[0].total == 1180
    with pytest.raises(Exception):
        snapshot.lines[0].unit_price = 2000


def test_contract_identity_keeps_company_isolation():
    first = contract(company_id="company-a")
    second = contract(company_id="company-b")
    assert first.company_id != second.company_id
    assert first.id != second.id


@pytest.mark.parametrize("code", ["E41", "E43", "E33", "E34", "E50"])
def test_non_sales_types_are_excluded(code):
    result = RecurringContractFiscalService.validate(code)
    assert not result.allowed
    assert result.requires_review


@pytest.mark.parametrize("code", ["E31", "E32"])
def test_general_sales_types_are_eligible(code):
    result = RecurringContractFiscalService.validate(code)
    assert result.allowed
    assert not result.requires_review


def test_conditional_type_requires_explicit_permission():
    assert not RecurringContractFiscalService.validate("E45").allowed
    assert RecurringContractFiscalService.validate("E45", allow_conditional=True).allowed


def test_missing_fiscal_type_requires_review():
    result = RecurringContractFiscalService.validate(None)
    assert result.requires_review
    with pytest.raises(ValueError):
        RecurringContractFiscalService.normalize_for_contract(None)


def test_contract_rejects_invalid_date_order():
    with pytest.raises(ValueError):
        contract(end_date=date(2026, 1, 30))
