from unittest.mock import patch


def test_reconciliation_route_requires_authentication(client):
    response = client.get("/admin/cxp-reconciliation")
    assert response.status_code in (302, 401)


def test_reconciliation_route_requires_permission(client, session):
    with session:
        session["user"] = {"role": "member", "ownerUID": "owner"}
    with patch("app.web.system_jobs.check_permission", return_value=False):
        response = client.get("/admin/cxp-reconciliation")
    assert response.status_code == 403
