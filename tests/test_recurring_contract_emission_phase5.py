from datetime import date, datetime, timezone

import pytest

from app.models.recurring_contract import ContractTermsVersion, RecurringContract, RecurringContractLine
from app.models.recurring_contract_emission import FiscalAttemptStatus, PostAcceptanceEffectType, RecurringContractEmissionAttempt
from app.models.recurring_contract_outbox import RecurringContractEmissionOutboxCommand
from app.services.recurring_contract_billing_service import RecurringContractBillingService
from app.services.recurring_contract_emission_worker import RecurringContractEmissionWorker
from app.services.recurring_contract_post_acceptance_service import RecurringContractPostAcceptanceService
from app.services.recurring_contract_reconciliation_service import RecurringContractReconciliationService


class Store:
    def __init__(self):
        self.attempts = {}
        self.effects = {}

    def save(self, attempt, sandbox=True):
        self.attempts[attempt.attempt_id] = attempt

    def claim_or_get(self, *, owner_uid, company_id, invoice_id, event_type, sandbox=True):
        key = f"{invoice_id}:{event_type.value}"
        if key not in self.effects:
            from app.models.recurring_contract_emission import PostAcceptanceEffect
            self.effects[key] = PostAcceptanceEffect(effect_id=key, owner_uid=owner_uid, company_id=company_id, invoice_id=invoice_id, event_type=event_type)
        return self.effects[key]

    def complete(self, effect, *, result=None, sandbox=True):
        self.effects[effect.effect_id] = effect.model_copy(update={"status": "COMPLETED", "result": result or {}})

    def fail(self, effect, *, error, sandbox=True):
        self.effects[effect.effect_id] = effect.model_copy(update={"status": "FAILED", "error": error})


class Outbox:
    def __init__(self):
        self.command = RecurringContractEmissionOutboxCommand(owner_uid="owner", company_id="company", contract_id="contract", occurrence_id="occ", attempt_id="attempt")
        self.finished = []

    def claim(self, **kwargs):
        self.command = self.command.model_copy(update={"status": "processing", "lease_owner": kwargs["worker_id"], "fencing_token": 1, "attempt_count": 1})
        return self.command

    def finish(self, **kwargs):
        self.finished.append(kwargs)
        return self.command


def contract():
    value = RecurringContract(
        owner_uid="owner", company_id="company", client_id="client", client_name_snapshot="Client",
        start_date=date(2026, 1, 1), billing_anchor_date=date(2026, 1, 1), billing_day=1,
        status="active", ecf_type="E31", lines=(RecurringContractLine(name="Service", unit_price=100),),
    )
    return value.add_terms_version(ContractTermsVersion(version=1, effective_from=date(2026, 1, 1), ecf_type="E31", lines=value.lines))


def prepared():
    return RecurringContractBillingService.prepare_invoice(contract(), occurrence_date=date(2026, 1, 1), now=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_accepted_emission_uses_one_reserved_sequence():
    outbox, store, calls = Outbox(), Store(), []

    def consume(*args, **kwargs):
        calls.append(1)
        return "E310000000001", "log-1"

    worker = RecurringContractEmissionWorker(
        outbox=outbox, attempts_store=store, company_loader=lambda *_: {"companyRNC": "132109122"},
        sequence_consumer=consume, emitter=lambda *_args, **_kwargs: {"success": True, "dgiiStatus": "ACCEPTED", "encf": "E310000000001", "trackId": "track-1"},
    )
    result = worker.process(command_id="command", owner_uid="owner", company_id="company", worker_id="worker", prepared=prepared(), sandbox=True)
    assert result["status"] == "ACCEPTED"
    assert len(calls) == 1
    assert result["attempt"].status == FiscalAttemptStatus.ACCEPTED


def test_timeout_is_ambiguous_and_not_reemitted_by_reconciliation():
    outbox, store, calls = Outbox(), Store(), []

    def consume(*args, **kwargs):
        calls.append(1)
        return "E310000000001", "log-1"

    worker = RecurringContractEmissionWorker(
        outbox=outbox, attempts_store=store, company_loader=lambda *_: {}, sequence_consumer=consume,
        emitter=lambda *_args, **_kwargs: {"success": False, "dgiiStatus": "TIMEOUT", "trackId": "track-1"},
    )
    result = worker.process(command_id="command", owner_uid="owner", company_id="company", worker_id="worker", prepared=prepared())
    assert result["status"] == "TIMEOUT"
    attempt = result["attempt"]
    reconciliation = RecurringContractReconciliationService(attempts_store=store, status_checker=lambda *_args, **_kwargs: {"success": True, "dgiiStatus": "PENDING"})
    resolved = reconciliation.reconcile(attempt, company={}, sandbox=True)
    assert resolved.status == FiscalAttemptStatus.PENDING
    assert len(calls) == 1


def test_reconciliation_can_resolve_accepted():
    attempt = RecurringContractEmissionAttempt(
        owner_uid="owner", company_id="company", contract_id="contract", occurrence_id="occurrence",
        request_hash="hash", ecf_type="E31", status=FiscalAttemptStatus.PENDING, track_id="track-1",
    )
    reconciliation = RecurringContractReconciliationService(attempts_store=Store(), status_checker=lambda *_args, **_kwargs: {"success": True, "dgiiStatus": "ACCEPTED", "responseBody": {"ok": True}})
    assert reconciliation.reconcile(attempt, company={}).status == FiscalAttemptStatus.ACCEPTED


def test_post_acceptance_effects_are_idempotent():
    store, calls = Store(), []

    def handler(**kwargs):
        calls.append(kwargs["invoice_id"])
        return {"posted": True}

    service = RecurringContractPostAcceptanceService(
        effects_store=store,
        effect_handlers={PostAcceptanceEffectType.ACCOUNTING: handler},
    )
    invoice = {"dgiiStatus": "ACCEPTED"}
    first = service.process(owner_uid="owner", company_id="company", invoice_id="invoice-1", invoice=invoice)
    second = service.process(owner_uid="owner", company_id="company", invoice_id="invoice-1", invoice=invoice)
    assert first["success"] and second["success"]
    assert calls == ["invoice-1"]


def test_post_acceptance_rejects_non_accepted_invoice():
    service = RecurringContractPostAcceptanceService(effects_store=Store(), effect_handlers={})
    result = service.process(owner_uid="owner", company_id="company", invoice_id="invoice-1", invoice={"dgiiStatus": "PENDING"})
    assert result["status"] == "not_accepted"
