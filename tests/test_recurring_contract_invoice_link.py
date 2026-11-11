from datetime import date, datetime, timezone

from app.models.recurring_contract import ContractTermsVersion, RecurringContract, RecurringContractLine
from app.services.recurring_contract_billing_service import RecurringContractBillingService
from app.services.recurring_contract_occurrence_service import RecurringContractOccurrenceService


def contract():
    value = RecurringContract(
        owner_uid="owner", company_id="company", client_id="client",
        contract_number="CON-001",
        start_date=date(2026, 1, 1), billing_anchor_date=date(2026, 1, 1), billing_day=1,
        status="active", ecf_type="E31",
        lines=(RecurringContractLine(name="Service", unit_price=100),),
    )
    return value.add_terms_version(ContractTermsVersion(
        version=1, effective_from=date(2026, 1, 1), ecf_type="E31", lines=value.lines,
    ))


def test_prepared_invoice_is_linked_to_contract_as_draft():
    value = contract()
    prepared = RecurringContractBillingService.prepare_invoice(value)
    invoice = prepared.invoice
    assert invoice.contractId == value.id
    assert invoice.contractNumber == "CON-001"
    assert invoice.status == "Borrador"
    assert invoice.encf == ""
    assert invoice.model_dump(mode="json")["contractId"] == value.id


def test_prepared_hash_is_stable_across_repreparations():
    value = contract()
    first = RecurringContractBillingService.prepare_invoice(
        value, now=datetime(2026, 2, 1, tzinfo=timezone.utc)
    )
    second = RecurringContractBillingService.prepare_invoice(
        value, now=datetime(2026, 2, 2, tzinfo=timezone.utc)
    )
    assert first.invoice.id != second.invoice.id
    assert RecurringContractOccurrenceService._hash_prepared(first) == RecurringContractOccurrenceService._hash_prepared(second)


def test_prepared_hash_changes_when_billable_conditions_change():
    value = contract()
    first = RecurringContractBillingService.prepare_invoice(value)
    changed = value.add_terms_version(ContractTermsVersion(
        version=2, effective_from=date(2026, 3, 1), ecf_type="E31",
        lines=(RecurringContractLine(name="Service", unit_price=200),),
    ))
    second = RecurringContractBillingService.prepare_invoice(
        changed, occurrence_date=date(2026, 3, 1)
    )
    assert RecurringContractOccurrenceService._hash_prepared(first) != RecurringContractOccurrenceService._hash_prepared(second)


class _Doc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _Query:
    def __init__(self, docs):
        self._docs = docs

    def limit(self, _count):
        return self

    def where(self, filter=None):
        return self

    def get(self):
        return list(self._docs)


class _Collection:
    def __init__(self, docs):
        self._docs = docs

    def where(self, filter=None):
        return _Query(self._docs)

    def limit(self, _count):
        return _Query(self._docs)


def test_contract_invoice_list_projection_keeps_contract_link(app_context, monkeypatch):
    from app.services import db_service

    docs = [
        _Doc("inv-1", {
            "invoiceNumber": "BOR-001", "date": "2026-02-01", "status": "Borrador",
            "isQuotation": False, "total": 118.0,
            "contractId": "contract-1", "contractNumber": "CON-001", "occurrenceId": "occ-1",
        }),
        _Doc("inv-2", {
            "invoiceNumber": "BOR-002", "date": "2026-02-01", "status": "Borrador",
            "isQuotation": False, "total": 50.0, "contractId": "contract-2",
        }),
    ]
    monkeypatch.setattr(db_service, "firebase_initialized", True)
    monkeypatch.setattr(db_service, "_company_coll", lambda **_: _Collection(docs))

    invoices = db_service.DatabaseService.get_invoices_by_contract(
        "owner-link-projection", "contract-1", sandbox=True, company_id="company"
    )

    assert [inv["id"] for inv in invoices] == ["inv-1"]
    assert invoices[0]["contractId"] == "contract-1"
    assert invoices[0]["contractNumber"] == "CON-001"
    assert invoices[0]["occurrenceId"] == "occ-1"
