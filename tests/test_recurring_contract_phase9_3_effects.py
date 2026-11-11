from app.models.recurring_contract_emission import FiscalAttemptStatus, PostAcceptanceEffectType
from app.services.recurring_contract_post_acceptance_service import RecurringContractPostAcceptanceService
from app.services.recurring_contract_reconciliation_service import RecurringContractReconciliationService


class Effect:
    def __init__(self, status="PENDING", result=None):
        self.status = status
        self.result = result


class Store:
    def __init__(self):
        self.effects = {}

    def claim_or_get(self, **kwargs):
        key = f"{kwargs['invoice_id']}:{kwargs['event_type'].value}"
        return self.effects.setdefault(key, Effect())

    def complete(self, effect, *, result, sandbox=True):
        effect.status = "COMPLETED"
        effect.result = result

    def fail(self, effect, *, error, sandbox=True):
        effect.status = "PENDING"


def test_completed_accounting_is_not_repeated_while_inventory_retries():
    store = Store()
    calls = {"accounting": 0, "inventory": 0}

    def accounting(**_):
        calls["accounting"] += 1
        return {"posted": True}

    def inventory(**_):
        calls["inventory"] += 1
        if calls["inventory"] == 1:
            raise RuntimeError("temporary")
        return {"committed": True}

    service = RecurringContractPostAcceptanceService(
        effects_store=store,
        effect_handlers={PostAcceptanceEffectType.ACCOUNTING: accounting, PostAcceptanceEffectType.INVENTORY: inventory},
    )
    first = service.process(owner_uid="o", company_id="c", invoice_id="i", invoice={"dgiiStatus": "ACCEPTED"})
    second = service.process(owner_uid="o", company_id="c", invoice_id="i", invoice={"dgiiStatus": "ACCEPTED"})
    assert first["status"] == "pending_effects"
    assert second["success"] is True
    assert calls == {"accounting": 1, "inventory": 2}


def test_no_track_id_remains_unknown_without_query():
    calls = []
    attempt = type("Attempt", (), {
        "status": FiscalAttemptStatus.TIMEOUT,
        "track_id": None,
        "model_copy": lambda self, update: type("Updated", (), {"status": update["status"]})(),
    })()
    result = RecurringContractReconciliationService(
        attempts_store=type("Store", (), {"save": lambda *_args, **_kwargs: calls.append(1)})(),
        status_checker=lambda *_args, **_kwargs: calls.append(2),
    ).reconcile(attempt, company={})
    assert result.status == FiscalAttemptStatus.UNKNOWN
    assert calls == [1]
