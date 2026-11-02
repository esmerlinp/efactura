from decimal import Decimal

import pytest

from app.models.internal_service_document import calculated_status, calculate_line
from app.services.internal_service_document_service import InternalServiceDocumentService


def test_calculate_line_uses_decimal_and_full_discount():
    line = calculate_line({"id": "item-1", "code": "SVC", "name": "Servicio", "price": 2000.00}, "1", "100")

    assert line.subtotal == Decimal("2000.00")
    assert line.discount == Decimal("2000.00")
    assert line.payable == Decimal("0.00")
    assert line.to_dict()["subtotalCents"] == 200000


def test_calculated_state_does_not_change_persisted_state():
    document = {
        "persistedState": "active",
        "promotionStartDate": "2026-01-01",
        "promotionEndDate": "2026-01-31",
    }

    assert calculated_status(document, "2026-02-01") == "vencido"
    assert document["persistedState"] == "active"


def test_invalid_promotion_type_is_rejected():
    with pytest.raises(ValueError):
        InternalServiceDocumentService.create(
            owner_uid="owner",
            company_id="company",
            sandbox=True,
            client_id="client",
            issue_date="2026-01-01",
            reason="test",
            promotion_type="invalid",
            promotion_start="2026-01-01",
            promotion_end="2026-01-31",
            billing_start="2026-02-01",
            lines=[],
            notes="",
            idempotency_key="key",
            actor={},
        )
