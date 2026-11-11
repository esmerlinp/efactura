from datetime import datetime, timezone

from app.models.recurring_contract_emission import FiscalAttemptStatus, PostAcceptanceEffectType, RecurringContractEmissionAttempt
from app.services.recurring_contract_post_acceptance_service import RecurringContractPostAcceptanceService
from app.services.recurring_contract_reconciliation_service import RecurringContractReconciliationService


class AttemptStore:
    def __init__(self):
        self.saved = []

    def save(self, attempt, sandbox=True):
        self.saved.append(attempt)


class Effect:
    def __init__(self, status="PENDING"):
        self.status = status
        self.result = None


class EffectsStore:
    def __init__(self):
        self.effects = {}

    def claim_or_get(self, **kwargs):
        key = f"{kwargs['invoice_id']}:{kwargs['event_type'].value}"
        return self.effects.setdefault(key, Effect())

    def complete(self, effect, *, result, sandbox=True):
        effect.status = "COMPLETED"
        effect.result = result

    def fail(self, effect, *, error, sandbox=True):
        effect.status = "FAILED"


def attempt(status=FiscalAttemptStatus.PENDING, track_id="track-1"):
    return RecurringContractEmissionAttempt(
        owner_uid="owner", company_id="company", contract_id="contract", occurrence_id="occurrence",
        request_hash="hash", ecf_type="E31", status=status, track_id=track_id,
    )


def test_missing_track_id_stays_unknown_and_persists():
    store = AttemptStore()
    value = attempt(track_id=None)
    result = RecurringContractReconciliationService(
        attempts_store=store, status_checker=lambda *_: {"success": True, "dgiiStatus": "ACCEPTED"}
    ).reconcile(value, company={})
    assert result.status == FiscalAttemptStatus.UNKNOWN
    assert store.saved[-1].status == FiscalAttemptStatus.UNKNOWN


def test_query_error_never_becomes_rejected():
    result = RecurringContractReconciliationService(
        attempts_store=AttemptStore(), status_checker=lambda *_args, **_kwargs: {"success": False, "message": "network"}
    ).reconcile(attempt(), company={})
    assert result.status == FiscalAttemptStatus.QUERY_ERROR


def test_accepted_status_is_persisted_by_reconciliation():
    store = AttemptStore()
    result = RecurringContractReconciliationService(
        attempts_store=store, status_checker=lambda *_args, **_kwargs: {"success": True, "dgiiStatus": "ACCEPTED"}
    ).reconcile(attempt(), company={})
    assert result.status == FiscalAttemptStatus.ACCEPTED
    assert store.saved[-1].status == FiscalAttemptStatus.ACCEPTED


def test_post_acceptance_effects_are_not_repeated_when_completed():
    store = EffectsStore()
    calls = []
    service = RecurringContractPostAcceptanceService(
        effects_store=store,
        effect_handlers={PostAcceptanceEffectType.ACCOUNTING: lambda **_: calls.append(1) or {"ok": True}},
    )
    invoice = {"dgiiStatus": "ACCEPTED"}
    service.process(owner_uid="owner", company_id="company", invoice_id="invoice", invoice=invoice)
    service.process(owner_uid="owner", company_id="company", invoice_id="invoice", invoice=invoice)
    assert len(calls) == 1


def test_post_acceptance_does_not_run_before_accepted():
    calls = []
    service = RecurringContractPostAcceptanceService(
        effects_store=EffectsStore(),
        effect_handlers={PostAcceptanceEffectType.ACCOUNTING: lambda **_: calls.append(1)},
    )
    result = service.process(owner_uid="owner", company_id="company", invoice_id="invoice", invoice={"dgiiStatus": "PENDING"})
    assert result["status"] == "not_accepted"
    assert calls == []
