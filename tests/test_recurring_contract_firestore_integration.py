"""Real Firestore Emulator certification tests.

Run with FIRESTORE_EMULATOR_HOST set and the certification environment:
  .venv-cert/bin/python -m pytest tests/test_recurring_contract_firestore_integration.py -q
"""

import os
import sys
import types
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("FIRESTORE_EMULATOR_HOST"),
    reason="FIRESTORE_EMULATOR_HOST no configurado",
)


def _load_domain_services():
    """Load domain modules without booting Flask/Firebase application factory."""
    root = Path(__file__).resolve().parents[1]
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = [str(root / "app")]
    services_pkg = types.ModuleType("app.services")
    services_pkg.__path__ = [str(root / "app" / "services")]
    models_pkg = types.ModuleType("app.models")
    models_pkg.__path__ = [str(root / "app" / "models")]
    sys.modules["app"] = app_pkg
    sys.modules["app.services"] = services_pkg
    sys.modules["app.models"] = models_pkg


@pytest.fixture(scope="module")
def firestore_client():
    try:
        from google.cloud import firestore
        return firestore.Client(project="vykone-certification")
    except Exception as exc:
        pytest.fail(f"SDK Firestore no disponible en entorno de certificación: {exc}")


@pytest.fixture
def services(firestore_client):
    _load_domain_services()
    from app.services.recurring_contract_occurrence_service import RecurringContractOccurrenceService
    from app.services.recurring_contract_outbox_service import OutboxCommandService
    return (
        RecurringContractOccurrenceService(firestore_client, clock=lambda: datetime.now(timezone.utc)),
        OutboxCommandService(firestore_client, clock=lambda: datetime.now(timezone.utc)),
    )


def test_real_firestore_concurrent_occurrence_creation(services):
    occurrences, _ = services

    def create(_):
        return occurrences.create_idempotent(
            owner_uid="owner-cert", company_id="company-cert", contract_id="contract-cert",
            billing_period_key="period-cert", period_start="2026-01-01", period_end="2026-01-31",
            occurrence_date="2026-01-01", sandbox=True,
        ).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(create, range(32)))
    assert len(set(ids)) == 1
    stored = occurrences.get(owner_uid="owner-cert", company_id="company-cert", occurrence_id=ids[0], sandbox=True)
    assert stored.billing_period_key == "period-cert"


def test_real_firestore_concurrent_outbox_creation(services):
    _, outbox = services

    def create(_):
        return outbox.create_idempotent(
            owner_uid="owner-cert", company_id="company-cert", contract_id="contract-cert",
            occurrence_id="occ-outbox-cert", attempt_id="attempt-cert", sandbox=True,
        ).command_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(create, range(32)))
    assert len(set(ids)) == 1


def test_real_firestore_lease_takeover_and_fencing(services):
    occurrences, _ = services
    occurrence = occurrences.create_idempotent(
        owner_uid="owner-cert", company_id="company-cert", contract_id="lease-contract",
        billing_period_key="lease-period", period_start="2026-01-01", period_end="2026-01-31",
        occurrence_date="2026-01-01", sandbox=True,
    )
    first = occurrences.acquire_lease(
        owner_uid="owner-cert", company_id="company-cert", occurrence_id=occurrence.id,
        worker_id="worker-one", ttl_seconds=1, sandbox=True,
    )
    import time
    time.sleep(1.2)
    second = occurrences.acquire_lease(
        owner_uid="owner-cert", company_id="company-cert", occurrence_id=occurrence.id,
        worker_id="worker-two", ttl_seconds=30, sandbox=True,
    )
    assert second.fencing_token > first.fencing_token
    with pytest.raises(Exception):
        occurrences.transition_with_fencing(
            owner_uid="owner-cert", company_id="company-cert", occurrence_id=occurrence.id,
            worker_id="worker-one", fencing_token=first.fencing_token,
            target="pending_reconciliation", sandbox=True,
        )


def test_real_firestore_company_and_environment_isolation(services):
    occurrences, outbox = services
    sandbox = occurrences.create_idempotent(
        owner_uid="owner-a", company_id="company-a", contract_id="same-contract",
        billing_period_key="same-period", period_start="2026-01-01", period_end="2026-01-31",
        occurrence_date="2026-01-01", sandbox=True,
    )
    production = occurrences.create_idempotent(
        owner_uid="owner-a", company_id="company-a", contract_id="same-contract",
        billing_period_key="same-period", period_start="2026-01-01", period_end="2026-01-31",
        occurrence_date="2026-01-01", sandbox=False,
    )
    other_company = occurrences.create_idempotent(
        owner_uid="owner-b", company_id="company-b", contract_id="same-contract",
        billing_period_key="same-period", period_start="2026-01-01", period_end="2026-01-31",
        occurrence_date="2026-01-01", sandbox=True,
    )
    assert len({sandbox.id, production.id, other_company.id}) == 3
    with pytest.raises(PermissionError):
        occurrences.get(owner_uid="owner-b", company_id="company-a", occurrence_id=sandbox.id, sandbox=True)
    command = outbox.create_idempotent(
        owner_uid="owner-a", company_id="company-a", contract_id="same-contract",
        occurrence_id=sandbox.id, attempt_id="attempt-isolation", sandbox=True,
    )
    assert command.company_id == "company-a"
