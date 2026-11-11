from datetime import date

import pytest

from app.models.recurring_contract import ContractTermsVersion, RecurringContract, RecurringContractLine
from app.services.recurring_contract_service import RecurringContractFeatureFlags, RecurringContractService


class Occurrences:
    def __init__(self):
        self.items = {}

    def create_idempotent(self, **kwargs):
        from app.models.recurring_contract_occurrence import RecurringContractBillingOccurrence
        key = kwargs["contract_id"] + kwargs["billing_period_key"]
        if key not in self.items:
            self.items[key] = RecurringContractBillingOccurrence(
                id=key, owner_uid=kwargs["owner_uid"], company_id=kwargs["company_id"],
                contract_id=kwargs["contract_id"], billing_period_key=kwargs["billing_period_key"],
                period_start=kwargs["period_start"], period_end=kwargs["period_end"],
                occurrence_date=kwargs["occurrence_date"],
            )
        return self.items[key]

    def prepare_once(self, *, occurrence, contract, sandbox):
        from app.services.recurring_contract_billing_service import RecurringContractBillingService
        prepared = RecurringContractBillingService.prepare_invoice(
            contract, occurrence_date=date.fromisoformat(occurrence.occurrence_date)
        )
        if occurrence.invoice_id:
            prepared.invoice.id = occurrence.invoice_id
        updated = occurrence.model_copy(update={"invoice_id": prepared.invoice.id, "status": "prepared"})
        self.items[updated.id] = updated
        return updated, prepared


class Outbox:
    def __init__(self):
        self.commands = {}

    def create_idempotent(self, **kwargs):
        from app.models.recurring_contract_outbox import RecurringContractEmissionOutboxCommand
        key = kwargs["occurrence_id"]
        if key not in self.commands:
            self.commands[key] = RecurringContractEmissionOutboxCommand(
                command_id=key, owner_uid=kwargs["owner_uid"], company_id=kwargs["company_id"],
                contract_id=kwargs["contract_id"], occurrence_id=key, attempt_id=kwargs["attempt_id"],
            )
        return self.commands[key]


def contract():
    value = RecurringContract(
        owner_uid="owner", company_id="company", client_id="client",
        start_date=date(2026, 1, 1), billing_anchor_date=date(2026, 1, 1), billing_day=1,
        status="active", ecf_type="E31",
        lines=(RecurringContractLine(name="Service", unit_price=100),),
    )
    return value.add_terms_version(ContractTermsVersion(
        version=1, effective_from=date(2026, 1, 1), ecf_type="E31", lines=value.lines,
    ))


class InvoiceStore:
    def __init__(self):
        self.saved = {}

    def __call__(self, *, owner_uid, invoice_id, invoice_dict, sandbox=True, company_id=None):
        self.saved[invoice_id] = dict(invoice_dict)
        return invoice_dict


class InvoiceLoader:
    def __init__(self, store):
        self.store = store

    def __call__(self, *, owner_uid, invoice_id, sandbox=True, company_id=None):
        return self.store.saved.get(invoice_id)


def service(enabled, store=None, loader=None):
    return RecurringContractService(
        occurrence_service=Occurrences(), outbox_service=Outbox(),
        flags=RecurringContractFeatureFlags(lambda *_: enabled),
        invoice_store=store or InvoiceStore(),
        invoice_loader=loader,
    )


def test_disabled_company_keeps_legacy_path():
    result = service(False).prepare_and_enqueue(
        contract=contract(), owner_uid="owner", company_id="company", sandbox=True, trigger="manual"
    )
    assert result["status"] == "legacy_required"


def test_enabled_manual_and_scheduler_share_same_occurrence():
    value = contract()
    coordinator = service(True)
    first = coordinator.prepare_and_enqueue(
        contract=value, owner_uid="owner", company_id="company", sandbox=True, trigger="manual"
    )
    second = coordinator.prepare_and_enqueue(
        contract=value, owner_uid="owner", company_id="company", sandbox=True, trigger="scheduler"
    )
    assert first["occurrence"].id == second["occurrence"].id
    assert first["command"].command_id == second["command"].command_id


def test_enabled_contract_persists_linked_draft_invoice():
    store = InvoiceStore()
    result = service(True, store).prepare_and_enqueue(
        contract=contract(), owner_uid="owner", company_id="company", sandbox=True, trigger="manual"
    )
    saved = store.saved[result["invoice_id"]]
    assert saved["contractId"] == result["prepared"].invoice.contractId
    assert saved["contractNumber"] == result["prepared"].invoice.contractNumber
    assert saved["occurrenceId"] == result["occurrence"].id
    assert saved["status"] == "Borrador"
    assert saved["encf"] == ""


def test_scope_is_validated_before_enqueue():
    with pytest.raises(PermissionError):
        service(True).prepare_and_enqueue(
            contract=contract(), owner_uid="other", company_id="company", sandbox=True, trigger="manual"
        )


def test_prepared_draft_gets_provisional_fac_number():
    store = InvoiceStore()
    result = service(True, store).prepare_and_enqueue(
        contract=contract(), owner_uid="owner", company_id="company", sandbox=True, trigger="manual"
    )
    saved = store.saved[result["invoice_id"]]
    assert saved["invoiceNumber"].startswith("FAC-")
    assert len(saved["invoiceNumber"]) == 10
    assert saved["invoiceNumber"] == result["prepared"].invoice.invoiceNumber


def test_reprepare_preserves_existing_invoice_number():
    store = InvoiceStore()
    coordinator = service(True, store, loader=InvoiceLoader(store))
    value = contract()

    first = coordinator.prepare_and_enqueue(
        contract=value, owner_uid="owner", company_id="company", sandbox=True, trigger="manual"
    )
    first_number = store.saved[first["invoice_id"]]["invoiceNumber"]

    second = coordinator.prepare_and_enqueue(
        contract=value, owner_uid="owner", company_id="company", sandbox=True, trigger="manual"
    )

    assert second["invoice_id"] == first["invoice_id"]
    assert store.saved[second["invoice_id"]]["invoiceNumber"] == first_number
