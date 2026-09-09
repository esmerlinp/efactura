"""Tests del nuevo orden de autorización de desvinculación.

Regla: la autorización se solicita DESPUÉS de calcular las prestaciones
(Paso 1 del wizard, botón "Enviar a autorización"), nunca en la creación,
y el request de autorización lleva el esquema completo de prestaciones
en ``metadata`` para quien aprueba.

Cubre:
- _prestaciones_metadata: mapeo correcto + tolerancia a vacíos.
- _termination_auth_gate: reenvía el metadata al motor.
- create_authorization_request: persiste el metadata.
- _check_auth_hold: sigue bloqueando el avance en draft con auth pendiente.
"""

from unittest.mock import MagicMock, patch

from app.services.hr_authorization_service import create_authorization_request
from app.services.offboarding_service import OffboardingService

COMPANY = "company-test"


def _settlement():
    return {
        "terminationType": "despido_injustificado",
        "terminationDate": "2026-02-28",
        "salarioDiarioPromedio": 1500.0,
        "antiguedad": {"years": 3, "months": 2, "days": 5},
        "conceptos": {
            "preaviso": {"monto": 21000.0, "dias": 14, "baseLegal": "Art. 76", "aplica": True},
            "cesantia": {"monto": 94500.0, "dias": 63, "baseLegal": "Art. 80", "aplica": True},
            "vacaciones": {"monto": 0.0, "dias": 0, "baseLegal": "", "aplica": False},
        },
        "conceptosAdicionales": [
            {"name": "Bono", "type": "earning", "monto": 5000.0, "comment": "extra"},
        ],
        "descuentosDetalle": [
            {"name": "Préstamo", "monto": 2000.0},
        ],
        "totales": {
            "montoTotal": 120500.0,
            "montoNetoAPagar": 118500.0,
            "montoPrestaciones": 115500.0,
            "montoDerechosAdquiridos": 5000.0,
            "montoDescuentos": 2000.0,
            "montoExento": 115500.0,
        },
    }


def _req():
    return {
        "id": "off-1",
        "employeeName": "Juan Pérez",
        "terminationType": "despido_injustificado",
        "effectiveDate": "2026-02-28",
    }


# ═══════════════════════════════════════════════════════════════════════════
# _prestaciones_metadata
# ═══════════════════════════════════════════════════════════════════════════

class TestPrestacionesMetadata:
    def test_full_settlement_maps_correctly(self):
        from app.web.rrhh.offboarding import _prestaciones_metadata
        meta = _prestaciones_metadata(_settlement(), _req())
        assert meta["employeeName"] == "Juan Pérez"
        assert meta["terminationType"] == "despido_injustificado"
        assert meta["terminationDate"] == "2026-02-28"
        assert meta["montoTotal"] == 120500.0
        assert meta["montoNetoAPagar"] == 118500.0
        assert meta["montoPrestaciones"] == 115500.0
        assert meta["montoDerechosAdquiridos"] == 5000.0
        assert meta["montoDescuentos"] == 2000.0
        assert meta["montoExento"] == 115500.0
        assert meta["antiguedad"] == {"years": 3, "months": 2, "days": 5}
        assert meta["salarioDiarioPromedio"] == 1500.0
        # Solo conceptos que aplican
        keys = {c["key"] for c in meta["conceptos"]}
        assert keys == {"preaviso", "cesantia"}
        preaviso = next(c for c in meta["conceptos"] if c["key"] == "preaviso")
        assert preaviso["monto"] == 21000.0
        assert preaviso["dias"] == 14
        assert meta["conceptosAdicionales"][0]["name"] == "Bono"
        assert meta["descuentos"][0] == {"name": "Préstamo", "monto": 2000.0}

    def test_empty_inputs_do_not_crash(self):
        from app.web.rrhh.offboarding import _prestaciones_metadata
        meta = _prestaciones_metadata({}, {})
        assert meta["montoTotal"] == 0.0
        assert meta["montoNetoAPagar"] == 0.0
        assert meta["conceptos"] == []
        assert meta["conceptosAdicionales"] == []
        assert meta["descuentos"] == []

    def test_none_inputs_do_not_crash(self):
        from app.web.rrhh.offboarding import _prestaciones_metadata
        meta = _prestaciones_metadata(None, None)
        assert meta["montoTotal"] == 0.0
        assert meta["employeeName"] == ""

    def test_string_amounts_are_coerced(self):
        from app.web.rrhh.offboarding import _prestaciones_metadata
        s = _settlement()
        s["totales"]["montoTotal"] = "120500.00"
        meta = _prestaciones_metadata(s, _req())
        assert meta["montoTotal"] == 120500.0


# ═══════════════════════════════════════════════════════════════════════════
# _termination_auth_gate — reenvío del metadata
# ═══════════════════════════════════════════════════════════════════════════

class TestTerminationAuthGateMetadata:
    def _gate(self, metadata):
        import app.web.rrhh.offboarding as off_mod
        svc = MagicMock()
        svc.get_request.return_value = dict(_req())
        with patch.object(off_mod, "_user",
                          return_value={"uid": "u1", "email": "rrhh@x.com", "name": "RRHH"}), \
             patch.object(off_mod, "_has_termination_rule", return_value=True), \
             patch.object(off_mod, "url_for", return_value="/fake/wizard"), \
             patch("app.services.hr_authorization_service.create_authorization_request") as mock_create:
            mock_create.return_value = {
                "request": {"id": "auth-1"}, "approved": False, "isFallback": False,
            }
            result = off_mod._termination_auth_gate(
                svc, "off-1", COMPANY, "owner-1", True, metadata=metadata)
        return result, mock_create, svc

    def test_gate_forwards_metadata_to_engine(self):
        from app.web.rrhh.offboarding import _prestaciones_metadata
        meta = _prestaciones_metadata(_settlement(), _req())
        result, mock_create, svc = self._gate(meta)
        assert result["approved"] is False
        assert mock_create.call_count == 1
        assert mock_create.call_args.kwargs["metadata"] == meta
        # company_id, doc_type, doc_id van posicionales
        assert mock_create.call_args.args[1] == "termination"
        assert mock_create.call_args.args[2] == "off-1"
        assert mock_create.call_args.kwargs["entity_type"] == "offboarding"
        # Estampa el authorizationRequestId en la solicitud
        svc.save_request_raw.assert_called_once()
        saved_req = svc.save_request_raw.call_args.args[1]
        assert saved_req["authorizationRequestId"] == "auth-1"

    def test_gate_without_rule_does_not_create(self):
        import app.web.rrhh.offboarding as off_mod
        svc = MagicMock()
        with patch.object(off_mod, "_user", return_value={"uid": "u1"}), \
             patch.object(off_mod, "_has_termination_rule", return_value=False), \
             patch("app.services.hr_authorization_service.create_authorization_request") as mock_create:
            result = off_mod._termination_auth_gate(svc, "off-1", COMPANY, "owner-1", True)
        assert result == {"approved": True, "isFallback": True, "request": None}
        mock_create.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# Motor: el metadata persiste en la solicitud
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthorizationMetadataPlumbing:
    @patch("app.services.hr_authorization_service.hr")
    def test_create_persists_metadata(self, mock_hr):
        mock_hr.get_authorization_rules.return_value = [{
            "id": "rule-1", "docType": "termination", "minApprovals": 1,
            "approvers": [{"id": "a1", "name": "Aprobador", "email": "a1@x.com"}],
            "isActive": True,
        }]
        mock_hr.get_authorization_requests.return_value = []
        saved = {}
        mock_hr.save_authorization_request.side_effect = (
            lambda c, rid, data, sandbox=True: saved.update(data))
        mock_hr.get_mass_action.return_value = None
        meta = {"montoTotal": 120500.0, "conceptos": [{"key": "preaviso", "monto": 21000.0}]}
        with patch("app.services.hr_authorization_service.DatabaseService"):
            result = create_authorization_request(
                COMPANY, "termination", doc_id="off-1", doc_number="Juan Pérez",
                entity_type="mass_action", created_by_uid="u1",
                created_by_email="rrhh@x.com", metadata=meta,
            )
        assert result["approved"] is False
        assert saved["metadata"] == meta


# ═══════════════════════════════════════════════════════════════════════════
# El hold sigue bloqueando el avance en draft con auth pendiente
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthHoldUnchanged:
    def _svc(self):
        return OffboardingService(COMPANY, sandbox=True)

    def test_hold_blocks_draft_with_pending_auth(self):
        svc = self._svc()
        req = {"id": "off-1", "status": "draft", "authorizationRequestId": "auth-1"}
        with patch("app.services.hr_data_service.get_authorization_request",
                   return_value={"id": "auth-1", "status": "pending",
                                 "docTypeLabel": "Desvinculación"}):
            hold = svc._check_auth_hold(req)
        assert hold is not None
        assert "pendiente de autorización" in hold

    def test_hold_lifted_when_approved(self):
        svc = self._svc()
        req = {"id": "off-1", "status": "draft", "authorizationRequestId": "auth-1"}
        with patch("app.services.hr_data_service.get_authorization_request",
                   return_value={"id": "auth-1", "status": "approved"}):
            assert svc._check_auth_hold(req) is None

    def test_hold_ignores_non_draft(self):
        svc = self._svc()
        req = {"id": "off-1", "status": "pending_settlement",
               "authorizationRequestId": "auth-1"}
        with patch("app.services.hr_data_service.get_authorization_request",
                   return_value={"id": "auth-1", "status": "pending"}):
            assert svc._check_auth_hold(req) is None

    def test_hold_ignores_missing_auth_link(self):
        svc = self._svc()
        assert svc._check_auth_hold({"id": "off-1", "status": "draft"}) is None


# ═══════════════════════════════════════════════════════════════════════════
# Retiro de la cola de autorizaciones (corregir y reenviar)
# ═══════════════════════════════════════════════════════════════════════════

class TestWithdrawFromQueue:
    def _mock_off_svc(self, off):
        saved = {}
        mock_svc = MagicMock()
        mock_svc.get_request.return_value = dict(off)
        mock_svc.save_request_raw.side_effect = (
            lambda doc_id, data, user_email="": saved.update(data))
        return mock_svc, saved

    def test_stamp_cancelled_draft_clears_link(self):
        from app.services.hr_authorization_service import _stamp_offboarding
        off = {"id": "off-1", "status": "draft",
               "authorizationRequestId": "auth-1",
               "authorizationStatus": "pending",
               "authorizationComment": "x",
               "authorizationStampedAt": "2026-01-01",
               "employeeName": "Juan"}
        mock_svc, saved = self._mock_off_svc(off)
        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=mock_svc):
            _stamp_offboarding(
                dict(off), "off-1",
                {"authorizationRequestId": "auth-1",
                 "authorizationStatus": "cancelled"},
                "cancelled", COMPANY, True)
        assert "authorizationRequestId" not in saved
        assert "authorizationStatus" not in saved
        assert "authorizationComment" not in saved
        assert "authorizationStampedAt" not in saved
        assert saved["status"] == "draft"
        assert saved["employeeName"] == "Juan"
        mock_svc.transition.assert_not_called()

    def test_stamp_cancelled_non_draft_keeps_stamp(self):
        # Cancel total: la desvinculación ya está en terminal, se estampa normal.
        from app.services.hr_authorization_service import _stamp_offboarding
        off = {"id": "off-1", "status": "cancelled",
               "authorizationRequestId": "auth-1"}
        mock_svc, saved = self._mock_off_svc(off)
        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=mock_svc):
            _stamp_offboarding(
                dict(off), "off-1",
                {"authorizationRequestId": "auth-1",
                 "authorizationStatus": "cancelled"},
                "cancelled", COMPANY, True)
        assert saved["authorizationRequestId"] == "auth-1"
        assert saved["authorizationStatus"] == "cancelled"

    def test_hold_lifted_after_withdraw(self):
        svc = OffboardingService(COMPANY, sandbox=True)
        # Tras el retiro ya no hay vínculo: el wizard se desbloquea.
        assert svc._check_auth_hold({"id": "off-1", "status": "draft"}) is None

    def test_cancel_authorization_offboarding_withdraws_link(self):
        from app.services.hr_authorization_service import cancel_authorization
        auth = {"id": "auth-1", "docType": "termination", "documentId": "off-1",
                "docTypeLabel": "Desvinculación", "entityType": "offboarding",
                "status": "pending", "approvalHistory": []}
        off = {"id": "off-1", "status": "draft",
               "authorizationRequestId": "auth-1"}
        mock_svc, saved_off = self._mock_off_svc(off)
        saved_auth = {}
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService"), \
             patch("app.services.offboarding_service.OffboardingService",
                   return_value=mock_svc):
            mock_hr.get_authorization_request.return_value = dict(auth)
            mock_hr.save_authorization_request.side_effect = (
                lambda c, rid, data, sandbox=True: saved_auth.update(data))
            result = cancel_authorization(
                COMPANY, "auth-1", cancelled_by="rrhh@x.com", sandbox=True)
        assert result["success"] is True
        assert saved_auth["status"] == "cancelled"
        assert "authorizationRequestId" not in saved_off
        assert saved_off["status"] == "draft"


# ═══════════════════════════════════════════════════════════════════════════
# Inmutabilidad: una liquidación autorizada no puede recalcularse
# ═══════════════════════════════════════════════════════════════════════════

class TestSettlementRecalcLock:
    def _blocked(self, req, settlement, auth=None, auth_raises=False):
        import app.web.rrhh.offboarding as off_mod
        with patch.object(off_mod, "hr") as mock_hr:
            if auth_raises:
                mock_hr.get_authorization_request.side_effect = Exception("db down")
            else:
                mock_hr.get_authorization_request.return_value = auth
            return off_mod._settlement_recalc_blocked(
                req, settlement, COMPANY, True)

    def test_allowed_without_auth_nor_settlement(self):
        assert self._blocked({"id": "off-1", "status": "draft"}, None) is None

    def test_allowed_calculada_without_auth(self):
        req = {"id": "off-1", "status": "draft"}
        assert self._blocked(req, {"id": "s-1", "status": "calculada"}) is None

    def test_allowed_borrador(self):
        req = {"id": "off-1", "status": "draft"}
        assert self._blocked(req, {"id": "s-1", "status": "borrador"}) is None

    def test_allowed_auth_pending(self):
        req = {"id": "off-1", "status": "draft", "authorizationRequestId": "auth-1"}
        st = {"id": "s-1", "status": "calculada"}
        assert self._blocked(req, st, auth={"id": "auth-1", "status": "pending"}) is None

    def test_allowed_auth_returned(self):
        req = {"id": "off-1", "status": "draft", "authorizationRequestId": "auth-1"}
        st = {"id": "s-1", "status": "calculada"}
        assert self._blocked(req, st, auth={"id": "auth-1", "status": "returned"}) is None

    def test_allowed_auth_cancelled(self):
        # Tras retirar de la cola se puede corregir y reenviar.
        req = {"id": "off-1", "status": "draft", "authorizationRequestId": ""}
        st = {"id": "s-1", "status": "calculada"}
        assert self._blocked(req, st, auth={"id": "auth-1", "status": "cancelled"}) is None

    def test_blocked_auth_approved(self):
        req = {"id": "off-1", "status": "draft", "authorizationRequestId": "auth-1"}
        st = {"id": "s-1", "status": "calculada"}
        msg = self._blocked(req, st, auth={"id": "auth-1", "status": "approved"})
        assert msg is not None
        assert "congelados" in msg

    def test_blocked_auth_rejected(self):
        req = {"id": "off-1", "status": "cancelled", "authorizationRequestId": "auth-1"}
        st = {"id": "s-1", "status": "calculada"}
        msg = self._blocked(req, st, auth={"id": "auth-1", "status": "rejected"})
        assert msg is not None

    def test_blocked_settlement_aprobada(self):
        req = {"id": "off-1", "status": "draft"}
        msg = self._blocked(req, {"id": "s-1", "status": "aprobada"})
        assert msg is not None
        assert "aprobada" in msg

    def test_blocked_settlement_pendiente_pago(self):
        req = {"id": "off-1", "status": "pending_payment"}
        msg = self._blocked(req, {"id": "s-1", "status": "pendiente_pago"})
        assert msg is not None

    def test_blocked_settlement_pagada(self):
        req = {"id": "off-1", "status": "pending_documents"}
        msg = self._blocked(req, {"id": "s-1", "status": "pagada"})
        assert msg is not None

    def test_auth_lookup_failure_falls_through_to_settlement(self):
        # Si Firestore falla, no se bloquea por auth (comportamiento degradado),
        # pero el estado del settlement sí bloquea.
        req = {"id": "off-1", "status": "draft", "authorizationRequestId": "auth-1"}
        assert self._blocked(req, {"id": "s-1", "status": "calculada"},
                             auth_raises=True) is None
        assert self._blocked(req, {"id": "s-1", "status": "pagada"},
                             auth_raises=True) is not None


class TestRefreshPendingAuthMetadata:
    def test_refreshes_pending_auth(self):
        import app.web.rrhh.offboarding as off_mod
        auth = {"id": "auth-1", "status": "pending", "metadata": {}}
        saved = {}
        with patch.object(off_mod, "hr") as mock_hr:
            mock_hr.get_authorization_request.return_value = auth
            mock_hr.save_authorization_request.side_effect = (
                lambda c, rid, data, sandbox=True: saved.update(data))
            updated = off_mod._refresh_pending_auth_metadata(
                COMPANY, "auth-1", _settlement(), _req(), True)
        assert updated is True
        assert saved["metadata"]["montoTotal"] == 120500.0

    def test_skips_non_pending_auth(self):
        import app.web.rrhh.offboarding as off_mod
        auth = {"id": "auth-1", "status": "approved", "metadata": {}}
        with patch.object(off_mod, "hr") as mock_hr:
            mock_hr.get_authorization_request.return_value = auth
            updated = off_mod._refresh_pending_auth_metadata(
                COMPANY, "auth-1", _settlement(), _req(), True)
            mock_hr.save_authorization_request.assert_not_called()
        assert updated is False

    def test_skips_without_auth_id(self):
        import app.web.rrhh.offboarding as off_mod
        with patch.object(off_mod, "hr") as mock_hr:
            updated = off_mod._refresh_pending_auth_metadata(
                COMPANY, "", _settlement(), _req(), True)
            mock_hr.get_authorization_request.assert_not_called()
        assert updated is False


# ═══════════════════════════════════════════════════════════════════════════
# Corrección post-autorización: reabrir sin editar la versión aprobada
# ═══════════════════════════════════════════════════════════════════════════

class TestRequestSettlementCorrection:
    def _svc_with(self, req, settlement, auth=None):
        import app.services.offboarding_service as off_mod
        stores = {"requests": {req["id"]: dict(req)},
                  "settlements": {},
                  "auths": {}}
        if settlement:
            stores["settlements"][settlement.get("id", "s-1")] = dict(settlement)
        if auth:
            stores["auths"][auth["id"]] = dict(auth)

        mock_ods = MagicMock()
        mock_ods.get_request.side_effect = (
            lambda rid, cid, sb: dict(stores["requests"].get(rid) or {}))
        mock_ods.get_one.side_effect = (
            lambda coll, sid, cid, sb: dict(stores["settlements"].get(sid) or {}))
        def _save(coll, sid, data, cid, sb):
            stores["settlements"][sid] = dict(data)
        mock_ods.save.side_effect = _save
        def _save_req(rid, data, cid, sb):
            stores["requests"][rid] = dict(data)
        mock_ods.save_request.side_effect = _save_req

        class _FakeStatusChange:
            # pydantic está mockeado en conftest; emular model_dump real.
            def __init__(self, **kwargs):
                self._data = dict(kwargs)
            def model_dump(self):
                return dict(self._data)

        patches = [
            patch.object(off_mod, "ods", mock_ods),
            patch.object(off_mod, "log_action"),
            patch.object(off_mod, "StatusChange", _FakeStatusChange),
            patch("app.services.hr_data_service.get_authorization_request",
                  side_effect=lambda cid, aid, sandbox=True: (
                      dict(stores["auths"].get(aid)) if stores["auths"].get(aid) else None)),
            patch("app.services.hr_data_service.save_authorization_request",
                  side_effect=lambda cid, aid, data, sandbox=True: (
                      stores["auths"].__setitem__(aid, dict(data)))),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        from app.services.offboarding_service import OffboardingService
        return OffboardingService(COMPANY, sandbox=True), stores

    # unittest-style cleanup support without TestCase
    def addCleanup(self, fn):
        self._cleanups = getattr(self, "_cleanups", [])
        self._cleanups.append(fn)

    def setup_method(self):
        self._cleanups = []

    def teardown_method(self):
        for fn in getattr(self, "_cleanups", []):
            try:
                fn()
            except Exception:
                pass

    def _approved_case(self):
        req = {"id": "off-1", "status": "pending_settlement",
               "authorizationRequestId": "auth-1", "settlementId": "s-1",
               "statusHistory": []}
        st = dict(_settlement())
        st.update({"id": "s-1", "status": "pendiente_pago", "version": 2,
                   "totales": dict(_settlement()["totales"])})
        auth = {"id": "auth-1", "status": "approved", "approvalHistory": []}
        return req, st, auth

    def test_success_approved(self):
        svc, stores = self._svc_with(*self._approved_case())
        result = svc.request_settlement_correction(
            "off-1", "Error en vacaciones", "rrhh@x.com")
        assert result["snapshotId"] == "s-1-v2"
        snap = stores["settlements"]["s-1-v2"]
        assert snap["status"] == "reemplazada"
        assert snap["isSnapshot"] is True
        assert snap["snapshotOf"] == "s-1"
        assert snap["replaceReason"] == "Error en vacaciones"
        # La versión aprobada queda intacta en el snapshot.
        assert snap["totales"]["montoTotal"] == 120500.0
        live = stores["settlements"]["s-1"]
        assert live["status"] == "calculada"
        auth = stores["auths"]["auth-1"]
        assert auth["status"] == "cancelled"
        assert auth["correctionReason"] == "Error en vacaciones"
        assert "Invalidada por solicitud de corrección" in auth["approvalHistory"][-1]["comment"]
        req = stores["requests"]["off-1"]
        assert req["status"] == "draft"
        assert "authorizationRequestId" not in req
        assert req["lastCorrection"]["reason"] == "Error en vacaciones"
        assert req["lastCorrection"]["previousTotal"] == 120500.0
        assert req["lastCorrection"]["previousVersion"] == 2
        assert req["statusHistory"][-1]["toStatus"] == "draft"

    def test_success_fallback_without_auth(self):
        req = {"id": "off-1", "status": "pending_settlement",
               "settlementId": "s-1", "statusHistory": []}
        st = dict(_settlement())
        st.update({"id": "s-1", "status": "aprobada", "version": 1,
                   "totales": dict(_settlement()["totales"])})
        svc, stores = self._svc_with(req, st, auth=None)
        result = svc.request_settlement_correction(
            "off-1", "Monto mal digitado", "rrhh@x.com")
        assert result["snapshotId"] == "s-1-v1"
        assert stores["requests"]["off-1"]["status"] == "draft"
        assert stores["settlements"]["s-1"]["status"] == "calculada"

    def test_blocked_pagada(self):
        req, st, auth = self._approved_case()
        st["status"] = "pagada"
        svc, _ = self._svc_with(req, st, auth)
        try:
            svc.request_settlement_correction("off-1", "Error", "rrhh@x.com")
            raise AssertionError("debió bloquear")
        except ValueError as e:
            assert "pagada" in str(e)

    def test_blocked_pending_auth(self):
        req, st, auth = self._approved_case()
        auth["status"] = "pending"
        req["status"] = "draft"
        st["status"] = "calculada"
        svc, _ = self._svc_with(req, st, auth)
        try:
            svc.request_settlement_correction("off-1", "Error", "rrhh@x.com")
            raise AssertionError("debió bloquear")
        except ValueError as e:
            assert "Retirar de la cola" in str(e)

    def test_blocked_empty_reason(self):
        svc, _ = self._svc_with(*self._approved_case())
        try:
            svc.request_settlement_correction("off-1", "   ", "rrhh@x.com")
            raise AssertionError("debió bloquear")
        except ValueError as e:
            assert "motivo" in str(e).lower()

    def test_blocked_terminal(self):
        req, st, auth = self._approved_case()
        req["status"] = "completed"
        svc, _ = self._svc_with(req, st, auth)
        try:
            svc.request_settlement_correction("off-1", "Error", "rrhh@x.com")
            raise AssertionError("debió bloquear")
        except ValueError as e:
            assert "terminal" in str(e)

    def test_blocked_nothing_locked(self):
        req = {"id": "off-1", "status": "draft", "settlementId": "s-1",
               "statusHistory": []}
        st = dict(_settlement())
        st.update({"id": "s-1", "status": "calculada", "version": 1,
                   "totales": dict(_settlement()["totales"])})
        svc, _ = self._svc_with(req, st, auth=None)
        try:
            svc.request_settlement_correction("off-1", "Error", "rrhh@x.com")
            raise AssertionError("debió bloquear")
        except ValueError as e:
            assert "recalcularse directamente" in str(e)

    def test_blocked_no_settlement(self):
        req = {"id": "off-1", "status": "draft", "statusHistory": []}
        svc, _ = self._svc_with(req, None, auth=None)
        try:
            svc.request_settlement_correction("off-1", "Error", "rrhh@x.com")
            raise AssertionError("debió bloquear")
        except ValueError as e:
            assert "vinculada" in str(e)

    def test_metadata_includes_correction(self):
        from app.web.rrhh.offboarding import _prestaciones_metadata
        req = dict(_req())
        req["lastCorrection"] = {
            "reason": "Error en vacaciones", "by": "rrhh@x.com",
            "at": "2026-03-01T10:00:00", "previousVersion": 2,
            "previousTotal": 120500.0, "previousNeto": 118500.0,
        }
        meta = _prestaciones_metadata(_settlement(), req)
        assert meta["correction"]["reason"] == "Error en vacaciones"
        assert meta["correction"]["previousVersion"] == 2
        assert meta["correction"]["previousTotal"] == 120500.0

    def test_metadata_without_correction_is_none(self):
        from app.web.rrhh.offboarding import _prestaciones_metadata
        meta = _prestaciones_metadata(_settlement(), _req())
        assert meta["correction"] is None

    def test_enum_reemplazada(self):
        from app.models.offboarding import SettlementStatus
        assert SettlementStatus.REEMPLAZADA.value == "reemplazada"
