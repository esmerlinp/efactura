"""Company-scoped repository for commercial V2 contracts."""

from __future__ import annotations

from app.models.recurring_contract import RecurringContract


class RecurringContractRepository:
    COLLECTION = "contracts"

    def __init__(self, database_service):
        self.db = database_service

    def get_all(self, owner_uid, company_id, sandbox=True):
        raw = self.db.get_contracts(owner_uid, company_id=company_id, sandbox=sandbox)
        result = []
        for item in raw:
            full = self.db.get_contract(owner_uid, item.get("id"), company_id=company_id, sandbox=sandbox)
            if not full or full.get("schemaVersion") != 2:
                continue
            fields = set(RecurringContract.model_fields)
            result.append(RecurringContract.model_validate({key: value for key, value in full.items() if key in fields}))
        return result

    def get(self, owner_uid, company_id, contract_id, sandbox=True):
        full = self.db.get_contract(owner_uid, contract_id, company_id=company_id, sandbox=sandbox)
        if not full or full.get("schemaVersion") != 2:
            return None
        fields = set(RecurringContract.model_fields)
        return RecurringContract.model_validate({key: value for key, value in full.items() if key in fields})
