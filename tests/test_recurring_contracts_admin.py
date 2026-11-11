def test_admin_blueprint_is_registered_as_separate_domain_ui():
    from flask import Flask
    from app.web.recurring_contracts_admin import recurring_contracts_admin_bp

    app = Flask(__name__)
    app.register_blueprint(recurring_contracts_admin_bp)
    assert recurring_contracts_admin_bp.name == "recurring_contracts_admin"
    assert any(rule.rule.startswith("/operations/recurring-contracts") for rule in app.url_map.iter_rules())


def test_admin_repository_merges_existing_document_and_keeps_schema_version(monkeypatch):
    from datetime import date

    from app.models.recurring_contract import ContractTermsVersion, RecurringContract, RecurringContractLine
    from app.services.db_service import DatabaseService
    from app.web import recurring_contracts_admin

    line = RecurringContractLine(name="Servicio", unit_price=100)
    contract = RecurringContract(
        owner_uid="owner", company_id="company", client_id="client",
        start_date=date(2026, 1, 1), billing_anchor_date=date(2026, 1, 1),
        billing_day=1, status="active", ecf_type="E31", lines=(line,),
    ).add_terms_version(ContractTermsVersion(version=1, effective_from=date(2026, 1, 1), ecf_type="E31", lines=(line,)))

    existing = contract.model_dump(mode="json")
    existing.update({
        "schemaVersion": 2,
        "branchId": "branch-1",
        "projectId": "project-1",
        "contractLines": [{"name": "Servicio"}],
        "legacySource": {"id": "legacy-1"},
        "createdAt": "2026-01-01T00:00:00+00:00",
    })
    saved = {}

    monkeypatch.setattr(
        DatabaseService, "get_contract",
        classmethod(lambda cls, *args, **kwargs: dict(existing)),
    )

    def fake_save(cls, owner_uid, contract_id, payload, **kwargs):
        saved.update(payload)
        return payload

    monkeypatch.setattr(DatabaseService, "save_contract", classmethod(fake_save))

    repo = recurring_contracts_admin._DatabaseContractRepository("owner", "company", True)
    repo.update(contract)

    assert saved["branchId"] == "branch-1"
    assert saved["projectId"] == "project-1"
    assert saved["contractLines"] == [{"name": "Servicio"}]
    assert saved["legacySource"] == {"id": "legacy-1"}
    assert saved["createdAt"] == "2026-01-01T00:00:00+00:00"
    assert saved["schemaVersion"] == 2
    assert saved["ecf_type"] == "E31"


def test_contract_from_data_ignores_legacy_extra_fields():
    from datetime import date

    from app.models.recurring_contract import ContractTermsVersion, RecurringContract, RecurringContractLine
    from app.web import recurring_contracts_admin

    line = RecurringContractLine(name="Servicio", unit_price=100)
    domain = RecurringContract(
        owner_uid="owner", company_id="company", client_id="client",
        start_date=date(2026, 1, 1), billing_anchor_date=date(2026, 1, 1),
        billing_day=1, status="active", ecf_type=None, lines=(line,),
        needs_fiscal_review=True,
    ).add_terms_version(ContractTermsVersion(version=1, effective_from=date(2026, 1, 1), lines=(line,)))

    doc = domain.model_dump(mode="json")
    doc.update({
        "schemaVersion": 2,
        "branchId": "branch-1",
        "projectId": None,
        "contractLines": [{"name": "Servicio"}],
        "ownerUID": "owner",
        "legacySource": {"id": "legacy-1"},
    })

    contract = recurring_contracts_admin._contract_from_data(doc)

    assert contract is not None
    assert contract.needs_fiscal_review is True
    assert contract.ecf_type is None
    assert recurring_contracts_admin._contract_from_data({"schemaVersion": 1}) is None
