"""Run real Firestore contract certification in a clean interpreter."""

from __future__ import annotations

import os
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore


def load_domain_package():
    root = Path(__file__).resolve().parents[1]
    app = types.ModuleType("app")
    app.__path__ = [str(root / "app")]
    services = types.ModuleType("app.services")
    services.__path__ = [str(root / "app" / "services")]
    models = types.ModuleType("app.models")
    models.__path__ = [str(root / "app" / "models")]
    sys.modules["app"] = app
    sys.modules["app.services"] = services
    sys.modules["app.models"] = models

def main():
    if not os.getenv("FIRESTORE_EMULATOR_HOST"):
        raise SystemExit("FIRESTORE_EMULATOR_HOST requerido")
    load_domain_package()
    client = firestore.Client(project="vykone-certification")
    from app.services.recurring_contract_occurrence_service import RecurringContractOccurrenceService
    from app.services.recurring_contract_outbox_service import OutboxCommandService
    clock = lambda: datetime.now(timezone.utc)
    occurrences = RecurringContractOccurrenceService(client, clock=clock)
    outbox = OutboxCommandService(client, clock=clock)

    def create(_):
        return occurrences.create_idempotent(
            owner_uid="owner-cert", company_id="company-cert", contract_id="contract-cert",
            billing_period_key="period-cert", period_start="2026-01-01", period_end="2026-01-31",
            occurrence_date="2026-01-01", sandbox=True,
        ).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        occurrence_ids = list(executor.map(create, range(32)))
    assert len(set(occurrence_ids)) == 1
    occurrence = occurrences.get(owner_uid="owner-cert", company_id="company-cert", occurrence_id=occurrence_ids[0], sandbox=True)
    assert occurrence and occurrence.company_id == "company-cert"

    def create_command(_):
        return outbox.create_idempotent(
            owner_uid="owner-cert", company_id="company-cert", contract_id="contract-cert",
            occurrence_id=occurrence.id, attempt_id="attempt-cert", sandbox=True,
        ).command_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        command_ids = list(executor.map(create_command, range(32)))
    assert len(set(command_ids)) == 1
    command = outbox.claim(owner_uid="owner-cert", company_id="company-cert", command_id=command_ids[0], worker_id="worker-one", ttl_seconds=1, sandbox=True)
    time.sleep(1.2)
    recovered = outbox.recover_expired(owner_uid="owner-cert", company_id="company-cert", command_id=command.command_id, sandbox=True)
    assert recovered.lease_owner is None
    from app.models.recurring_contract_emission import FiscalAttemptStatus, PostAcceptanceEffectType, RecurringContractEmissionAttempt
    from app.services.recurring_contract_emission_store import RecurringContractEmissionStore, RecurringContractEffectsStore
    from app.services.recurring_contract_reconciliation_service import RecurringContractReconciliationService
    from app.services.recurring_contract_post_acceptance_service import RecurringContractPostAcceptanceService
    attempt_store = RecurringContractEmissionStore(client)
    attempt = RecurringContractEmissionAttempt(
        owner_uid="owner-cert", company_id="company-cert", contract_id="contract-cert",
        occurrence_id=occurrence.id, request_hash="cert-hash", ecf_type="E31",
        status=FiscalAttemptStatus.UNKNOWN, track_id="track-cert",
    )
    attempt_store.save(attempt, sandbox=True)
    reconciliation = RecurringContractReconciliationService(
        attempts_store=attempt_store,
        status_checker=lambda *_args, **_kwargs: {"success": True, "dgiiStatus": "ACCEPTED", "responseBody": {"emulator": True}},
    )
    resolved = reconciliation.reconcile(attempt, company={}, sandbox=True)
    persisted = attempt_store.get(company_id="company-cert", attempt_id=attempt.attempt_id, owner_uid="owner-cert", sandbox=True)
    assert resolved.status == FiscalAttemptStatus.ACCEPTED
    assert persisted.status == FiscalAttemptStatus.ACCEPTED
    effects_store = RecurringContractEffectsStore(client)
    effect = effects_store.claim_or_get(owner_uid="owner-cert", company_id="company-cert", invoice_id="invoice-cert", event_type=PostAcceptanceEffectType.ACCOUNTING, sandbox=True)
    effects_store.complete(effect, result={"posted": True}, sandbox=True)
    effect_again = effects_store.claim_or_get(owner_uid="owner-cert", company_id="company-cert", invoice_id="invoice-cert", event_type=PostAcceptanceEffectType.ACCOUNTING, sandbox=True)
    assert effect_again.status == "COMPLETED"
    print({
        "firestore_emulator_host": os.environ["FIRESTORE_EMULATOR_HOST"],
        "occurrence_id": occurrence.id,
        "command_id": command.command_id,
        "fencing_token": command.fencing_token,
        "recovered_status": recovered.status.value,
        "reconciled_attempt_status": persisted.status.value,
        "post_acceptance_effect_status": effect_again.status,
        "assertions": "passed",
    })


if __name__ == "__main__":
    main()
