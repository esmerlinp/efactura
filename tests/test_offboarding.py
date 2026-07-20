"""Tests unitarios para el módulo Offboarding.

Cubre: modelos, máquina de estados, SOD, checklist, TSS.
"""

import pytest
from datetime import datetime, timezone
from app.models.offboarding import (
    TerminationRequest, TerminationSettlement, TerminationChecklist,
    TerminationStatus, TerminationType, SettlementStatus,
    ChecklistItem, ChecklistCategory, ApprovalRecord,
    OFFBOARDING_STATES, DEFAULT_CHECKLIST_TASKS,
    TERMINATION_TYPE_RISK_MAP,
)
from app.services.state_machine import StateMachineValidator, OFFBOARDING_STATES as SM_STATES


# ═══════════════════════════════════════════════════════════════════════════
# MODELOS
# ═══════════════════════════════════════════════════════════════════════════

class TestTerminationRequestModel:
    def test_default_status_is_draft(self):
        req = TerminationRequest()
        assert req.status == TerminationStatus.DRAFT

    def test_default_type_is_renuncia(self):
        req = TerminationRequest()
        assert req.terminationType == TerminationType.RENUNCIA_VOLUNTARIA

    def test_auto_generates_id(self):
        req = TerminationRequest()
        assert req.id is not None
        assert len(req.id) > 0

    def test_custom_status(self):
        req = TerminationRequest(status=TerminationStatus.APPROVED)
        assert req.status == TerminationStatus.APPROVED

    def test_status_history_on_create(self):
        req = TerminationRequest()
        assert req.statusHistory == []

    def test_full_employee_data(self):
        req = TerminationRequest(
            employeeId="emp_001",
            employeeName="Juan Pérez",
            cedula="001-2345678-9",
            departmentId="dept_01",
            positionId="pos_01",
            supervisorId="sup_01",
        )
        assert req.employeeName == "Juan Pérez"
        assert req.cedula == "001-2345678-9"


class TestTerminationSettlementModel:
    def test_default_status_is_borrador(self):
        s = TerminationSettlement()
        assert s.status == SettlementStatus.BORRADOR

    def test_calculated_fields_default_zero(self):
        s = TerminationSettlement()
        assert s.baseSalary == 0.0
        assert s.montoNetoAPagar == 0.0


class TestChecklistModel:
    def test_checklist_item_defaults(self):
        item = ChecklistItem(task="Devolver laptop", category=ChecklistCategory.ASSETS)
        assert item.completed is False
        assert item.isMandatory is True

    def test_checklist_tracks_progress(self):
        cl = TerminationChecklist(
            items=[
                ChecklistItem(task="A").model_dump(),
                ChecklistItem(task="B").model_dump(),
            ],
            totalItems=2,
            completedItems=0,
        )
        assert cl.totalItems == 2
        assert cl.allCompleted is False


# ═══════════════════════════════════════════════════════════════════════════
# MÁQUINA DE ESTADOS
# ═══════════════════════════════════════════════════════════════════════════

class TestOffboardingStateMachine:
    def setup_method(self):
        self.sm = StateMachineValidator(SM_STATES)

    def test_defines_all_states(self):
        expected = [
            "draft", "pending_supervisor_approval", "pending_hr_approval",
            "approved", "pending_settlement", "pending_assets",
            "pending_payment", "pending_documents", "pending_tss",
            "completed", "cancelled", "rejected",
        ]
        for s in expected:
            assert s in SM_STATES, f"Falta estado: {s}"

    def test_draft_to_submit(self):
        assert self.sm.can_transition("draft", "pending_supervisor_approval") is True

    def test_draft_to_cancel(self):
        assert self.sm.can_transition("draft", "cancelled") is True

    def test_draft_to_approved_blocked(self):
        assert self.sm.can_transition("draft", "approved") is False

    def test_completed_no_transitions(self):
        assert self.sm.get_allowed_transitions("completed") == []

    def test_cancelled_no_transitions(self):
        assert self.sm.get_allowed_transitions("cancelled") == []

    def test_rejected_no_transitions(self):
        assert self.sm.get_allowed_transitions("rejected") == []

    def test_full_pipeline(self):
        pipeline = [
            ("draft", "pending_supervisor_approval"),
            ("pending_supervisor_approval", "pending_hr_approval"),
            ("pending_hr_approval", "pending_settlement"),
            ("pending_settlement", "pending_assets"),
            ("pending_assets", "pending_payment"),
            ("pending_payment", "pending_documents"),
            ("pending_documents", "pending_tss"),
            ("pending_tss", "completed"),
        ]
        for current, next_state in pipeline:
            assert self.sm.can_transition(current, next_state), \
                f"Fallo: {current} → {next_state}"

    def test_pending_hr_to_pending_settlement_direct(self):
        assert self.sm.can_transition("pending_hr_approval", "pending_settlement") is True

    def test_pending_hr_to_approved_no_longer_direct(self):
        assert self.sm.can_transition("pending_hr_approval", "approved") is False

    def test_approved_to_pending_settlement(self):
        assert self.sm.can_transition("approved", "pending_settlement") is True

    def test_pending_hr_to_completed_blocked(self):
        assert self.sm.can_transition("pending_hr_approval", "completed") is False

    def test_cancel_from_any_non_terminal(self):
        non_terminal = [s for s in SM_STATES if s not in ("completed", "cancelled", "rejected")]
        for s in non_terminal:
            assert self.sm.can_transition(s, "cancelled"), \
                f"No se puede cancelar desde {s}"

    def test_reject_from_pending(self):
        assert self.sm.can_transition("pending_supervisor_approval", "rejected") is True
        assert self.sm.can_transition("pending_hr_approval", "rejected") is True

    def test_validate_transition_raises_on_invalid(self):
        with pytest.raises(ValueError, match="Transición inválida"):
            self.sm.validate_transition("draft", "completed", "offboarding")

    def test_for_offboarding_factory(self):
        sm = StateMachineValidator.for_offboarding()
        assert sm.can_transition("draft", "pending_supervisor_approval") is True


# ═══════════════════════════════════════════════════════════════════════════
# ESTADOS DEFINIDOS EN MODELOS (OFFBOARDING_STATES)
# ═══════════════════════════════════════════════════════════════════════════

class TestOffboardingStateDefinitions:
    def test_all_states_have_label_and_color(self):
        for key, cfg in OFFBOARDING_STATES.items():
            assert "label" in cfg, f"Estado {key} sin label"
            assert "color" in cfg, f"Estado {key} sin color"

    def test_all_states_have_transitions_list(self):
        for key, cfg in OFFBOARDING_STATES.items():
            assert isinstance(cfg["transitions"], list), f"Estado {key} transitions no es lista"

    def test_terminal_states_have_empty_transitions(self):
        for s in ("completed", "cancelled", "rejected"):
            assert OFFBOARDING_STATES[s]["transitions"] == []


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTES Y CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════

class TestOffboardingConstants:
    def test_default_checklist_has_tasks(self):
        assert len(DEFAULT_CHECKLIST_TASKS) > 0

    def test_default_checklist_includes_assets(self):
        categories = {t["category"] for t in DEFAULT_CHECKLIST_TASKS}
        assert "assets" in categories

    def test_termination_type_risk_map_has_all_types(self):
        for t in TerminationType:
            assert t in TERMINATION_TYPE_RISK_MAP, f"Falta riesgo para {t}"

    def test_all_enum_values_defined(self):
        assert len(TerminationType) >= 8
        assert len(TerminationStatus) >= 10
        assert len(SettlementStatus) >= 3

    def test_offboarding_states_sm_sync(self):
        """Los estados en OFFBOARDING_STATES (modelos) deben coincidir
        con OFFBOARDING_STATES (state_machine.py)."""
        model_keys = set(OFFBOARDING_STATES.keys())
        sm_keys = set(SM_STATES.keys())
        assert model_keys == sm_keys, \
            f"Diferencia: modelos={model_keys - sm_keys}, sm={sm_keys - model_keys}"


# ═══════════════════════════════════════════════════════════════════════════
# SOD (SEGREGATION OF DUTIES)
# ═══════════════════════════════════════════════════════════════════════════

class TestSODRules:
    def test_approval_record_has_all_fields(self):
        ar = ApprovalRecord(
            approverEmail="jefe@empresa.com",
            approverName="Jefe",
            role="supervisor",
            decision="approved",
            level=1,
        )
        assert ar.approverEmail == "jefe@empresa.com"
        assert ar.decision == "approved"

    def test_status_change_tracking(self):
        from app.models.offboarding import StatusChange
        sc = StatusChange(
            fromStatus="draft",
            toStatus="pending_supervisor_approval",
            changedBy="user@test.com",
            changedAt="2025-01-01T00:00:00Z",
        )
        assert sc.fromStatus == "draft"
        assert sc.toStatus == "pending_supervisor_approval"


# ═══════════════════════════════════════════════════════════════════════════
# TSS
# ═══════════════════════════════════════════════════════════════════════════

class TestTSSBajaFormat:
    def test_tss_file_starts_with_header(self):
        from app.services.offboarding_tss_service import generate_tss_baja
        content = generate_tss_baja(
            request_data={
                "effectiveDate": "2025-06-01",
                "terminationType": "renuncia_voluntaria",
            },
            employee={
                "firstName": "Juan",
                "middleName": "Carlos",
                "firstLastName": "Pérez",
                "secondLastName": "García",
                "cedula": "00123456789",
                "gender": "M",
                "birthDate": "1990-01-15",
                "tssKey": "001",
                "baseSalary": 45000,
            },
            company_rnc="123456789",
        )
        assert content.startswith("E")
        lines = content.strip().split("\n")
        assert len(lines) >= 2
        assert lines[1].startswith("D")

    def test_tss_filename_format(self):
        from app.services.offboarding_tss_service import get_tss_baja_filename
        filename = get_tss_baja_filename("123456789", "062025")
        assert filename.startswith("BA_")
        assert filename.endswith(".txt")

    def test_tss_detalle_length(self):
        from app.services.offboarding_tss_service import generate_tss_baja
        content = generate_tss_baja(
            request_data={"effectiveDate": "2025-06-01", "terminationType": "despido_injustificado"},
            employee={
                "firstName": "María", "middleName": "", "firstLastName": "López",
                "secondLastName": "", "cedula": "00123456789", "gender": "F",
                "birthDate": "1995-05-20", "tssKey": "002", "baseSalary": 60000,
            },
            company_rnc="987654321",
        )
        lines = content.strip().split("\n")
        detalle = lines[1]
        assert len(detalle) == 356, f"Longitud {len(detalle)} != 356 (esperado)"


# ═══════════════════════════════════════════════════════════════════════════
# GUARDAS (BUSINESS RULES)
# ═══════════════════════════════════════════════════════════════════════════

class TestOffboardingGuards:
    def test_access_revoked_at_field_exists(self):
        req = TerminationRequest()
        assert hasattr(req, "accessRevokedAt")
        assert req.accessRevokedAt is None

    def test_access_revoked_at_can_be_set(self):
        req = TerminationRequest(accessRevokedAt="2025-07-20T12:00:00Z")
        assert req.accessRevokedAt == "2025-07-20T12:00:00Z"

    def test_guard_assets_completed_no_checklist(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guard_assets_completed({"id": "x", "ownerUid": "test_uid", "sandbox": True})
        assert guard is not None
        assert "checklist" in guard.lower()

    def test_guard_tss_notified_missing(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guard_tss_notified({"id": "x"})
        assert guard is not None
        assert "TSS" in guard

    def test_guard_tss_notified_present(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guard_tss_notified({"id": "x", "tssNotifiedAt": "2025-07-20T12:00:00Z"})
        assert guard is None

    def test_guard_access_revoked_missing(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guard_access_revoked({"id": "x"})
        assert guard is not None
        assert "accesos" in guard.lower()

    def test_guard_access_revoked_present(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guard_access_revoked({"id": "x", "accessRevokedAt": "2025-07-20T12:00:00Z"})
        assert guard is None

    def test_check_guards_assets_to_payment(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guards("pending_assets", "pending_payment", {})
        assert guard is not None

    def test_check_guards_completed_needs_both(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guards("pending_tss", "completed",
                                   {"id": "x", "tssNotifiedAt": "2025-07-20T12:00:00Z"})
        assert guard is not None  # falta accessRevokedAt

    def test_check_guards_completed_passes_with_both(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guards("pending_tss", "completed", {
            "id": "x",
            "tssNotifiedAt": "2025-07-20T12:00:00Z",
            "accessRevokedAt": "2025-07-20T12:00:00Z",
        })
        assert guard is None

    def test_check_guards_other_transition_no_guard(self):
        from app.services.offboarding_service import OffboardingService
        svc = OffboardingService("test_uid", sandbox=True)
        guard = svc._check_guards("pending_settlement", "pending_assets", {})
        assert guard is None
