"""Non-destructive migration store with deterministic idempotency."""

from __future__ import annotations

from app.models.recurring_contract_migration import RecurringContractMigrationRecord


class InMemoryRecurringContractMigrationStore:
    def __init__(self):
        self.records = {}
        self.targets = {}

    def exists(self, source_id, *, owner_uid, company_id, sandbox, source_fingerprint):
        key = self.key(company_id, source_id, sandbox)
        record = self.records.get(key)
        return bool(record and record.source_fingerprint == source_fingerprint and record.owner_uid == owner_uid)

    def save_if_absent(self, record: RecurringContractMigrationRecord):
        key = self.key(record.company_id, record.source_id, record.sandbox)
        if key not in self.records:
            self.records[key] = record
            if record.target_document:
                self.targets[key] = record.target_document
        return self.records[key]

    @staticmethod
    def key(company_id, source_id, sandbox):
        return f"{company_id}:{'sandbox' if sandbox else 'production'}:{source_id}"

    def rollback(self, *, company_id, source_id, sandbox, owner_uid):
        key = self.key(company_id, source_id, sandbox)
        record = self.records.get(key)
        if not record or record.owner_uid != owner_uid:
            return False
        self.records.pop(key, None)
        self.targets.pop(key, None)
        return True
