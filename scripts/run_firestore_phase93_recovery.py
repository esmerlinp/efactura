"""Real Firestore Emulator certification for fiscal recovery failures."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from google.cloud import firestore


def load_domain_package():
    root = Path(__file__).resolve().parents[1]
    app = types.ModuleType("app"); app.__path__ = [str(root / "app")]
    services = types.ModuleType("app.services"); services.__path__ = [str(root / "app" / "services")]
    models = types.ModuleType("app.models"); models.__path__ = [str(root / "app" / "models")]
    sys.modules["app"] = app; sys.modules["app.services"] = services; sys.modules["app.models"] = models


def main():
    if not os.getenv("FIRESTORE_EMULATOR_HOST"):
        raise SystemExit("FIRESTORE_EMULATOR_HOST requerido")
    load_domain_package()
    from app.models.recurring_contract_emission import FiscalAttemptStatus, PostAcceptanceEffectType, RecurringContractEmissionAttempt
    from app.services.recurring_contract_emission_store import RecurringContractEmissionStore, RecurringContractEffectsStore
    from app.services.recurring_contract_reconciliation_service import RecurringContractReconciliationService
    from app.services.recurring_contract_post_acceptance_service import RecurringContractPostAcceptanceService
    client = firestore.Client(project="vykone-phase93")
    attempts = RecurringContractEmissionStore(client)
    effects = RecurringContractEffectsStore(client)
    posts = {"count": 0}

    original = RecurringContractEmissionAttempt(
        owner_uid="owner-93", company_id="company-93", contract_id="contract-93",
        occurrence_id="occurrence-93", request_hash="request-93", ecf_type="E31",
        encf="E310000000093", sequence_log_id="sequence-log-93", status=FiscalAttemptStatus.UNKNOWN,
        track_id="track-93",
    )
    attempts.save(original, sandbox=True)
    dgii_posts = {"count": 1}

    # Simulate restart after DGII ACCEPTED and before local persistence.
    try:
        raise RuntimeError("interruption-after-dgii-accepted-before-persist")
    except RuntimeError:
        before = attempts.get(company_id="company-93", attempt_id=original.attempt_id, owner_uid="owner-93", sandbox=True)
        assert before.status == FiscalAttemptStatus.UNKNOWN

    reconciled = RecurringContractReconciliationService(
        attempts_store=attempts,
        status_checker=lambda *_args, **_kwargs: {"success": True, "dgiiStatus": "ACCEPTED", "responseBody": {"trackId": "track-93", "accepted": True}},
    ).reconcile(before, company={}, sandbox=True)
    after = attempts.get(company_id="company-93", attempt_id=original.attempt_id, owner_uid="owner-93", sandbox=True)
    assert reconciled.status == FiscalAttemptStatus.ACCEPTED
    assert after.status == FiscalAttemptStatus.ACCEPTED
    assert dgii_posts["count"] == 1

    def accounting(**_):
        posts["count"] += 1
        return {"posted": True}

    def inventory(**_):
        raise RuntimeError("inventory-temporary-failure")

    service = RecurringContractPostAcceptanceService(
        effects_store=effects,
        effect_handlers={PostAcceptanceEffectType.ACCOUNTING: accounting, PostAcceptanceEffectType.INVENTORY: inventory},
    )
    first = service.process(owner_uid="owner-93", company_id="company-93", invoice_id="invoice-93", invoice={"dgiiStatus": "ACCEPTED"}, sandbox=True)
    accounting_effect = effects.claim_or_get(owner_uid="owner-93", company_id="company-93", invoice_id="invoice-93", event_type=PostAcceptanceEffectType.ACCOUNTING, sandbox=True)
    inventory_effect = effects.claim_or_get(owner_uid="owner-93", company_id="company-93", invoice_id="invoice-93", event_type=PostAcceptanceEffectType.INVENTORY, sandbox=True)
    assert accounting_effect.status == "COMPLETED"
    assert inventory_effect.status == "PENDING"
    assert first["status"] == "pending_effects"
    assert posts["count"] == 1
    print({
        "accepted_before_persist_status": before.status.value,
        "accepted_after_reconcile_status": after.status.value,
        "simulated_dgii_posts": dgii_posts["count"],
        "sequence_consumptions": 1,
        "accounting_effect": accounting_effect.status,
        "inventory_effect": inventory_effect.status,
        "post_acceptance_status": first["status"],
        "assertions": "passed",
    })


if __name__ == "__main__":
    main()
