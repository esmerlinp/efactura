"""Pruebas del guard de acceso web del Contrato de Producción (entrega 2)."""

from unittest.mock import patch, DEFAULT

from app.services.production_agreement_guard import ProductionAgreementGuard, GuardResult
from app.services.production_agreement_access_service import AccessDecision


def _setup_production_session(client):
    user_dict = {
        'uid': 'test_owner_uid',
        'ownerUID': 'test_owner_uid',
        'role': 'owner',
        'email': 'admin@test.com',
        'name': 'Admin',
        'status': 'active',
        'default_company_id': 'test_comp_1',
        'permissions': {'canViewAuditLog': True},
    }
    with client.session_transaction() as sess:
        sess.clear()
        sess['user'] = dict(user_dict)
        sess['selected_company_id'] = 'test_comp_1'
        sess['selected_owner_uid'] = 'test_owner_uid'
        sess['company_country'] = 'DO'
        sess['company_plan_id'] = 'plan_test'
        sess['company_plan_version'] = 1
        sess['company_modules'] = {'auditoria': {'enabled': True}}
        sess['is_sandbox_mode'] = False
    return user_dict


_COMPANY_DOC = {
    'id': 'test_comp_1',
    'status': 'Activo',
    'planId': 'plan_test',
    'plan_id': 'plan_test',
    'plan_version': 1,
    'owner_uid': 'test_owner_uid',
    'country': 'DO',
    'configured': True,
    'pos_enabled': False,
    'production_enabled': True,
    'sandbox_enabled': True,
    'sandbox_indefinite': True,
}


def _patch_session_deps():
    user_dict = {
        'uid': 'test_owner_uid', 'ownerUID': 'test_owner_uid', 'role': 'owner',
        'email': 'admin@test.com', 'name': 'Admin', 'status': 'active',
        'default_company_id': 'test_comp_1', 'permissions': {'canViewAuditLog': True},
    }
    return patch.multiple(
        'app.services.db_service.DatabaseService',
        get_user_profile=DEFAULT,
        get_company=DEFAULT,
        get_company_profile=DEFAULT,
        get_membership=DEFAULT,
        get_company_context=DEFAULT,
        get_user_companies=DEFAULT,
        get_branches=DEFAULT,
        get_projects=DEFAULT,
        get_plan=DEFAULT,
    ), user_dict


class TestGuardWebIntegration:
    def _run_blocked_request(self, client, blocked_decision):
        from app.services import production_agreement_access_service as _acc
        _setup_production_session(client)
        patches, user_dict = _patch_session_deps()
        with patch.object(
            _acc.ProductionAgreementAccessService, "evaluate_web_access",
            classmethod(lambda cls, cid, uid, sandbox=False: blocked_decision),
        ):
            with patches as mocks:
                mocks['get_user_profile'].return_value = user_dict
                mocks['get_company'].return_value = _COMPANY_DOC
                mocks['get_company_profile'].return_value = _COMPANY_DOC
                mocks['get_membership'].return_value = {'status': 'active', 'role': 'owner'}
                mocks['get_company_context'].return_value = {
                    'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid',
                    'company_name': 'Test Co', 'role': 'owner',
                    'permissions': {'canViewAuditLog': True},
                }
                mocks['get_user_companies'].return_value = []
                mocks['get_branches'].return_value = []
                mocks['get_projects'].return_value = []
                mocks['get_plan'].return_value = {
                    'id': 'plan_test', 'plan_version': 1,
                    'modules': {'auditoria': {'enabled': True}},
                }
                return client.get('/dashboard')

    def test_html_redirects_to_agreement_when_blocked(self, client):
        blocked = AccessDecision(allowed=False, reason="company_agreement_required",
                                 requires_company_agreement=True, requires_user_acknowledgement=True)
        resp = self._run_blocked_request(client, blocked)
        assert resp.status_code == 302
        assert "/production-agreement" in resp.headers["Location"]

    def test_ajax_returns_403_json_when_blocked(self, client):
        from app.services import production_agreement_access_service as _acc
        _setup_production_session(client)
        patches, user_dict = _patch_session_deps()
        blocked = AccessDecision(allowed=False, reason="company_agreement_required",
                                 requires_company_agreement=True, requires_user_acknowledgement=True)
        with patch.object(
            _acc.ProductionAgreementAccessService, "evaluate_web_access",
            classmethod(lambda cls, cid, uid, sandbox=False: blocked),
        ):
            with patches as mocks:
                mocks['get_user_profile'].return_value = user_dict
                mocks['get_company'].return_value = _COMPANY_DOC
                mocks['get_company_profile'].return_value = _COMPANY_DOC
                mocks['get_membership'].return_value = {'status': 'active', 'role': 'owner'}
                mocks['get_company_context'].return_value = {
                    'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid',
                    'company_name': 'Test Co', 'role': 'owner',
                    'permissions': {'canViewAuditLog': True},
                }
                mocks['get_user_companies'].return_value = []
                mocks['get_branches'].return_value = []
                mocks['get_projects'].return_value = []
                mocks['get_plan'].return_value = {
                    'id': 'plan_test', 'plan_version': 1,
                    'modules': {'auditoria': {'enabled': True}},
                }
                resp = client.get('/dashboard', headers={"X-Requested-With": "XMLHttpRequest"})
                assert resp.status_code == 403
                data = resp.get_json()
                assert data["code"] == "PRODUCTION_AGREEMENT_REQUIRED"

    def test_logout_is_not_blocked(self, client):
        _setup_production_session(client)
        patches, user_dict = _patch_session_deps()
        with patches as mocks:
            mocks['get_user_profile'].return_value = user_dict
            mocks['get_company'].return_value = _COMPANY_DOC
            mocks['get_company_profile'].return_value = _COMPANY_DOC
            mocks['get_membership'].return_value = {'status': 'active', 'role': 'owner'}
            mocks['get_company_context'].return_value = {
                'company_id': 'test_comp_1', 'owner_uid': 'test_owner_uid',
                'company_name': 'Test Co', 'role': 'owner',
                'permissions': {'canViewAuditLog': True},
            }
            mocks['get_user_companies'].return_value = []
            mocks['get_branches'].return_value = []
            mocks['get_projects'].return_value = []
            mocks['get_plan'].return_value = {
                'id': 'plan_test', 'plan_version': 1,
                'modules': {'auditoria': {'enabled': True}},
            }
            resp = client.get('/logout')
            assert "/production-agreement" not in resp.headers.get("Location", "")


class TestGuardExemptions:
    def test_sandbox_also_enforces_agreement(self, monkeypatch):
        from app.services import production_agreement_access_service as _acc
        monkeypatch.setattr(
            _acc.ProductionAgreementAccessService, "evaluate_web_access",
            classmethod(lambda cls, cid, uid, sandbox=False: AccessDecision(
                allowed=False, reason="company_agreement_required",
                requires_company_agreement=True, requires_user_acknowledgement=True,
            )),
        )
        result = ProductionAgreementGuard.evaluate("web_dashboard.dashboard", "c1", "u1", is_sandbox=True)
        assert result.blocked is True
        assert result.reason == "company_agreement_required"

    def test_exempt_endpoints(self):
        for endpoint in (
            "web_production_agreement.view",
            "web_production_agreement.accept_company",
            "web_production_agreement.acknowledge",
            "web_invoices.onboarding_wizard",
            "web_invoices.onboarding_skip",
            "web_auth.logout",
            "web_auth.select_company",
            "static",
        ):
            result = ProductionAgreementGuard.evaluate(endpoint, "c1", "u1", is_sandbox=False)
            assert result.blocked is False, endpoint

    def test_is_exempt_none(self):
        assert ProductionAgreementGuard.is_exempt(None) is True


class TestGuardBlocking:
    def test_blocks_when_company_agreement_required(self, monkeypatch):
        from app.services import production_agreement_access_service as _acc
        monkeypatch.setattr(
            _acc.ProductionAgreementAccessService, "evaluate_web_access",
            classmethod(lambda cls, cid, uid, sandbox=False: AccessDecision(
                allowed=False, reason="company_agreement_required",
                requires_company_agreement=True, requires_user_acknowledgement=True,
            )),
        )
        result = ProductionAgreementGuard.evaluate("web_dashboard.dashboard", "c1", "u1", is_sandbox=False)
        assert result.blocked is True
        assert result.reason == "company_agreement_required"

    def test_allows_when_access_ok(self, monkeypatch):
        from app.services import production_agreement_access_service as _acc
        monkeypatch.setattr(
            _acc.ProductionAgreementAccessService, "evaluate_web_access",
            classmethod(lambda cls, cid, uid, sandbox=False: AccessDecision(allowed=True, reason="ok")),
        )
        result = ProductionAgreementGuard.evaluate("web_dashboard.dashboard", "c1", "u1", is_sandbox=False)
        assert result.blocked is False

    def test_missing_context_not_blocked(self):
        result = ProductionAgreementGuard.evaluate("web_dashboard.dashboard", "", "", is_sandbox=False)
        assert result.blocked is False
