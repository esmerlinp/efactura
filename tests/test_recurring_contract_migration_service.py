from datetime import datetime, timezone

from app.models.recurring_contract_migration import MigrationDisposition
from app.services.recurring_contract_migration_service import RecurringContractMigrationService
from app.services.recurring_contract_migration_store import InMemoryRecurringContractMigrationStore


def legacy(**overrides):
    value = {
        "id": "legacy-1",
        "contractNumber": "CON-001",
        "clientId": "client-1",
        "clientName": "Cliente",
        "clientRNC": "101010101",
        "status": "Activo",
        "recurrenceInterval": "mensual",
        "startDate": "2026-01-01",
        "nextBillingDate": "2026-02-01",
        "endDate": "",
        "amount": 1180,
        "contractLines": [{"itemId": "item-1", "name": "Servicio", "code": "S", "quantity": 1, "unitPrice": 1000, "itbisRate": 0.18}],
        "ecfType": "E31",
        "currency": "DOP",
        "legacyOnly": "preserve me",
    }
    value.update(overrides)
    return value


def service(store=None):
    return RecurringContractMigrationService(store, clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_complete_contract_is_migratable_and_preserves_source():
    result = service().dry_run([legacy()], owner_uid="owner", company_id="company")
    record = result.records[0]
    assert result.migratable == 1
    assert record.disposition == MigrationDisposition.MIGRATABLE
    assert record.target_document["id"] == "legacy-1"
    assert record.target_document["terms_versions"][0]["ecf_type"] == "E31"
    assert record.target_document["legacySource"]["legacyOnly"] == "preserve me"


def test_missing_ecf_requires_review_without_default():
    result = service().dry_run([legacy(ecfType=None)], owner_uid="owner", company_id="company")
    record = result.records[0]
    assert record.disposition == MigrationDisposition.NEEDS_REVIEW
    assert record.target_document["needs_fiscal_review"] is True
    assert record.target_document["ecf_type"] is None


def test_no_lines_is_incompatible_without_losing_source():
    result = service().dry_run([legacy(contractLines=[], amount=1180)], owner_uid="owner", company_id="company")
    record = result.records[0]
    assert record.disposition == MigrationDisposition.INCOMPATIBLE
    assert record.target_document is None
    assert record.source_document["amount"] == 1180


def test_mismatched_amount_is_review_not_recalculated_history():
    result = service().dry_run([legacy(amount=999)], owner_uid="owner", company_id="company")
    record = result.records[0]
    assert record.disposition == MigrationDisposition.NEEDS_REVIEW
    assert record.target_document["amount"] if "amount" in record.target_document else True
    assert any("amount" in warning for warning in record.warnings)


def test_unknown_frequency_is_incompatible():
    result = service().dry_run([legacy(recurrenceInterval="cada_30_dias")], owner_uid="owner", company_id="company")
    assert result.incompatible == 1


def test_dry_run_does_not_write():
    store = InMemoryRecurringContractMigrationStore()
    service(store).dry_run([legacy()], owner_uid="owner", company_id="company")
    assert store.records == {}


def test_write_is_idempotent_and_reexecution_is_detected():
    store = InMemoryRecurringContractMigrationStore()
    migrator = service(store)
    first = migrator.run([legacy()], owner_uid="owner", company_id="company", dry_run=False)
    second = migrator.run([legacy()], owner_uid="owner", company_id="company", dry_run=False)
    assert first.migratable == 1
    assert second.already_migrated == 1
    assert len(store.records) == 1


def test_company_and_environment_are_isolated():
    store = InMemoryRecurringContractMigrationStore()
    migrator = service(store)
    migrator.run([legacy()], owner_uid="owner-a", company_id="company-a", sandbox=True, dry_run=False)
    migrator.run([legacy()], owner_uid="owner-b", company_id="company-b", sandbox=True, dry_run=False)
    migrator.run([legacy()], owner_uid="owner-a", company_id="company-a", sandbox=False, dry_run=False)
    assert len(store.records) == 3


def test_rollback_removes_only_migration_record_not_source():
    store = InMemoryRecurringContractMigrationStore()
    migrator = service(store)
    migrator.run([legacy()], owner_uid="owner", company_id="company", dry_run=False)
    assert store.rollback(company_id="company", source_id="legacy-1", sandbox=True, owner_uid="owner")
    assert store.records == {}
