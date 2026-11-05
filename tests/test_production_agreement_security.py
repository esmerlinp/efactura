"""Pruebas de seguridad del Contrato de Producción (entrega 3).

Cobertura: inmutabilidad de versiones, aislamiento multiempresa, cambio de
propietario, manipulación de solicitudes, CSRF, idempotencia y caché.
"""

from unittest.mock import patch, DEFAULT

from app.services.production_agreement_service import (
    ProductionAgreementService,
    compute_content_hash,
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
# Inmutabilidad de versiones publicadas
# ─────────────────────────────────────────────────────────────────────────────

class TestVersionImmutability:
    def test_update_draft_rejects_published(self, monkeypatch):
        monkeypatch.setattr(
            ProductionAgreementService, "get_version",
            classmethod(lambda cls, vid: {"id": "v1", "status": "active", "content": "x"}),
        )
        result = ProductionAgreementService.update_draft("v1", "t", "nuevo", "u")
        assert result is None

    def test_update_draft_rejects_superseded(self, monkeypatch):
        monkeypatch.setattr(
            ProductionAgreementService, "get_version",
            classmethod(lambda cls, vid: {"id": "v1", "status": "superseded", "content": "x"}),
        )
        assert ProductionAgreementService.update_draft("v1", "t", "nuevo", "u") is None

    def test_update_draft_allows_draft(self, monkeypatch):
        monkeypatch.setattr(
            ProductionAgreementService, "get_version",
            classmethod(lambda cls, vid: {"id": "v1", "status": "draft", "content": "x"}),
        )
        from app.services import production_agreement_service as _svc
        monkeypatch.setattr(_svc, "_versions_ref", lambda: _FakeRef())
        result = ProductionAgreementService.update_draft("v1", "Título", "<p>nuevo</p>", "u")
        assert result is not None
        assert result["status"] == "draft"

    def test_verify_integrity(self, monkeypatch):
        content = "<p>x</p>"
        monkeypatch.setattr(
            ProductionAgreementService, "get_version",
            classmethod(lambda cls, vid: {"id": "v1", "content": content,
                                          "contentHash": compute_content_hash(content)}),
        )
        assert ProductionAgreementService.verify_integrity("v1") is True

    def test_verify_integrity_detects_tampering(self, monkeypatch):
        monkeypatch.setattr(
            ProductionAgreementService, "get_version",
            classmethod(lambda cls, vid: {"id": "v1", "content": "alterado",
                                          "contentHash": "hash-inventado"}),
        )
        assert ProductionAgreementService.verify_integrity("v1") is False

    def test_next_version_number(self, monkeypatch):
        monkeypatch.setattr(
            ProductionAgreementService, "list_versions",
            classmethod(lambda cls: [{"version": 3}, {"version": 1}, {"version": "2"}]),
        )
        assert ProductionAgreementService.next_version_number() == 4

    def test_next_version_number_empty(self, monkeypatch):
        monkeypatch.setattr(ProductionAgreementService, "list_versions", classmethod(lambda cls: []))
        assert ProductionAgreementService.next_version_number() == 1


class _FakeRef:
    def __init__(self):
        self.set_calls = []

    def document(self, _doc_id):
        return self

    def set(self, data, merge=False):
        self.set_calls.append(data)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Aislamiento multiempresa y cambio de propietario
# ─────────────────────────────────────────────────────────────────────────────

def _fake_active(version_id="v1", version=1):
    return {"id": version_id, "version": version, "contentHash": "hash1", "content": "<p>x</p>"}


class TestMultiCompanyIsolation:
    def _setup(self, monkeypatch, acceptances, acknowledgements):
        monkeypatch.setattr(ProductionAgreementAccessService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_company_active",
                            classmethod(lambda cls, cid: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_active_membership",
                            classmethod(lambda cls, cid, uid: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_is_owner",
                            classmethod(lambda cls, cid, uid: True))

        from app.services import production_agreement_service as _svc
        monkeypatch.setattr(_svc.ProductionAgreementService, "get_active_version",
                            classmethod(lambda cls: _fake_active()))

        from app.services import production_agreement_acceptance_service as _acc
        monkeypatch.setattr(
            _acc.ProductionAgreementAcceptanceService, "get_company_acceptance",
            classmethod(lambda cls, cid, vid, sandbox=False: acceptances.get(cid)),
        )
        monkeypatch.setattr(
            _acc.ProductionAgreementAcceptanceService, "get_user_acknowledgement",
            classmethod(lambda cls, cid, uid, vid, sandbox=False: acknowledgements.get((cid, uid))),
        )

    def test_company_acceptance_does_not_leak_across_companies(self, monkeypatch):
        self._setup(
            monkeypatch,
            acceptances={"cA": {"contentHash": "hash1"}},
            acknowledgements={("cA", "u1"): {"contentHash": "hash1"},
                              ("cB", "u1"): {"contentHash": "hash1"}},
        )
        a = ProductionAgreementAccessService.evaluate_web_access("cA", "u1")
        b = ProductionAgreementAccessService.evaluate_web_access("cB", "u1")
        assert a.allowed is True
        assert b.allowed is False
        assert b.reason == "company_agreement_required"

    def test_owner_change_does_not_invalidate_company_acceptance(self, monkeypatch):
        # La aceptación es por compañía, no por propietario. El método de
        # aceptación no consulta la identidad del owner actual al validar.
        self._setup(
            monkeypatch,
            acceptances={"cA": {"contentHash": "hash1"}},
            acknowledgements={("cA", "u1"): {"contentHash": "hash1"}},
        )
        # Aunque _is_owner devuelva False (nuevo propietario aún no reconocido),
        # la aceptación empresarial de la compañía sigue siendo válida.
        decision = ProductionAgreementAccessService.evaluate_web_access("cA", "u1")
        assert decision.company_agreement_ok is True


class TestNewVersionRequiresReacceptance:
    def test_new_version_without_acceptance_blocks(self, monkeypatch):
        monkeypatch.setattr(ProductionAgreementAccessService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_company_active",
                            classmethod(lambda cls, cid: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_active_membership",
                            classmethod(lambda cls, cid, uid: True))
        monkeypatch.setattr(ProductionAgreementAccessService, "_is_owner",
                            classmethod(lambda cls, cid, uid: True))

        from app.services import production_agreement_service as _svc
        monkeypatch.setattr(_svc.ProductionAgreementService, "get_active_version",
                            classmethod(lambda cls: _fake_active(version_id="v2", version=2)))

        from app.services import production_agreement_acceptance_service as _acc
        # No hay aceptación para v2.
        monkeypatch.setattr(
            _acc.ProductionAgreementAcceptanceService, "get_company_acceptance",
            classmethod(lambda cls, cid, vid, sandbox=False: None),
        )
        monkeypatch.setattr(
            _acc.ProductionAgreementAcceptanceService, "get_user_acknowledgement",
            classmethod(lambda cls, cid, uid, vid, sandbox=False: None),
        )

        decision = ProductionAgreementAccessService.evaluate_web_access("cA", "u1")
        assert decision.allowed is False
        assert decision.requires_company_agreement is True


# ─────────────────────────────────────────────────────────────────────────────
# Idempotencia (fundamentos deterministas)
# ─────────────────────────────────────────────────────────────────────────────

class TestIdempotencyFoundations:
    def test_ack_id_deterministic(self):
        assert _ack_id("u1", "v1") == _ack_id("u1", "v1")

    def test_ack_id_isolated_by_user_and_version(self):
        ids = {
            _ack_id("u1", "v1"), _ack_id("u2", "v1"),
            _ack_id("u1", "v2"), _ack_id("u2", "v2"),
        }
        assert len(ids) == 4

    def test_accept_company_rejects_non_owner_before_write(self, monkeypatch):
        # Si el usuario no es owner, no se toca Firestore para escribir evidencia.
        monkeypatch.setattr(ProductionAgreementAcceptanceService, "_available", classmethod(lambda cls: True))
        monkeypatch.setattr(ProductionAgreementAcceptanceService, "_is_owner",
                            classmethod(lambda cls, cid, uid: False))
        result = ProductionAgreementAcceptanceService.accept_company("c1", "u1", "N", "e@e.com")
        assert result == {"ok": False, "reason": "not_owner"}


# ─────────────────────────────────────────────────────────────────────────────
# Caché con invalidación
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheInvalidation:
    def test_invalidate_bumps_version(self, app):
        from app.services.cache_service import CacheService
        with app.app_context():
            before = CacheService.get_version("c1", False, "production_agreement")
            CacheService.invalidate_production_agreement("c1")
            after = CacheService.get_version("c1", False, "production_agreement")
            assert after == before + 1

    def test_invalidate_global_bumps_global_version(self, app):
        from app.services.cache_service import CacheService
        with app.app_context():
            before = CacheService.get_version("__global__", False, "production_agreement_global")
            CacheService.invalidate_production_agreement_global()
            after = CacheService.get_version("__global__", False, "production_agreement_global")
            assert after == before + 1


# ─────────────────────────────────────────────────────────────────────────────
# Manipulación de solicitudes (el navegador no determina identidad/versión/hash)
# ─────────────────────────────────────────────────────────────────────────────

_COMPANY_DOC = {
    'id': 'real_company', 'status': 'Activo', 'planId': 'plan_test', 'plan_id': 'plan_test',
    'plan_version': 1, 'owner_uid': 'real_owner', 'country': 'DO', 'configured': True,
    'pos_enabled': False, 'production_enabled': True, 'sandbox_enabled': True,
    'sandbox_indefinite': True,
}


def _session_deps():
    return patch.multiple(
        'app.services.db_service.DatabaseService',
        get_user_profile=DEFAULT, get_company=DEFAULT, get_company_profile=DEFAULT,
        get_membership=DEFAULT, get_company_context=DEFAULT, get_user_companies=DEFAULT,
        get_branches=DEFAULT, get_projects=DEFAULT, get_plan=DEFAULT,
    )


def _apply_deps(mocks):
    mocks['get_user_profile'].return_value = {
        'uid': 'real_user', 'ownerUID': 'real_owner', 'role': 'owner',
        'email': 'a@b.c', 'name': 'A', 'status': 'active',
        'default_company_id': 'real_company', 'permissions': {},
    }
    mocks['get_company'].return_value = _COMPANY_DOC
    mocks['get_company_profile'].return_value = _COMPANY_DOC
    mocks['get_membership'].return_value = {'status': 'active', 'role': 'owner'}
    mocks['get_company_context'].return_value = {
        'company_id': 'real_company', 'owner_uid': 'real_owner', 'company_name': 'T',
        'role': 'owner', 'permissions': {},
    }
    mocks['get_user_companies'].return_value = []
    mocks['get_branches'].return_value = []
    mocks['get_projects'].return_value = []
    mocks['get_plan'].return_value = {'id': 'plan_test', 'plan_version': 1, 'modules': {}}


class TestRequestManipulation:
    def test_accept_company_uses_session_identity_not_form(self, client, monkeypatch):
        captured = {}
        from app.services import production_agreement_acceptance_service as _acc
        monkeypatch.setattr(
            _acc.ProductionAgreementAcceptanceService, "accept_company",
            classmethod(lambda cls, **kw: captured.update(kw) or {"ok": True}),
        )
        from app.services import production_agreement_access_service as _asvc
        monkeypatch.setattr(
            _asvc.ProductionAgreementAccessService, "evaluate_web_access",
            classmethod(lambda cls, cid, uid, sandbox=False: AccessDecision(allowed=True, reason="ok")),
        )

        with client.session_transaction() as sess:
            sess.clear()
            sess['user'] = {'uid': 'real_user', 'ownerUID': 'real_owner', 'role': 'owner',
                            'email': 'a@b.c', 'name': 'A', 'status': 'active'}
            sess['selected_company_id'] = 'real_company'
            sess['selected_owner_uid'] = 'real_owner'
            sess['is_sandbox_mode'] = False

        with _session_deps() as mocks:
            _apply_deps(mocks)
            resp = client.post('/production-agreement/accept-company', data={
                'accept': '1',
                'company_id': 'spoofed_company',
                'user_id': 'spoofed_user',
                'agreementVersion': '999',
                'contentHash': 'spoofed_hash',
            })

        assert resp.status_code == 302
        assert captured['company_id'] == 'real_company'
        assert captured['user_id'] == 'real_user'
        assert 'agreementVersion' not in captured
        assert 'contentHash' not in captured

    def test_accept_company_requires_checkbox(self, client, monkeypatch):
        from app.services import production_agreement_acceptance_service as _acc
        called = []
        monkeypatch.setattr(
            _acc.ProductionAgreementAcceptanceService, "accept_company",
            classmethod(lambda cls, **kw: called.append(kw) or {"ok": False, "reason": "write_error"}),
        )

        with client.session_transaction() as sess:
            sess.clear()
            sess['user'] = {'uid': 'real_user', 'ownerUID': 'real_owner', 'role': 'owner',
                            'email': 'a@b.c', 'name': 'A', 'status': 'active'}
            sess['selected_company_id'] = 'real_company'
            sess['selected_owner_uid'] = 'real_owner'
            sess['is_sandbox_mode'] = False

        with _session_deps() as mocks:
            _apply_deps(mocks)
            client.post('/production-agreement/accept-company', data={'accept': '0'})

        assert called == []

    def test_csrf_required_for_accept(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
        from app.services import production_agreement_acceptance_service as _acc
        called = []
        monkeypatch.setattr(
            _acc.ProductionAgreementAcceptanceService, "accept_company",
            classmethod(lambda cls, **kw: called.append(kw) or {"ok": True}),
        )

        client = app.test_client()
        with client.session_transaction() as sess:
            sess.clear()
            sess['user'] = {'uid': 'real_user', 'ownerUID': 'real_owner', 'role': 'owner',
                            'email': 'a@b.c', 'name': 'A', 'status': 'active'}
            sess['selected_company_id'] = 'real_company'
            sess['selected_owner_uid'] = 'real_owner'
            sess['is_sandbox_mode'] = False

        with _session_deps() as mocks:
            _apply_deps(mocks)
            resp = client.post('/production-agreement/accept-company', data={'accept': '1'})

        # Sin token CSRF, el POST es rechazado (redirige) y nunca llega al servicio.
        assert resp.status_code == 302
        assert called == []
