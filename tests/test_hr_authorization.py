"""Tests unitarios para el motor de autorizaciones de RRHH (cola N de M).

Cubre: resolución de aprobadores, fallback de auto-aprobación, quórum,
rechazo, devolución para corrección, reenvío y aplicación a entidades.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.hr_authorization_service import (
    resolve_approvers,
    create_authorization_request,
    decide_authorization,
    return_for_correction,
    resubmit_authorization,
    get_pending_for_user,
    _normalise_approvers,
    _notify,
    _stamp_entity,
    reassign_authorization,
)
from app.services.db_service import DatabaseService
from app.services.state_machine import (
    StateMachineValidator, MASS_ACTION_STATES, OFFBOARDING_STATES,
)

COMPANY = "company-test"


def _rule(doc_type="salary_change", approvers=None, min_approvals=1, is_active=True):
    return {
        "id": "rule-1",
        "docType": doc_type,
        "minApprovals": min_approvals,
        "approvers": approvers or [{"id": "approver-1", "name": "Aprobador 1", "email": "a1@x.com"}],
        "isActive": is_active,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Máquina de estados — transición "returned"
# ═══════════════════════════════════════════════════════════════════════════

class TestReturnedStateMachine:
    def test_mass_action_transitions(self):
        ma = StateMachineValidator(MASS_ACTION_STATES)
        assert ma.can_transition("pending_approval", "returned")
        assert ma.can_transition("returned", "pending_approval")
        assert not ma.can_transition("approved", "returned")

    def test_offboarding_transitions(self):
        ob = StateMachineValidator(OFFBOARDING_STATES)
        assert ob.can_transition("pending_supervisor_approval", "returned")
        assert ob.can_transition("pending_hr_approval", "returned")
        assert ob.can_transition("returned", "pending_supervisor_approval")
        assert ob.can_transition("returned", "pending_hr_approval")


# ═══════════════════════════════════════════════════════════════════════════
# _normalise_approvers
# ═══════════════════════════════════════════════════════════════════════════

class TestNormaliseApprovers:
    def test_dict_items(self):
        result = _normalise_approvers([{"id": "u1", "name": "Ana", "email": "ana@x.com"}])
        assert result == [{"id": "u1", "name": "Ana", "email": "ana@x.com"}]

    def test_string_pipe_items(self):
        result = _normalise_approvers(["u1|Ana|ana@x.com"])
        assert result == [{"id": "u1", "name": "Ana", "email": "ana@x.com"}]

    def test_empty(self):
        assert _normalise_approvers([]) == []
        assert _normalise_approvers(None) == []


# ═══════════════════════════════════════════════════════════════════════════
# resolve_approvers
# ═══════════════════════════════════════════════════════════════════════════

class TestResolveApprovers:
    @patch("app.services.hr_authorization_service.hr")
    def test_fallback_self_approval(self, mock_hr):
        mock_hr.get_authorization_rules.return_value = []
        result = resolve_approvers(COMPANY, "salary_change", created_by_uid="u_creator",
                                   created_by_email="c@x.com", created_by_name="Creador")
        assert result["isFallback"] is True
        assert result["minApprovals"] == 1
        assert result["approvers"][0]["id"] == "u_creator"
        assert result["approvers"][0]["email"] == "c@x.com"

    @patch("app.services.hr_authorization_service.hr")
    def test_rule_overrides_fallback(self, mock_hr):
        mock_hr.get_authorization_rules.return_value = [_rule(approvers=[
            {"id": "a", "name": "A", "email": "a@x.com"},
            {"id": "b", "name": "B", "email": "b@x.com"},
        ], min_approvals=2)]
        result = resolve_approvers(COMPANY, "salary_change", created_by_uid="u_creator")
        assert result["isFallback"] is False
        assert result["minApprovals"] == 2
        assert len(result["approvers"]) == 2

    @patch("app.services.hr_authorization_service.hr")
    def test_inactive_rule_ignored(self, mock_hr):
        mock_hr.get_authorization_rules.return_value = [_rule(is_active=False)]
        result = resolve_approvers(COMPANY, "salary_change", created_by_uid="u_creator")
        assert result["isFallback"] is True


# ═══════════════════════════════════════════════════════════════════════════
# create_authorization_request
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateRequest:
    def _patch_db(self):
        return patch("app.services.hr_authorization_service.DatabaseService")

    @patch("app.services.hr_authorization_service.hr")
    def test_fallback_creates_approved_request(self, mock_hr):
        mock_hr.get_authorization_rules.return_value = []
        saved = {}
        mock_hr.save_authorization_request.side_effect = lambda c, rid, data, sandbox=True: saved.update(data)
        mock_hr.get_authorization_request.return_value = None
        mock_hr.get_mass_action.return_value = None

        with self._patch_db() as mock_db:
            result = create_authorization_request(
                COMPANY, "salary_change", doc_id="ma-1", doc_number="MA-1",
                entity_type="mass_action", created_by_uid="u_creator",
                created_by_email="c@x.com", created_by_name="Creador",
            )
        assert result["approved"] is True
        assert result["isFallback"] is True
        assert saved["status"] == "approved"
        assert saved["approvalSteps"][0]["status"] == "approved"
        assert saved["approvalSteps"][0]["comment"].startswith("Auto-aprobacion")
        mock_db.create_user_notification.assert_called()

    @patch("app.services.hr_authorization_service.hr")
    def test_rule_creates_pending_request_and_notifies(self, mock_hr):
        mock_hr.get_authorization_rules.return_value = [_rule(min_approvals=1)]
        saved = {}
        mock_hr.save_authorization_request.side_effect = lambda c, rid, data, sandbox=True: saved.update(data)
        mock_hr.get_authorization_request.return_value = None
        mock_hr.get_mass_action.return_value = None

        with self._patch_db() as mock_db:
            result = create_authorization_request(
                COMPANY, "salary_change", doc_id="ma-1", entity_type="mass_action",
                created_by_uid="u_creator", created_by_email="c@x.com",
            )
        assert result["approved"] is False
        assert saved["status"] == "pending"
        assert saved["ruleId"] == "rule-1"
        mock_db.create_user_notification.assert_called()

    @patch("app.services.hr_authorization_service.hr")
    def test_reuses_open_request(self, mock_hr):
        existing = {"id": "req-existing", "status": "pending", "ruleId": "rule-1"}
        mock_hr.get_authorization_requests.return_value = [
            {"id": "req-existing", "docType": "salary_change", "documentId": "ma-1", "status": "pending", "ruleId": "rule-1"}
        ]
        mock_hr.get_authorization_request.return_value = existing
        with self._patch_db():
            result = create_authorization_request(
                COMPANY, "salary_change", doc_id="ma-1", entity_type="mass_action",
                created_by_uid="u_creator",
            )
        assert result["request"]["id"] == "req-existing"


# ═══════════════════════════════════════════════════════════════════════════
# decide_authorization — quórum N de M
# ═══════════════════════════════════════════════════════════════════════════

def _pending_request(steps=None, min_approvals=1, rule_id="rule-1"):
    return {
        "id": "req-1",
        "docType": "salary_change",
        "documentId": "ma-1",
        "docTypeLabel": "Cambio de Salario",
        "entityType": "mass_action",
        "createdByUid": "u_creator",
        "createdByEmail": "c@x.com",
        "minApprovals": min_approvals,
        "status": "pending",
        "isFallback": not rule_id,
        "approvalSteps": steps or [
            {"id": "a", "name": "A", "email": "a@x.com", "status": "pending", "decidedAt": None, "comment": ""},
        ],
        "approvalHistory": [],
        "link": "",
    }


class TestDecideAuthorization:
    def _run(self, request, approver, approved=True, comment=""):
        mock_db = MagicMock()
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService", mock_db), \
             patch("app.services.db_service.db_firestore", None):
            mock_hr.get_authorization_request.return_value = request
            mock_hr.get_mass_action.return_value = None
            return decide_authorization(COMPANY, request["id"], approver,
                                        approved=approved, comment=comment)

    def test_single_approver_approves(self):
        req = _pending_request()
        result = self._run(req, "a", approved=True, comment="ok")
        assert result["success"] is True
        assert result["status"] == "approved"
        assert req["approvalSteps"][0]["status"] == "approved"

    def test_quorum_reached_only_after_second_approval(self):
        req = _pending_request(
            steps=[
                {"id": "a", "name": "A", "email": "a@x.com", "status": "pending", "decidedAt": None, "comment": ""},
                {"id": "b", "name": "B", "email": "b@x.com", "status": "pending", "decidedAt": None, "comment": ""},
            ],
            min_approvals=2,
        )
        result = self._run(req, "a", approved=True)
        assert result["status"] == "pending"

        result = self._run(req, "b", approved=True)
        assert result["status"] == "approved"

    def test_single_rejection_rejects(self):
        req = _pending_request(
            steps=[
                {"id": "a", "name": "A", "email": "a@x.com", "status": "pending", "decidedAt": None, "comment": ""},
                {"id": "b", "name": "B", "email": "b@x.com", "status": "pending", "decidedAt": None, "comment": ""},
            ],
            min_approvals=2,
        )
        result = self._run(req, "b", approved=False, comment="no procede")
        assert result["status"] == "rejected"

    def test_already_decided_approver_rejected(self):
        req = _pending_request()
        self._run(req, "a", approved=True)
        result = self._run(req, "a", approved=False)
        assert result["success"] is False

    def test_unknown_approver_rejected(self):
        req = _pending_request()
        result = self._run(req, "stranger")
        assert result["success"] is False


# ═══════════════════════════════════════════════════════════════════════════
# return_for_correction / resubmit_authorization
# ═══════════════════════════════════════════════════════════════════════════

class TestReturnResubmit:
    def test_return_requires_comment(self):
        with patch("app.services.hr_authorization_service.hr") as mock_hr:
            mock_hr.get_authorization_request.return_value = _pending_request()
            result = return_for_correction(COMPANY, "req-1", "a", comment="  ")
            assert result["success"] is False

    def test_return_and_resubmit_flow(self):
        req = _pending_request()
        mock_db = MagicMock()
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService", mock_db):
            mock_hr.get_authorization_request.return_value = req
            mock_hr.get_mass_action.return_value = None

            result = return_for_correction(COMPANY, req["id"], "a", comment="corrige el monto")
            assert result["status"] == "returned"
            assert req["status"] == "returned"
            assert req["returnComment"] == "corrige el monto"

            mock_hr.get_authorization_request.return_value = req
            result = resubmit_authorization(COMPANY, req["id"], resubmitted_by="c@x.com")
            assert result["status"] == "pending"
            assert req["approvalSteps"][0]["status"] == "pending"


# ═══════════════════════════════════════════════════════════════════════════
# get_pending_for_user
# ═══════════════════════════════════════════════════════════════════════════

class TestPendingForUser:
    def test_only_returns_requests_with_user_step(self):
        req_mine = _pending_request()
        req_other = _pending_request(steps=[
            {"id": "z", "name": "Z", "email": "z@x.com", "status": "pending", "decidedAt": None, "comment": ""},
        ])
        with patch("app.services.hr_authorization_service.hr") as mock_hr:
            mock_hr.get_authorization_requests.return_value = [req_mine, req_other]
            result = get_pending_for_user(COMPANY, "a")
        assert len(result) == 1
        assert result[0]["id"] == "req-1"


# ═══════════════════════════════════════════════════════════════════════════
# Comentarios — mapeo de colección HR en DatabaseService
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthorizationCommentsCollMap:
    def _run(self, sandbox):
        mock_coll = MagicMock()
        mock_doc = MagicMock()
        mock_comments_coll = MagicMock()
        mock_doc.collection.return_value = mock_comments_coll
        mock_comments_coll.get.return_value = []
        mock_coll.document.return_value = mock_doc

        with patch("app.services.db_service.firebase_initialized", True), \
             patch("app.services.db_service._company_coll", return_value=mock_coll) as mock_cc:
            DatabaseService.get_resource_comments("owner-1", "authorizations", "req-1",
                                                  sandbox=sandbox, company_id=COMPANY)
        expected = "sandbox_hr_authorization_requests" if sandbox else "hr_authorization_requests"
        mock_cc.assert_called_once_with(company_id=COMPANY, owner_uid="owner-1", coll_name=expected)

    def test_sandbox_collection(self):
        self._run(sandbox=True)

    def test_production_collection(self):
        self._run(sandbox=False)


# ═══════════════════════════════════════════════════════════════════════════
# Notificaciones — email
# ═══════════════════════════════════════════════════════════════════════════

class TestNotifyEmail:
    @patch("app.services.hr_authorization_service._send_email")
    def test_notify_sends_email(self, mock_send):
        with patch("app.services.hr_authorization_service.DatabaseService") as mock_db:
            _notify("u1", "Título", "Mensaje", "/rrhh/authorizations/req-1",
                    "authorization_pending", email="a@x.com")
        mock_db.create_user_notification.assert_called_once()
        mock_send.assert_called_once_with("a@x.com", "Título", "Mensaje",
                                          "/rrhh/authorizations/req-1")

    @patch("app.services.hr_authorization_service._send_email")
    def test_notify_without_email_skips_mailer(self, mock_send):
        with patch("app.services.hr_authorization_service.DatabaseService") as mock_db:
            _notify("u1", "Título", "Mensaje", "", "authorization_pending")
        mock_db.create_user_notification.assert_called_once()
        mock_send.assert_called_once_with("", "Título", "Mensaje", "")

    def test_notify_skips_when_no_recipient(self):
        with patch("app.services.hr_authorization_service.DatabaseService") as mock_db:
            _notify("", "Título", "Mensaje", "", "authorization_pending", email="")
        mock_db.create_user_notification.assert_not_called()

    def test_email_body_renders_cta(self):
        from app.services.hr_authorization_service import _email_body
        html = _email_body("Aprobar", "Mensaje", "/rrhh/authorizations/req-1")
        assert "Aprobar" in html
        assert "/rrhh/authorizations/req-1" in html
        assert "Mensaje" in html


# ═══════════════════════════════════════════════════════════════════════════
# Enganche offboarding — gate en _check_sod y estampado de rechazo/devolución
# ═══════════════════════════════════════════════════════════════════════════

class TestOffboardingHook:
    def _off_request(self, status="pending_hr_approval"):
        return {"id": "off-1", "employeeId": "emp-1", "status": status}

    def _stamp_request(self, status):
        return {
            "id": "req-1",
            "status": status,
            "approvalHistory": [{"action": status, "comment": "comentario"}],
            "approvedBy": "Jefe HR",
        }

    def test_sod_blocks_settlement_without_authorization(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService(COMPANY, True)
        req = self._off_request()
        req["authorizationRequestId"] = "req-1"
        with patch("app.services.hr_data_service.get_authorization_request",
                   return_value={"status": "pending"}):
            result = svc._check_sod("pending_hr_approval", "pending_settlement",
                                    req, "hr@x.com", "hr")
        assert result is not None

    def test_sod_allows_settlement_when_authorized(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService(COMPANY, True)
        req = self._off_request()
        req["authorizationRequestId"] = "req-1"
        with patch("app.services.hr_data_service.get_authorization_request",
                   return_value={"status": "approved"}):
            result = svc._check_sod("pending_hr_approval", "pending_settlement",
                                    req, "hr@x.com", "hr")
        assert result is None

    def test_stamp_offboarding_rejected_transitions(self):
        mock_svc = MagicMock()
        mock_svc.get_request.return_value = self._off_request()
        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=mock_svc):
            _stamp_entity(COMPANY, "offboarding", "off-1", self._stamp_request("rejected"))
        mock_svc.transition.assert_called_once_with(
            "off-1", "rejected", user_email="Sistema", user_role="owner", comment="comentario")

    def test_stamp_offboarding_returned_transitions(self):
        mock_svc = MagicMock()
        mock_svc.get_request.return_value = self._off_request()
        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=mock_svc):
            _stamp_entity(COMPANY, "offboarding", "off-1", self._stamp_request("returned"))
        mock_svc.transition.assert_called_once_with(
            "off-1", "returned", user_email="Sistema", user_role="owner", comment="comentario")

    def test_stamp_offboarding_approved_does_not_transition(self):
        mock_svc = MagicMock()
        mock_svc.get_request.return_value = self._off_request()
        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=mock_svc):
            _stamp_entity(COMPANY, "offboarding", "off-1", self._stamp_request("approved"))
        mock_svc.transition.assert_not_called()
        mock_svc.save_request_raw.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# Asignado por defecto y reasignación
# ═══════════════════════════════════════════════════════════════════════════

class TestDefaultAssignee:
    def _rule(self, approvers=None, default_assignee=None, min_approvals=1):
        rule = {
            "id": "rule-1",
            "docType": "salary_change",
            "minApprovals": min_approvals,
            "approvers": approvers or [
                {"id": "a1", "name": "A1", "email": "a1@x.com"},
                {"id": "a2", "name": "A2", "email": "a2@x.com"},
            ],
            "isActive": True,
        }
        if default_assignee:
            rule["defaultAssignee"] = default_assignee
        return rule

    def test_resolve_approvers_carries_default_assignee(self):
        with patch("app.services.hr_authorization_service.hr") as mock_hr:
            mock_hr.get_authorization_rules.return_value = [
                self._rule(default_assignee={"id": "a2", "name": "A2", "email": "a2@x.com"})
            ]
            result = resolve_approvers(COMPANY, "salary_change")
        assert result["defaultAssignee"]["id"] == "a2"

    def test_resolve_approvers_fallback_assignee_is_first_approver(self):
        with patch("app.services.hr_authorization_service.hr") as mock_hr:
            mock_hr.get_authorization_rules.return_value = [self._rule()]
            result = resolve_approvers(COMPANY, "salary_change")
        assert result["defaultAssignee"]["id"] == "a1"

    def test_create_request_stores_assigned_to(self):
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService"):
            mock_hr.get_authorization_rules.return_value = [
                self._rule(default_assignee={"id": "a2", "name": "A2", "email": "a2@x.com"})
            ]
            mock_hr.get_authorization_requests.return_value = []
            mock_hr.get_authorization_request.return_value = None
            mock_hr.get_mass_action.return_value = None
            result = create_authorization_request(
                COMPANY, "salary_change", doc_id="ma-1", entity_type="mass_action",
                created_by_uid="u_creator", created_by_email="c@x.com",
            )
        req = result["request"]
        assert req["assignedTo"]["id"] == "a2"
        assert req["ruleDefaultAssignee"]["id"] == "a2"

    def test_return_for_correction_reassigns_to_creator(self):
        req = _pending_request()
        req["createdByUid"] = "u_creator"
        req["createdByName"] = "Creador"
        mock_db = MagicMock()
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService", mock_db):
            mock_hr.get_authorization_request.return_value = req
            mock_hr.get_mass_action.return_value = None
            return_for_correction(COMPANY, "req-1", "a", comment="corrije")
        assert req["assignedTo"]["id"] == "u_creator"

    def test_resubmit_restores_default_assignee(self):
        req = _pending_request()
        req["status"] = "returned"
        req["ruleDefaultAssignee"] = {"id": "a", "name": "A", "email": "a@x.com"}
        req["assignedTo"] = {"id": "u_creator", "name": "Creador", "email": "c@x.com"}
        mock_db = MagicMock()
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService", mock_db):
            mock_hr.get_authorization_request.return_value = req
            result = resubmit_authorization(COMPANY, "req-1")
        assert result["success"]
        assert req["assignedTo"]["id"] == "a"

    def test_reassign_to_another_approver(self):
        req = _pending_request(steps=[
            {"id": "a1", "name": "A1", "email": "a1@x.com", "status": "pending", "decidedAt": None, "comment": ""},
            {"id": "a2", "name": "A2", "email": "a2@x.com", "status": "pending", "decidedAt": None, "comment": ""},
        ])
        req["assignedTo"] = {"id": "a1", "name": "A1", "email": "a1@x.com"}
        mock_db = MagicMock()
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService", mock_db):
            mock_hr.get_authorization_request.return_value = req
            result = reassign_authorization(COMPANY, "req-1", "a2", reassigned_by="Admin")
        assert result["success"]
        assert req["assignedTo"]["id"] == "a2"
        assert len(req["assigneeHistory"]) == 1
        assert req["assigneeHistory"][0]["from"] == "a1"

    def test_reassign_to_creator(self):
        req = _pending_request()
        req["createdByUid"] = "u_creator"
        req["createdByName"] = "Creador"
        req["assignedTo"] = {"id": "a", "name": "A", "email": "a@x.com"}
        mock_db = MagicMock()
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService", mock_db):
            mock_hr.get_authorization_request.return_value = req
            result = reassign_authorization(COMPANY, "req-1", "u_creator", reassigned_by="Admin")
        assert result["success"]
        assert req["assignedTo"]["id"] == "u_creator"

    def test_reassign_outsider_fails(self):
        req = _pending_request()
        mock_db = MagicMock()
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService", mock_db):
            mock_hr.get_authorization_request.return_value = req
            result = reassign_authorization(COMPANY, "req-1", "stranger", reassigned_by="Admin")
        assert not result["success"]

    def test_resubmit_preserves_approved_signatures(self):
        req = _pending_request(steps=[
            {"id": "a", "name": "A", "email": "a@x.com", "status": "approved", "decidedAt": "2026-01-01T00:00:00", "comment": "ok"},
            {"id": "b", "name": "B", "email": "b@x.com", "status": "pending", "decidedAt": None, "comment": ""},
        ], min_approvals=2)
        req["status"] = "returned"
        req["ruleDefaultAssignee"] = {"id": "b", "name": "B", "email": "b@x.com"}
        mock_db = MagicMock()
        with patch("app.services.hr_authorization_service.hr") as mock_hr, \
             patch("app.services.hr_authorization_service.DatabaseService", mock_db), \
             patch("app.services.hr_authorization_service._stamp_entity"):
            mock_hr.get_authorization_request.return_value = req
            result = resubmit_authorization(COMPANY, "req-1")
        assert result["success"]
        assert result["status"] == "pending"
        assert req["approvalSteps"][0]["status"] == "approved"
        assert req["approvalSteps"][1]["status"] == "pending"
        assert result["request"]["approvalSteps"][0]["status"] == "approved"
