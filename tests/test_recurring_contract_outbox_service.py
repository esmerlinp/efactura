from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock

import pytest

from app.models.recurring_contract_outbox import OutboxCommandStatus
from app.services.recurring_contract_outbox_service import OutboxLeaseError, OutboxCommandService


class Snapshot:
    def __init__(self, data=None):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class Ref:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def get(self):
        with self.db.lock:
            return Snapshot(self.db.docs.get(self.path))


class Collection:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def document(self, doc_id):
        return Ref(self.db, f"{self.path}/{doc_id}")


class Companies:
    def __init__(self, db):
        self.db = db

    def document(self, company_id):
        return Company(self.db, f"companies/{company_id}")


class Company:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def collection(self, name):
        return Collection(self.db, f"{self.path}/{name}")


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
        return Companies(self)

    def transaction(self):
        return Transaction(self)

    def commit(self, transaction):
        with self.lock:
            for path, expected in transaction.reads:
                if self.docs.get(path) != expected:
                    raise RuntimeError("transaction conflict")
            for operation, path, data in transaction.writes:
                if operation == "create" and path in self.docs:
                    raise RuntimeError("already exists")
                self.docs[path] = data


def build_service():
    db = InMemoryFirestore()
    service = OutboxCommandService(db, clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    service._run_transaction = lambda operation: _run_transaction(service, operation)
    return service


def _run_transaction(service, operation):
    transaction = service.db.transaction()
    result = operation(transaction)
    service.db.commit(transaction)
    return result


def create(service, company_id="company-1", owner_uid="owner-1"):
    return service.create_idempotent(
        owner_uid=owner_uid,
        company_id=company_id,
        contract_id="contract-1",
        occurrence_id="occurrence-1",
        attempt_id="attempt-1",
    )


def test_command_creation_is_idempotent(service=None):
    service = service or build_service()
    first = create(service)
    second = create(service)
    assert first.command_id == second.command_id
    assert len(service.db.docs) == 1


def test_concurrent_command_creation_has_one_command():
    service = build_service()
    with ThreadPoolExecutor(max_workers=16) as executor:
        commands = list(executor.map(lambda _: create(service).command_id, range(64)))
    assert len(set(commands)) == 1
    assert len(service.db.docs) == 1


def test_claim_blocks_second_worker():
    service = build_service()
    command = create(service)
    claimed = service.claim(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-1")
    with pytest.raises(OutboxLeaseError):
        service.claim(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-2")
    assert claimed.fencing_token == 1


def test_expired_lease_recovery_increments_fencing():
    current = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    db = InMemoryFirestore()
    service = OutboxCommandService(db, clock=lambda: current[0])
    service._run_transaction = lambda operation: _run_transaction(service, operation)
    command = create(service)
    first = service.claim(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-1", ttl_seconds=1)
    current[0] = datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
    recovered = service.recover_expired(owner_uid="owner-1", company_id="company-1", command_id=command.command_id)
    assert recovered.status == OutboxCommandStatus.RETRY_WAIT
    second = service.claim(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-2")
    assert second.fencing_token > first.fencing_token


def test_old_worker_cannot_finish_after_takeover():
    current = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    db = InMemoryFirestore()
    service = OutboxCommandService(db, clock=lambda: current[0])
    service._run_transaction = lambda operation: _run_transaction(service, operation)
    command = create(service)
    first = service.claim(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-1", ttl_seconds=1)
    current[0] = datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
    service.recover_expired(owner_uid="owner-1", company_id="company-1", command_id=command.command_id)
    second = service.claim(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-2")
    with pytest.raises(OutboxLeaseError):
        service.finish(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-1", fencing_token=first.fencing_token, success=True)
    assert second.fencing_token > first.fencing_token


def test_retryable_error_enters_retry_wait():
    service = build_service()
    command = create(service)
    claimed = service.claim(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-1")
    updated = service.finish(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-1", fencing_token=claimed.fencing_token, success=False, retryable=True, error="timeout", error_class="transient")
    assert updated.status == OutboxCommandStatus.RETRY_WAIT
    assert updated.last_error == "timeout"
    assert updated.error_class == "transient"


def test_non_retryable_error_is_terminal_failure():
    service = build_service()
    command = create(service)
    claimed = service.claim(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-1")
    updated = service.finish(owner_uid="owner-1", company_id="company-1", command_id=command.command_id, worker_id="worker-1", fencing_token=claimed.fencing_token, success=False, retryable=False, error="invalid payload", error_class="permanent")
    assert updated.status == OutboxCommandStatus.FAILED


def test_scope_isolation():
    service = build_service()
    command = create(service, company_id="company-a", owner_uid="owner-a")
    with pytest.raises(PermissionError):
        service.get(owner_uid="owner-b", company_id="company-a", command_id=command.command_id)


def test_sandbox_and_production_are_separate():
    service = build_service()
    sandbox = service.create_idempotent(owner_uid="owner-1", company_id="company-1", contract_id="contract-1", occurrence_id="occurrence-1", attempt_id="attempt-1", sandbox=True)
    production = service.create_idempotent(owner_uid="owner-1", company_id="company-1", contract_id="contract-1", occurrence_id="occurrence-1", attempt_id="attempt-1", sandbox=False)
    assert sandbox.command_id == production.command_id
    assert len(service.db.docs) == 2
