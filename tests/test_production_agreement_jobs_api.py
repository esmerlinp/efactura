"""Pruebas de política de jobs y bloqueo de API de producción (entrega 5)."""

from app.services.production_agreement_access_service import ProductionAgreementAccessService


class TestJobContractAccess:
    def test_job_gate_resolves_company_and_checks(self, monkeypatch):
        import app.services.production_agreement_access_service as acc
        import app.services.db_service as db
        monkeypatch.setattr(db, "_resolve_company_id", lambda ouid: "c1")
        monkeypatch.setattr(
            acc.ProductionAgreementAccessService, "requires_job_contract_access",
            classmethod(lambda cls, cid: True),
        )
        assert acc.ProductionAgreementAccessService.requires_job_contract_access_for_owner("o1") is True

    def test_job_gate_no_company_fails_closed(self, monkeypatch):
        import app.services.production_agreement_access_service as acc
        import app.services.db_service as db
        monkeypatch.setattr(db, "_resolve_company_id", lambda ouid: None)
        assert acc.ProductionAgreementAccessService.requires_job_contract_access_for_owner("o1") is True

    def test_job_gate_empty_owner_fails_closed(self, monkeypatch):
        import app.services.production_agreement_access_service as acc
        assert acc.ProductionAgreementAccessService.requires_job_contract_access_for_owner("") is True

    def test_job_requires_company_agreement_not_user(self, monkeypatch):
        # Los jobs no exigen reconocimiento individual: solo aceptación empresarial.
        monkeypatch.setattr(ProductionAgreementAccessService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_company_active", classmethod(lambda cls, cid: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "requires_company_agreement",
                            classmethod(lambda cls, cid: False))
        assert ProductionAgreementAccessService.requires_job_contract_access("c1") is False


class TestApiProductionBlock:
    def test_production_api_is_blocked(self, app):
        from app.api.auth import _production_api_blocked
        with app.test_request_context():
            from flask import g
            g.sandbox_mode = False
            resp = _production_api_blocked()
        assert resp is not None
        assert resp[1] == 403
        data = resp[0].get_json()
        assert data["code"] == "PRODUCTION_AGREEMENT_REQUIRED"

    def test_sandbox_api_is_not_blocked(self, app):
        from app.api.auth import _production_api_blocked
        with app.test_request_context():
            from flask import g
            g.sandbox_mode = True
            assert _production_api_blocked() is None

    def test_default_sandbox_is_not_blocked(self, app):
        from app.api.auth import _production_api_blocked
        with app.test_request_context():
            from flask import g
            g.pop("sandbox_mode", None)
            assert _production_api_blocked() is None
