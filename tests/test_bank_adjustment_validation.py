import pytest


def test_bank_adjustment_requires_reason_and_nonzero_amount():
    from app.services.db_service import DatabaseService
    with pytest.raises(ValueError):
        DatabaseService.save_bank_adjustment("owner", "account", 0, "", company_id="company")
