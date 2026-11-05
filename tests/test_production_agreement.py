"""Pruebas del sistema de Contrato de Producción (entrega 1: flujo web)."""

import pytest

from app.services.production_agreement_service import (
    sanitize_html,
    canonicalize,
    compute_content_hash,
    ProductionAgreementService,
    _to_iso,
)
from app.services.production_agreement_acceptance_service import (
    ProductionAgreementAcceptanceService,
    _ack_id,
)
from app.services.production_agreement_access_service import (
    ProductionAgreementAccessService,
    AccessDecision,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sanitización y hash (funciones puras)
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitization:
    def test_strips_script_tag(self):
        assert sanitize_html("<p>Hola</p><script>alert(1)</script>") == "<p>Hola</p>"

    def test_strips_event_handler_attributes(self):
        out = sanitize_html('<div onclick="alert(1)">x</div>')
        assert "onclick" not in out
        assert "x" in out

    def test_strips_javascript_url(self):
        out = sanitize_html('<a href="javascript:alert(1)">click</a>')
        assert "javascript:" not in out
        assert "click" in out

    def test_keeps_safe_link(self):
        out = sanitize_html('<a href="https://vykcore.com">sitio</a>')
        assert 'href="https://vykcore.com"' in out

    def test_keeps_allowed_tags(self):
        out = sanitize_html("<p><strong>negrita</strong> y <em>cursiva</em></p>")
        assert "<strong>negrita</strong>" in out
        assert "<em>cursiva</em>" in out

    def test_drops_unknown_tags_keeps_text(self):
        out = sanitize_html("<foo>contenido</foo>")
        assert "<foo" not in out
        assert "contenido" in out

    def test_strips_comments(self):
        out = sanitize_html("<p>a</p><!-- secret --><p>b</p>")
        assert "secret" not in out


class TestCanonicalization:
    def test_normalizes_crlf(self):
        assert canonicalize("a\r\nb\r\nc") == "a\nb\nc"

    def test_strips_outer_whitespace(self):
        assert canonicalize("   <p>x</p>  ") == "<p>x</p>"


class TestTimestampNormalization:
    def test_none_returns_empty(self):
        assert _to_iso(None) == ""

    def test_string_passthrough(self):
        assert _to_iso("2026-11-05T10:00:00") == "2026-11-05T10:00:00"

    def test_datetime_with_nanoseconds(self):
        from google.api_core.datetime_helpers import DatetimeWithNanoseconds
        from datetime import datetime, timezone
        value = DatetimeWithNanoseconds.from_rfc3339("2026-11-05T10:00:00.123456789Z")
        result = _to_iso(value)
        assert isinstance(result, str)
        assert result.startswith("2026-11-05")

    def test_object_with_to_datetime(self):
        class FakeTs:
            def to_datetime(self):
                from datetime import datetime, timezone
                return datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)
        assert _to_iso(FakeTs()).startswith("2026-11-05")


class TestHash:
    def test_deterministic(self):
        assert compute_content_hash("hola") == compute_content_hash("hola")

    def test_different_content_different_hash(self):
        assert compute_content_hash("a") != compute_content_hash("b")

    def test_canonical_equivalent_inputs(self):
        assert compute_content_hash("<p>x</p>\n") == compute_content_hash(" <p>x</p> ")


# ─────────────────────────────────────────────────────────────────────────────
# Decisión de acceso (con Firestore mockeado)
# ─────────────────────────────────────────────────────────────────────────────

def _fake_active_version():
    return {"id": "v1", "version": 1, "contentHash": "hash1", "content": "<p>x</p>"}


class TestAccessDecisions:
    def _setup(self, monkeypatch, *, company_active=True, membership=True,
               is_owner=False, has_active=True, company_accept=True, user_ack=True):
        monkeypatch.setattr(ProductionAgreementAccessService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_company_active",
                            classmethod(lambda cls, cid: company_active))
        monkeypatch.setattr(ProductionAgreementAccessService, "_active_membership",
                            classmethod(lambda cls, cid, uid: membership))
        monkeypatch.setattr(ProductionAgreementAccessService, "_is_owner",
                            classmethod(lambda cls, cid, uid: is_owner))

        from app.services import production_agreement_service as _svc
        if has_active:
            monkeypatch.setattr(_svc.ProductionAgreementService, "get_active_version",
                                classmethod(lambda cls: _fake_active_version()))
        else:
            monkeypatch.setattr(_svc.ProductionAgreementService, "get_active_version",
                                classmethod(lambda cls: None))

        from app.services import production_agreement_acceptance_service as _acc
        company_acc = {"contentHash": "hash1"} if company_accept else None
        user_acc = {"contentHash": "hash1"} if user_ack else None
        monkeypatch.setattr(_acc.ProductionAgreementAcceptanceService, "get_company_acceptance",
                            classmethod(lambda cls, cid, vid, sandbox=False: company_acc))
        monkeypatch.setattr(_acc.ProductionAgreementAcceptanceService, "get_user_acknowledgement",
                            classmethod(lambda cls, cid, uid, vid, sandbox=False: user_acc))

    def test_allowed_when_both_satisfied(self, monkeypatch):
        self._setup(monkeypatch, company_accept=True, user_ack=True)
        decision = ProductionAgreementAccessService.evaluate_web_access("c1", "u1")
        assert decision.allowed is True

    def test_company_agreement_required(self, monkeypatch):
        self._setup(monkeypatch, company_accept=False, user_ack=False)
        decision = ProductionAgreementAccessService.evaluate_web_access("c1", "u1")
        assert decision.allowed is False
        assert decision.reason == "company_agreement_required"
        assert decision.requires_company_agreement is True

    def test_user_acknowledgement_required(self, monkeypatch):
        self._setup(monkeypatch, company_accept=True, user_ack=False)
        decision = ProductionAgreementAccessService.evaluate_web_access("c1", "u1")
        assert decision.allowed is False
        assert decision.reason == "user_acknowledgement_required"

    def test_no_membership_blocks(self, monkeypatch):
        self._setup(monkeypatch, membership=False)
        decision = ProductionAgreementAccessService.evaluate_web_access("c1", "u1")
        assert decision.allowed is False
        assert decision.reason == "no_active_membership"

    def test_company_inactive_blocks(self, monkeypatch):
        self._setup(monkeypatch, company_active=False)
        decision = ProductionAgreementAccessService.evaluate_web_access("c1", "u1")
        assert decision.allowed is False
        assert decision.reason == "company_inactive"

    def test_no_active_version_allows(self, monkeypatch):
        self._setup(monkeypatch, has_active=False)
        decision = ProductionAgreementAccessService.evaluate_web_access("c1", "u1")
        assert decision.allowed is True
        assert decision.reason == "no_active_version"

    def test_hash_mismatch_blocks(self, monkeypatch):
        self._setup(monkeypatch, company_accept=False, user_ack=False)
        from app.services import production_agreement_acceptance_service as _acc
        monkeypatch.setattr(_acc.ProductionAgreementAcceptanceService, "get_company_acceptance",
                            classmethod(lambda cls, cid, vid, sandbox=False: {"contentHash": "diferente"}))
        decision = ProductionAgreementAccessService.evaluate_web_access("c1", "u1")
        assert decision.allowed is False
        assert decision.requires_company_agreement is True


class TestContextPolicies:
    def test_api_requires_contract_access(self):
        # Sin identidad contractual verificable en la credencial, siempre bloqueado.
        assert ProductionAgreementAccessService.requires_api_contract_access("c1", {}) is True

    def test_job_requires_company_agreement(self, monkeypatch):
        monkeypatch.setattr(ProductionAgreementAccessService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_company_active", classmethod(lambda cls, cid: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "requires_company_agreement",
                            classmethod(lambda cls, cid: True))
        assert ProductionAgreementAccessService.requires_job_contract_access("c1") is True


# ─────────────────────────────────────────────────────────────────────────────
# Aceptación empresarial (autorización)
# ─────────────────────────────────────────────────────────────────────────────

class TestAcceptanceAuthorization:
    def test_ack_id_deterministic(self):
        assert _ack_id("u1", "v1") == _ack_id("u1", "v1")
        assert _ack_id("u1", "v1") != _ack_id("u2", "v1")

    def test_accept_company_rejects_non_owner(self, monkeypatch):
        monkeypatch.setattr(ProductionAgreementAcceptanceService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAcceptanceService, "_is_owner",
                            classmethod(lambda cls, cid, uid: False))
        result = ProductionAgreementAcceptanceService.accept_company("c1", "u1", "N", "e@e.com")
        assert result["ok"] is False
        assert result["reason"] == "not_owner"

    def test_accept_company_requires_membership(self, monkeypatch):
        monkeypatch.setattr(ProductionAgreementAcceptanceService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAcceptanceService, "_is_owner",
                            classmethod(lambda cls, cid, uid: True))
        monkeypatch.setattr(ProductionAgreementAcceptanceService, "_active_membership",
                            classmethod(lambda cls, cid, uid: False))
        result = ProductionAgreementAcceptanceService.accept_company("c1", "u1", "N", "e@e.com")
        assert result["ok"] is False
        assert result["reason"] == "no_active_membership"


# ─────────────────────────────────────────────────────────────────────────────
# Separación Sandbox / Producción
# ─────────────────────────────────────────────────────────────────────────────

class TestSandboxSeparation:
    def test_collection_names_differ_by_environment(self):
        from app.services.production_agreement_acceptance_service import (
            _acceptances_coll_name, _acknowledgements_coll_name,
        )
        assert _acceptances_coll_name(False) == "production_agreement_acceptances"
        assert _acceptances_coll_name(True) == "sandbox_production_agreement_acceptances"
        assert _acknowledgements_coll_name(False) == "user_agreement_acknowledgements"
        assert _acknowledgements_coll_name(True) == "sandbox_user_agreement_acknowledgements"

    def test_evaluate_forwards_sandbox_flag_to_evidence(self, monkeypatch):
        from app.services import production_agreement_service as _svc
        from app.services import production_agreement_acceptance_service as _acc

        monkeypatch.setattr(ProductionAgreementAccessService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_company_active",
                            classmethod(lambda cls, cid: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_active_membership",
                            classmethod(lambda cls, cid, uid: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_is_owner",
                            classmethod(lambda cls, cid, uid: True))
        monkeypatch.setattr(_svc.ProductionAgreementService, "get_active_version",
                            classmethod(lambda cls: {"id": "v1", "version": 1,
                                                     "contentHash": "hash1", "content": "x"}))

        seen = {}

        def fake_company(cls, cid, vid, sandbox=False):
            seen["company_sandbox"] = sandbox
            return {"contentHash": "hash1"}

        def fake_user(cls, cid, uid, vid, sandbox=False):
            seen["user_sandbox"] = sandbox
            return {"contentHash": "hash1"}

        monkeypatch.setattr(_acc.ProductionAgreementAcceptanceService, "get_company_acceptance",
                            classmethod(fake_company))
        monkeypatch.setattr(_acc.ProductionAgreementAcceptanceService, "get_user_acknowledgement",
                            classmethod(fake_user))

        ProductionAgreementAccessService.evaluate_web_access("c1", "u1", sandbox=True)
        assert seen["company_sandbox"] is True
        assert seen["user_sandbox"] is True
