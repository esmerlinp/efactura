from datetime import date

import pytest

from app.models.recurring_contract import (
    ContractTermsVersion,
    RecurringContract,
    RecurringContractLine,
    RecurringContractStatus,
)
from app.services.db_service import DatabaseService
from app.web import operations


def contract(status=RecurringContractStatus.ACTIVE):
    value = RecurringContract(
        owner_uid="owner", company_id="company", client_id="client",
        contract_number="CON-001", start_date=date(2026, 1, 1),
        billing_anchor_date=date(2026, 1, 1), billing_day=1,
        status=status, ecf_type="E31",
        lines=(RecurringContractLine(name="Service", unit_price=100),),
    )
    return value.add_terms_version(ContractTermsVersion(
        version=1, effective_from=date(2026, 1, 1), ecf_type="E31", lines=value.lines,
    ))


def test_v2_status_labels_match_detail_template():
    assert operations._v2_status_label(RecurringContractStatus.ACTIVE) == "Activo"
    assert operations._v2_status_label(RecurringContractStatus.SUSPENDED) == "Suspendido"
    assert operations._v2_status_label(RecurringContractStatus.CANCELLED) == "Cancelado"
    assert operations._v2_status_label(RecurringContractStatus.DRAFT) == "Borrador"
    assert operations._v2_status_label(RecurringContractStatus.PENDING_APPROVAL) == "Pendiente de Aprobación"


def test_v2_status_from_spanish_labels():
    assert operations._v2_status_from_label("Activo") == RecurringContractStatus.ACTIVE
    assert operations._v2_status_from_label(" suspendido ") == RecurringContractStatus.SUSPENDED
    assert operations._v2_status_from_label("Cancelado") == RecurringContractStatus.CANCELLED
    assert operations._v2_status_from_label("Pendiente de Aprobación") == RecurringContractStatus.PENDING_APPROVAL
    assert operations._v2_status_from_label("Inactivo") == RecurringContractStatus.SUSPENDED
    assert operations._v2_status_from_label("desconocido") is None


def test_v2_toggle_target_respects_state_machine():
    assert operations._v2_toggle_target(RecurringContractStatus.ACTIVE) == RecurringContractStatus.SUSPENDED
    assert operations._v2_toggle_target(RecurringContractStatus.SUSPENDED) == RecurringContractStatus.ACTIVE
    assert operations._v2_toggle_target(RecurringContractStatus.DRAFT) == RecurringContractStatus.ACTIVE


def test_v2_status_save_preserves_domain_and_extra_fields(monkeypatch):
    value = contract()
    full = value.model_dump(mode="json")
    full.update({
        "schemaVersion": 2,
        "legacySource": {"id": "legacy-1"},
        "cancelRequest": True,
        "signatureInfo": {"signed": True},
    })
    saved = {}

    monkeypatch.setattr(
        DatabaseService, "get_contract",
        classmethod(lambda cls, *args, **kwargs: dict(full)),
    )

    def fake_save(cls, owner_uid, contract_id, payload, **kwargs):
        saved.update(payload)
        return payload

    monkeypatch.setattr(DatabaseService, "save_contract", classmethod(fake_save))

    updated = operations._save_v2_contract_status(
        "owner", value.id, "company", True, value, RecurringContractStatus.SUSPENDED
    )

    assert updated.status == RecurringContractStatus.SUSPENDED
    assert saved["status"] == "suspended"
    assert saved["schemaVersion"] == 2
    assert saved["legacySource"] == {"id": "legacy-1"}
    assert saved["cancelRequest"] is True
    assert saved["signatureInfo"] == {"signed": True}
    assert saved["lines"] == full["lines"]
    assert saved["terms_versions"] == full["terms_versions"]


def test_v2_status_save_rejects_invalid_transition(monkeypatch):
    value = contract(RecurringContractStatus.CANCELLED)
    monkeypatch.setattr(
        DatabaseService, "get_contract",
        classmethod(lambda cls, *args, **kwargs: value.model_dump(mode="json")),
    )

    with pytest.raises(ValueError):
        operations._save_v2_contract_status(
            "owner", value.id, "company", True, value, RecurringContractStatus.ACTIVE
        )


def test_contract_fiscal_code_is_required_on_creation():
    with pytest.raises(ValueError, match="tipo de e-CF"):
        operations._require_contract_fiscal_code("")
    with pytest.raises(ValueError, match="tipo de e-CF"):
        operations._require_contract_fiscal_code(None)


def test_contract_fiscal_code_normalizes_eligible_types():
    assert operations._require_contract_fiscal_code(" E31 ") == "E31"
    assert operations._require_contract_fiscal_code("E32") == "E32"


def test_contract_fiscal_code_rejects_non_eligible_types():
    with pytest.raises(ValueError):
        operations._require_contract_fiscal_code("E43")


def test_detail_templates_expose_fiscal_review_resolution():
    from pathlib import Path

    detail = Path("templates/contracts/detail.html").read_text(encoding="utf-8")
    admin_detail = Path("templates/operations/recurring_contract_detail.html").read_text(encoding="utf-8")
    for template in (detail, admin_detail):
        assert "recurring_contract_fiscal_review" in template
    assert "needsFiscalReview" in detail
    assert "disabled" in detail


def test_v2_next_billing_date_is_forward_looking():
    from datetime import date

    value = contract()
    next_date = date.fromisoformat(operations._v2_next_billing_date(value))
    assert next_date > date.today()
