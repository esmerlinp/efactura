from unittest.mock import MagicMock, patch


def test_ajax_create_client_rejects_existing_rnc(client):
    with client.session_transaction() as session:
        session["user"] = {"ownerUID": "owner-1"}
        session["selected_company_id"] = "company-1"
        session["is_sandbox_mode"] = True

    existing = {"id": "client-1", "rnc": "131880681", "razonSocial": "Cliente Existente"}
    with patch("app.web.clients.check_permission", return_value=True), \
         patch("app.web.clients.DatabaseService.get_client_by_rnc", return_value=existing), \
         patch("app.web.clients.DatabaseService.save_client") as save_client:
        response = client.post("/clients/ajax_create", json={
            "rnc": "131-880681",
            "razonSocial": "Otro nombre",
        })

    assert response.status_code == 409
    assert response.get_json()["code"] == "CLIENT_ALREADY_EXISTS"
    assert response.get_json()["client"] == existing
    save_client.assert_not_called()


def test_ajax_create_client_allows_same_rnc_in_different_company(client):
    with client.session_transaction() as session:
        session["user"] = {"ownerUID": "owner-1"}
        session["selected_company_id"] = "company-2"
        session["is_sandbox_mode"] = True

    with patch("app.web.clients.check_permission", return_value=True), \
         patch("app.web.clients.DatabaseService.get_client_by_rnc", return_value=None), \
         patch("app.web.clients.DatabaseService.save_client"), \
         patch("app.services.audit_service.AuditService.log_from_request"):
        response = client.post("/clients/ajax_create", json={
            "rnc": "131880681",
            "razonSocial": "Cliente Empresa Dos",
        })

    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_global_account_reuses_identity_and_separates_membership():
    from app.services.customer_account_service import CustomerAccountService

    identity_ref = MagicMock()
    identity_ref.get.return_value.exists = True
    identity_ref.get.return_value.to_dict.return_value = {"accountId": "acct-1"}
    account_ref = MagicMock()
    account_doc = MagicMock()
    account_doc.exists = True
    account_doc.to_dict.return_value = {"rncNormalized": "131880681"}
    account_ref.document.return_value.get.return_value = account_doc
    firestore = MagicMock()
    firestore.collection.side_effect = lambda name: {
        "customer_identity_keys": MagicMock(document=lambda _: identity_ref),
        "customer_accounts": account_ref,
    }[name]

    contact = {"id": "client-2", "types": ["cliente"], "rnc": "131-880681", "email": "c@example.com", "razonSocial": "Cliente"}
    with patch("app.services.customer_account_service.db_firestore", firestore), \
         patch("app.services.customer_account_service.firebase_initialized", True), \
         patch.object(CustomerAccountService, "company_portal_enabled", return_value=True):
        result = CustomerAccountService.ensure_for_contact(contact, "owner", "company-2", False)

    assert result == "acct-1"
    membership = account_ref.document.return_value.collection.return_value.document.return_value.set
    membership.assert_called_once()
    assert membership.call_args.args[0]["companyId"] == "company-2"
    assert membership.call_args.args[0]["sandbox"] is False
