from unittest.mock import patch

from app.services.db_service import DatabaseService


def test_contract_invoice_history_accepts_both_contract_id_conventions():
    invoices = [
        {"id": "one", "contractId": "contract-1"},
        {"id": "two", "contract_id": "contract-1"},
        {"id": "three", "contractId": "contract-2"},
    ]
    with patch.object(DatabaseService, "get_invoices", return_value=invoices):
        result = DatabaseService.get_invoices_by_contract("owner", " contract-1 ", company_id="company", sandbox=True)
    assert {invoice["id"] for invoice in result} == {"one", "two"}
