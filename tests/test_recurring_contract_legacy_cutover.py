from app.services.recurring_contract_repository import RecurringContractRepository


def test_repository_only_exposes_schema_v2_contracts():
    class DB:
        @staticmethod
        def get_contracts(*args, **kwargs):
            return [{"id": "v2"}, {"id": "legacy"}]

        @staticmethod
        def get_contract(owner, contract_id, **kwargs):
            if contract_id == "v2":
                return {
                    "id": "v2", "schemaVersion": 2, "owner_uid": "owner", "company_id": "company",
                    "client_id": "client", "start_date": "2026-01-01", "billing_anchor_date": "2026-01-01",
                    "status": "active", "lines": [], "terms_versions": [],
                }
            return {"id": "legacy", "status": "Activo"}

    repository = RecurringContractRepository(DB)
    assert [contract.id for contract in repository.get_all("owner", "company", sandbox=True)] == ["v2"]
