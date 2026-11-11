from datetime import date, datetime, timezone

import pytest

from app.models.recurring_contract import (
    BillingFrequency,
    ContractTermsVersion,
    RecurringContract,
    RecurringContractLine,
    RecurringContractStatus,
)
from app.services.recurring_contract_billing_service import (
    RecurringContractBillingError,
    RecurringContractBillingService,
)


def make_contract(**overrides):
    data = {
        "owner_uid": "owner-1",
        "company_id": "company-1",
        "contract_number": "CONT-001",
        "client_id": "client-1",
        "client_name_snapshot": "Cliente Uno",
        "client_rnc_snapshot": "101010101",
        "status": RecurringContractStatus.ACTIVE,
        "start_date": date(2026, 1, 1),
        "billing_anchor_date": date(2026, 1, 1),
        "billing_day": 1,
        "frequency": BillingFrequency.MONTHLY,
        "ecf_type": "E31",
        "lines": (RecurringContractLine(name="Soporte", code="SUP", unit_price=1000),),
    }
    data.update(overrides)
    return RecurringContract(**data)


def add_terms(contract, **overrides):
    data = {
        "version": 1,
        "effective_from": contract.start_date,
        "ecf_type": contract.ecf_type,
        "currency": contract.currency,
        "payment_type": contract.payment_type,
        "payment_method": contract.payment_method,
        "credit_days": contract.credit_days,
        "lines": contract.lines,
    }
    data.update(overrides)
    return contract.add_terms_version(ContractTermsVersion(**data))


def ready_contract(**overrides):
    value = make_contract(**overrides)
    return add_terms(value)


def test_prepare_invoice_returns_snapshot_and_consistent_totals():
    result = RecurringContractBillingService.prepare_invoice(
        ready_contract(),
        occurrence_date=date(2026, 1, 1),
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result.snapshot.billing_period_key.startswith(f"{result.invoice.id}") is False
    assert result.invoice.date == "2026-01-01"
    assert result.invoice.dueDate == "2026-01-01"
    assert result.invoice.ecfType.endswith("(E31)")
    assert result.invoice.subtotal == 1000
    assert result.invoice.totalITBIS == 180
    assert result.invoice.total == 1180
    assert result.invoice.items[0].total == 1180


def test_prepare_invoice_uses_terms_version_for_future_period():
    value = ready_contract()
    value = value.add_terms_version(
        ContractTermsVersion(
            version=2,
            effective_from=date(2026, 2, 1),
            ecf_type="E32",
            currency="USD",
            credit_days=30,
            lines=(RecurringContractLine(name="Soporte USD", unit_price=50, itbis_rate=0),),
        )
    )
    result = RecurringContractBillingService.prepare_invoice(value, occurrence_date=date(2026, 2, 1))
    assert result.snapshot.contract_version == 2
    assert result.invoice.ecfType.endswith("(E32)")
    assert result.invoice.currency == "USD"
    assert result.invoice.dueDate == "2026-03-03"
    assert result.invoice.total == 50


@pytest.mark.parametrize("status", ["draft", "pending_approval", "suspended", "cancelled", "expired"])
def test_non_active_contract_is_rejected(status):
    with pytest.raises(RecurringContractBillingError, match="no está activo"):
        RecurringContractBillingService.prepare_invoice(ready_contract(status=status))


def test_fiscal_review_is_rejected_without_emission():
    with pytest.raises(RecurringContractBillingError, match="revisión fiscal"):
        RecurringContractBillingService.prepare_invoice(ready_contract(needs_fiscal_review=True))


def test_resolved_fiscal_review_allows_preparation():
    value = ready_contract(needs_fiscal_review=True)
    resolved = value.model_copy(update={"needs_fiscal_review": False, "ecf_type": "E31"})
    result = RecurringContractBillingService.prepare_invoice(
        resolved, occurrence_date=date(2026, 1, 1)
    )
    assert result.invoice.total == 1180
    assert result.snapshot.ecf_type == "E31"


def test_missing_fiscal_type_is_rejected():
    value = make_contract(ecf_type=None)
    value = add_terms(value, ecf_type=None)
    with pytest.raises(RecurringContractBillingError, match="tipo de e-CF"):
        RecurringContractBillingService.prepare_invoice(value)


def test_missing_terms_for_period_is_rejected():
    value = ready_contract()
    value = value.model_copy(update={
        "terms_versions": (value.terms_versions[0].model_copy(update={"effective_to": date(2026, 12, 31)}),)
    })
    with pytest.raises(RecurringContractBillingError, match="No existe versión contractual"):
        RecurringContractBillingService.prepare_invoice(value, occurrence_date=date(2027, 1, 1))


def test_period_outside_non_renewing_contract_is_rejected():
    value = ready_contract(
        end_date=date(2026, 1, 15),
        billing_anchor_date=date(2026, 1, 1),
        billing_day=1,
    )
    with pytest.raises(RecurringContractBillingError, match="excede la vigencia"):
        RecurringContractBillingService.prepare_invoice(value, occurrence_date=date(2026, 1, 1))


def test_empty_lines_are_rejected():
    value = ready_contract(lines=())
    with pytest.raises(RecurringContractBillingError, match="no tiene líneas"):
        RecurringContractBillingService.prepare_invoice(value)


def test_conditional_fiscal_type_remains_pending():
    value = make_contract(ecf_type="E45")
    value = add_terms(value, ecf_type="E45")
    with pytest.raises(RecurringContractBillingError, match="validación de operación"):
        RecurringContractBillingService.prepare_invoice(value)


def test_preparation_has_no_fiscal_side_effect_fields():
    result = RecurringContractBillingService.prepare_invoice(ready_contract())
    assert result.invoice.encf == ""
    assert not result.invoice.isSyncedWithDGII
    assert result.invoice.xmlSignature == ""
