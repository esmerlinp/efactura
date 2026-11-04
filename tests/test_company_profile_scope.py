from unittest.mock import patch

from app.services.db_service import DatabaseService


def test_get_company_profile_requires_company_id():
    with patch.object(DatabaseService, "get_company") as get_company:
        profile = DatabaseService.get_company_profile("owner-a")

    assert profile is None
    get_company.assert_not_called()


def test_get_company_profile_uses_requested_company_only():
    company = {"id": "company-a", "owner_uid": "owner-a", "status": "active"}
    with patch.object(DatabaseService, "get_company", return_value=company), \
         patch.object(DatabaseService, "get_plan", return_value=None):
        profile = DatabaseService.get_company_profile("owner-a", company_id="company-a")

    assert profile["ownerUID"] == "owner-a"
    assert profile["companyName"] == ""
