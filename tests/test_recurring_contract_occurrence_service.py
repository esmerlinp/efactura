from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Lock

import pytest

from app.models.recurring_contract import BillingFrequency, ContractTermsVersion, RecurringContract, RecurringContractLine
from app.models.recurring_contract_occurrence import BillingOccurrenceStatus
from app.services.recurring_contract_occurrence_service import (
    OccurrenceLeaseError,
    OccurrenceNotFoundError,
    RecurringContractOccurrenceService,
)


class Snapshot:
    def __init__(self, data=None):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class Ref:
    def __init__(self, db, path):
        self.db = db
        self.path = path

    def get(self):
        with self.db.lock:
            return Snapshot(self.db.docs.get(self.path))


class Collection:
    def __init__(self, db, path):
        self.db = db
        self.path = path

    def document(self, doc_id):
        return Ref(self.db, f"{self.path}/{doc_id}")


class Company:
    def __init__(self, db, path):
        self.db = db
        self.path = path

    def collection(self, name):
        return Collection(self.db, f"{self.path}/{name}")


class Companies:
    def __init__(self, db):
        self.db = db

    def document(self, doc_id):
        return Company(self.db, f"companies/{doc_id}")


class Transaction:
    def __init__(self, db):
        self.db = db
        self.reads = []
        self.writes = []

    def get(self, ref):
        with self.db.lock:
            snapshot = Snapshot(self.db.docs.get(ref.path))
        self.reads.append((ref.path, snapshot._data.copy() if snapshot.exists else None))
        return snapshot

    def create(self, ref, data):
        self.writes.append(("create", ref.path, dict(data)))

    def set(self, ref, data):
        self.writes.append(("set", ref.path, dict(data)))


class InMemoryFirestore:
    def __init__(self):
        self.docs = {}
        self.lock = Lock()

    def collection(self, name):
        if name != "companies":
            raise AssertionError(name)
        return Companies(self)

    def transaction(self):
        return Transaction(self)

    def commit(self, transaction):
        with self.lock:
            for path, expected in transaction.reads:
                actual = self.docs.get(path)
                if actual != expected:
                    raise RuntimeError("transaction conflict")
            for operation, path, data in transaction.writes:
                if operation == "create" and path in self.docs:
                    raise RuntimeError("already exists")
                self.docs[path] = data


class TransactionalFirestore(InMemoryFirestore):
    pass


def transactional_operation(service, operation):
    transaction = service.db.transaction()
    result = operation(transaction)
    service.db.commit(transaction)
    return result


def make_contract(company_id="company-1", owner_uid="owner-1"):
    contract = RecurringContract(
        owner_uid=owner_uid,
        company_id=company_id,
        contract_number="CONT-1",
        client_id="client-1",
        client_name_snapshot="Cliente",
        start_date=date(2026, 1, 1),
        billing_anchor_date=date(2026, 1, 1),
        billing_day=1,
        frequency=BillingFrequency.MONTHLY,
        status="active",
        ecf_type="E31",
        lines=(RecurringContractLine(name="Servicio", unit_price=100),),
    )
    return contract.add_terms_version(ContractTermsVersion(
        version=1,
        effective_from=date(2026, 1, 1),
        ecf_type="E31",
        lines=contract.lines,
    ))


@pytest.fixture
def service():
    db = InMemoryFirestore()
    result = RecurringContractOccurrenceService(db, clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    result._run_transaction = lambda operation: transactional_operation(result, operation)
    return result


def create(service, company_id="company-1", owner_uid="owner-1"):
    return service.create_idempotent(
        owner_uid=owner_uid,
        company_id=company_id,
        contract_id="contract-1",
        billing_period_key="contract-1:2026-01-01:2026-01-31",
        period_start="2026-01-01",
        period_end="2026-01-31",
        occurrence_date="2026-01-01",
    )


def test_create_is_idempotent(service):
    first = create(service)
    second = create(service)
    assert first.id == second.id
    assert len(service.db.docs) == 1


def test_concurrent_creation_has_one_logical_occurrence(service):
    def run(_):
        return create(service).id

    with ThreadPoolExecutor(max_workers=16) as executor:
        ids = list(executor.map(run, range(64)))
    assert len(set(ids)) == 1
    assert len(service.db.docs) == 1


def test_scope_isolation(service):
    create(service, company_id="company-a", owner_uid="owner-a")
    with pytest.raises(PermissionError):
        service.get(owner_uid="owner-b", company_id="company-a", occurrence_id=next(iter(service.db.docs.values()))["id"])


def test_missing_occurrence_is_rejected(service):
    with pytest.raises(OccurrenceNotFoundError):
        service.acquire_lease(
            owner_uid="owner-1", company_id="company-1", occurrence_id="missing", worker_id="worker-1"
        )


def test_lease_blocks_other_worker_until_expiry(service):
    occurrence = create(service)
    first = service.acquire_lease(
        owner_uid="owner-1", company_id="company-1", occurrence_id=occurrence.id, worker_id="worker-1"
    )
    with pytest.raises(OccurrenceLeaseError):
        service.acquire_lease(
            owner_uid="owner-1", company_id="company-1", occurrence_id=occurrence.id, worker_id="worker-2"
        )
    assert first.fencing_token == 1


def test_expired_lease_can_be_recovered_with_monotonic_fencing(service):
    occurrence = create(service)
    first = service.acquire_lease(
        owner_uid="owner-1", company_id="company-1", occurrence_id=occurrence.id, worker_id="worker-1", ttl_seconds=1
    )
    service.clock = lambda: datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
    second = service.acquire_lease(
        owner_uid="owner-1", company_id="company-1", occurrence_id=occurrence.id, worker_id="worker-2"
    )
    assert second.fencing_token > first.fencing_token
    with pytest.raises(OccurrenceLeaseError):
        service.transition_with_fencing(
            owner_uid="owner-1", company_id="company-1", occurrence_id=occurrence.id,
            worker_id="worker-1", fencing_token=first.fencing_token,
            target=BillingOccurrenceStatus.PENDING_RECONCILIATION,
        )


def test_valid_fencing_can_transition(service):
    occurrence = create(service)
    leased = service.acquire_lease(
        owner_uid="owner-1", company_id="company-1", occurrence_id=occurrence.id, worker_id="worker-1"
    )
    updated = service.transition_with_fencing(
        owner_uid="owner-1", company_id="company-1", occurrence_id=occurrence.id,
        worker_id="worker-1", fencing_token=leased.fencing_token,
        target=BillingOccurrenceStatus.PENDING_RECONCILIATION,
    )
    assert updated.status == BillingOccurrenceStatus.PENDING_RECONCILIATION
