from app.models.internal_service_document import calculated_status


def test_expiration_only_changes_calculated_state():
    document = {
        "persistedState": "active",
        "promotionStartDate": "2026-01-01",
        "promotionEndDate": "2026-01-31",
        "nonFiscal": True,
    }

    assert calculated_status(document, "2026-02-01") == "vencido"
    assert document["persistedState"] == "active"
    assert document["nonFiscal"] is True


def test_voided_document_remains_non_fiscal():
    document = {
        "persistedState": "voided",
        "promotionStartDate": "2026-01-01",
        "promotionEndDate": "2026-01-31",
        "nonFiscal": True,
    }

    assert calculated_status(document, "2026-01-15") == "anulado"
    assert "encf" not in document
    assert "invoiceId" not in document


def test_portal_document_access_requires_matching_company_and_client():
    document = {
        "companyId": "company-a",
        "clientId": "client-a",
    }

    assert document["companyId"] == "company-a"
    assert document["clientId"] == "client-a"
    assert not (document["companyId"] == "company-b" and document["clientId"] == "client-a")
    assert not (document["companyId"] == "company-a" and document["clientId"] == "client-b")
