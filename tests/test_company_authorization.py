from unittest.mock import patch

from app.services.company_authorization import (
    CompanyAuthorizationError,
    get_company_access,
    require_company_access,
)


def test_access_uses_membership_permissions_for_selected_company():
    membership = {
        "status": "active",
        "role": "employee",
        "permissions": {"canInvoice": True},
    }
    company = {"id": "company-a", "owner_uid": "owner-a", "status": "active"}

    with patch("app.services.company_authorization.DatabaseService.get_membership", return_value=membership), \
         patch("app.services.company_authorization.DatabaseService.get_company", return_value=company):
        access = get_company_access("user-a", "company-a")

    assert access.company_id == "company-a"
    assert access.owner_uid == "owner-a"
    assert access.has_permission("canInvoice") is True
    assert access.has_permission("canModifySettings") is False


def test_access_rejects_inactive_membership_even_when_global_profile_would_allow():
    with patch("app.services.company_authorization.DatabaseService.get_membership", return_value={
        "status": "inactive",
        "role": "owner",
        "permissions": {"canInvoice": True},
    }), patch("app.services.company_authorization.DatabaseService.get_company") as get_company:
        access = get_company_access("user-a", "company-a")

    assert access is None
    get_company.assert_not_called()


def test_owner_role_is_derived_from_company_owner_and_active_membership():
    with patch("app.services.company_authorization.DatabaseService.get_membership", return_value={
        "status": "active",
        "role": "employee",
        "permissions": {},
    }), patch("app.services.company_authorization.DatabaseService.get_company", return_value={
        "id": "company-a",
        "owner_uid": "user-a",
        "status": "active",
    }):
        access = get_company_access("user-a", "company-a")

    assert access.role == "owner"
    assert access.has_permission("canManageSettings") is True


def test_require_company_access_raises_without_active_membership():
    with patch("app.services.company_authorization.DatabaseService.get_membership", return_value=None):
        try:
            require_company_access("user-a", "company-a")
        except CompanyAuthorizationError:
            return
    raise AssertionError("Se esperaba CompanyAuthorizationError")
