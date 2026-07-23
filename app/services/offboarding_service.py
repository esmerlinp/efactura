"""OffboardingService — Lógica de negocio, máquina de estados y SOD.

Dependencias:
  - OffboardingDataService para persistencia
  - StateMachineValidator para control de transiciones
  - PayrollAuditService para auditoría
"""

from datetime import datetime, timezone
from typing import Optional

from app.services.state_machine import StateMachineValidator, OFFBOARDING_STATES
from app.services.payroll_audit_service import log_action
from app.services import offboarding_data_service as ods
from app.models.offboarding import (
    TerminationRequest, TerminationSettlement, TerminationChecklist,
    TerminationDocument, TerminationPayment, TerminationInterview,
    TerminationRiskAssessment, TerminationLegalCase, RehireRequest,
    TerminationRequestVersion,
    TerminationStatus, SettlementStatus,
    StatusChange, ApprovalRecord,
    ChecklistItem, RiskFactor,
    OFFBOARDING_STATES as OFFBOARDING_STATES_DEF,
)


class OffboardingService:
    """Agregado root: TerminationRequest con sus 8 entidades satélite."""

    def __init__(self, company_id: str, sandbox: bool = True):
        self.company_id = company_id
        self.sandbox = sandbox
        self.sm = StateMachineValidator(OFFBOARDING_STATES)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── TerminationRequest CRUD ───────────────────────────────────────────

    def create_request(self, data: dict, user_email: str) -> TerminationRequest:
        req = TerminationRequest(**data)
        req.createdBy = user_email
        req.createdAt = self._now()
        req.updatedAt = self._now()
        req.ownerUid = self.company_id
        req.sandbox = self.sandbox

        if not req.requestNumber:
            req.requestNumber = f"OFF-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        req.statusHistory.append(StatusChange(
            toStatus=req.status.value,
            changedBy=user_email,
            changedAt=self._now(),
            comment="Creación de solicitud",
        ).model_dump())

        ods.save_request(req.id, req.model_dump(), self.company_id, self.sandbox)
        log_action(self.company_id, "offboarding_created", "offboarding", req.id,
                   user_email, {"employeeId": req.employeeId}, sandbox=self.sandbox)
        return req

    def get_request(self, request_id: str) -> Optional[dict]:
        return ods.get_request(request_id, self.company_id, self.sandbox)

    def list_requests(self, status: str = None, limit: int = 100) -> list[dict]:
        return ods.list_requests(self.company_id, self.sandbox, status=status, limit=limit)

    def save_request_raw(self, request_id: str, data: dict, user_email: str):
        data["updatedBy"] = user_email
        data["updatedAt"] = self._now()
        ods.save_request(request_id, data, self.company_id, self.sandbox)

    # ── State Machine ──────────────────────────────────────────────────────

    def _get_status_value(self, req: dict) -> str:
        s = req.get("status", "")
        return s.value if hasattr(s, "value") else s

    def _check_guard_assets_completed(self, req: dict) -> Optional[str]:
        checklist_id = req.get("checklistId")
        if not checklist_id:
            return "Debe inicializar el checklist antes de avanzar a pago"
        cl = self.get_checklist(checklist_id)
        if not cl:
            return "Checklist no encontrado"
        asset_items = [i for i in cl.get("items", [])
                       if i.get("category") == "assets"]
        if not asset_items:
            return None
        if not all(i.get("completed") for i in asset_items):
            pending = [i["task"] for i in asset_items if not i.get("completed")]
            return f"Debe completar la devolución de todos los activos antes del pago: {', '.join(pending)}"
        return None

    def _check_guard_tss_notified(self, req: dict) -> Optional[str]:
        if not req.get("tssNotifiedAt"):
            return "Debe descargar/generar la notificación TSS antes de completar la solicitud"
        return None

    def _check_guard_access_revoked(self, req: dict) -> Optional[str]:
        if not req.get("accessRevokedAt"):
            return "Debe desactivar los accesos del empleado antes de completar la solicitud"
        return None

    def transition(self, request_id: str, new_status: str,
                   user_email: str, user_role: str, comment: str = "") -> dict:
        req_data = self.get_request(request_id)
        if not req_data:
            raise ValueError(f"Solicitud {request_id} no encontrada")

        current = self._get_status_value(req_data)
        self.sm.validate_transition(current, new_status, "offboarding")

        allowed_check = self._check_sod(current, new_status, req_data, user_email, user_role)
        if allowed_check:
            raise ValueError(allowed_check)

        guard_check = self._check_guards(current, new_status, req_data)
        if guard_check:
            raise ValueError(guard_check)

        timestamp = self._now()
        old_status = current

        if current == "pending_hr_approval" and new_status == "pending_settlement":
            self._record_auto_approved(req_data, user_email, timestamp)

        req_data["status"] = new_status

        status_entry = StatusChange(
            fromStatus=old_status,
            toStatus=new_status,
            changedBy=user_email,
            changedAt=timestamp,
            comment=comment or f"Transición: {old_status} → {new_status}",
        ).model_dump()
        if "statusHistory" not in req_data or not isinstance(req_data.get("statusHistory"), list):
            req_data["statusHistory"] = []
        req_data["statusHistory"].append(status_entry)

        ts_map = {
            "pending_supervisor_approval": "submittedAt",
            "pending_hr_approval": "supervisorApprovedAt",
            "approved": "hrApprovedAt",
            "pending_settlement": "settlementApprovedAt",
            "pending_assets": "assetsReturnedAt",
            "pending_payment": "paidAt",
            "pending_documents": "documentsGeneratedAt",
            "pending_tss": "tssNotifiedAt",
            "completed": "closedAt",
        }
        if new_status in ts_map:
            req_data[ts_map[new_status]] = timestamp

        ods.save_request(request_id, req_data, self.company_id, self.sandbox)
        log_action(self.company_id, f"offboarding_{new_status}", "offboarding", request_id,
                   user_email, {"fromStatus": old_status, "toStatus": new_status}, sandbox=self.sandbox)

        if new_status == "completed":
            self._mark_employee_inactive(req_data)

        return req_data

    def _check_guards(self, current: str, new_status: str, req: dict) -> Optional[str]:
        if current == "pending_assets" and new_status == "pending_payment":
            return self._check_guard_assets_completed(req)
        if new_status == "completed":
            guard = self._check_guard_tss_notified(req)
            if guard:
                return guard
            return self._check_guard_access_revoked(req)
        return None

    def _record_auto_approved(self, req_data: dict, user_email: str, timestamp: str):
        req_data["status"] = "approved"
        approved_entry = StatusChange(
            fromStatus="pending_hr_approval",
            toStatus="approved",
            changedBy=user_email,
            changedAt=timestamp,
            comment="Aprobación automática por RRHH",
            source="system",
        ).model_dump()
        if "statusHistory" not in req_data or not isinstance(req_data.get("statusHistory"), list):
            req_data["statusHistory"] = []
        req_data["statusHistory"].append(approved_entry)
        req_data["hrApprovedAt"] = timestamp
        log_action(self.company_id, "offboarding_approved", "offboarding",
                   req_data.get("id", ""), user_email,
                   {"fromStatus": "pending_hr_approval", "toStatus": "approved"},
                   sandbox=self.sandbox)

    def can_transition(self, current_status: str, new_status: str) -> bool:
        return self.sm.can_transition(current_status, new_status)

    def allowed_transitions(self, current_status: str) -> list:
        allowed = self.sm.get_allowed_transitions(current_status)
        if current_status == "pending_hr_approval":
            allowed = [t for t in allowed if t != "approved"]
        return allowed

    # ── Mark Employee Inactive ───────────────────────────────────────────────

    def _mark_employee_inactive(self, req_data: dict):
        employee_id = req_data.get("employeeId", "")
        if not employee_id:
            return
        try:
            from app.services import hr_data_service as hr
            emp = hr.get_employee(self.company_id, employee_id, sandbox=self.sandbox)
            if emp and emp.get("status") != "inactivo":
                emp["status"] = "inactivo"
                emp["terminationDate"] = req_data.get("effectiveDate", "")
                emp["terminationType"] = req_data.get("terminationType", "")
                hr.save_employee(self.company_id, employee_id, emp, sandbox=self.sandbox)
                log_action(self.company_id, "employee_marked_inactive", "employee",
                           employee_id, "system",
                           {"offboardingId": req_data.get("id", ""),
                            "terminationType": req_data.get("terminationType", "")},
                           sandbox=self.sandbox)
        except Exception as e:
            print(f"⚠️ Offboarding._mark_employee_inactive: {e}")

    # ── Access Revocation ────────────────────────────────────────────────────

    def revoke_access(self, request_id: str, user_email: str, revoke: bool = True) -> dict:
        req_data = self.get_request(request_id)
        if not req_data:
            raise ValueError(f"Solicitud {request_id} no encontrada")
        if revoke:
            req_data["accessRevokedAt"] = self._now()
        else:
            req_data["accessRevokedAt"] = None
        req_data["accessRevokedBy"] = user_email if revoke else None
        self.save_request_raw(request_id, req_data, user_email)
        log_action(self.company_id, "offboarding_access_revoked" if revoke else "offboarding_access_restored",
                   "offboarding", request_id, user_email,
                   {"employeeId": req_data.get("employeeId", "")}, sandbox=self.sandbox)
        return req_data

    # ── SOD Rules ───────────────────────────────────────────────────────────

    def _check_sod(self, current: str, new_status: str, req: dict,
                   user_email: str, user_role: str) -> Optional[str]:
        if user_role == "owner":
            return None
        if current == "draft" and new_status == "pending_supervisor_approval":
            if req.get("createdBy") == user_email:
                return "El creador no puede aprobar su propia solicitud"
        if new_status == "pending_hr_approval":
            if req.get("createdBy") == user_email:
                return "El creador no puede aprobar su propia solicitud"
        if new_status == "pending_payment":
            calc_by = req.get("settlementCalculatedBy", "")
            if calc_by == user_email:
                return "El calculador de liquidación no puede aprobar el pago"
        return None

    # ── Approval Workflow ───────────────────────────────────────────────────

    def add_approval(self, request_id: str, approver_email: str, approver_name: str,
                     role: str, decision: str, comment: str = "", level: int = 1) -> dict:
        req_data = self.get_request(request_id)
        if not req_data:
            raise ValueError(f"Solicitud {request_id} no encontrada")

        approval = ApprovalRecord(
            approverEmail=approver_email,
            approverName=approver_name,
            role=role,
            decision=decision,
            comment=comment,
            decidedAt=self._now(),
            level=level,
        ).model_dump()

        if "approvalHistory" not in req_data or not isinstance(req_data.get("approvalHistory"), list):
            req_data["approvalHistory"] = []
        req_data["approvalHistory"].append(approval)
        ods.save_request(request_id, req_data, self.company_id, self.sandbox)
        return req_data

    # ── Settlement ─────────────────────────────────────────────────────────

    def save_settlement(self, data: dict, user_email: str) -> str:
        settlement = TerminationSettlement(**data)
        settlement.calculatedBy = user_email
        settlement.calculatedAt = self._now()
        settlement.createdAt = self._now()
        ods.save("offboarding_settlements", settlement.id, settlement.model_dump(),
                 self.company_id, self.sandbox)

        if settlement.requestId:
            req_data = self.get_request(settlement.requestId)
            if req_data:
                req_data["settlementId"] = settlement.id
                req_data["settlementCalculatedBy"] = user_email
                req_data["settlementCalculatedAt"] = self._now()
                self.save_request_raw(settlement.requestId, req_data, user_email)

        log_action(self.company_id, "settlement_calculated", "offboarding_settlement",
                   settlement.id, user_email, {"requestId": settlement.requestId},
                   sandbox=self.sandbox)
        return settlement.id

    def get_settlement(self, settlement_id: str) -> Optional[dict]:
        return ods.get_one("offboarding_settlements", settlement_id, self.company_id, self.sandbox)

    def approve_settlement(self, settlement_id: str, approved_by: str,
                           comment: str = "") -> dict:
        settlement = self.get_settlement(settlement_id)
        if not settlement:
            raise ValueError(f"Liquidación {settlement_id} no encontrada")
        settlement["status"] = SettlementStatus.APROBADA.value
        settlement["approvedBy"] = approved_by
        settlement["approvedAt"] = self._now()
        settlement["approvalComment"] = comment
        ods.save("offboarding_settlements", settlement_id, settlement,
                 self.company_id, self.sandbox)
        log_action(self.company_id, "settlement_approved", "offboarding_settlement",
                   settlement_id, approved_by, sandbox=self.sandbox)
        return settlement

    # ── Checklist ──────────────────────────────────────────────────────────

    def init_checklist(self, request_id: str, employee_id: str) -> str:
        from app.models.offboarding import DEFAULT_CHECKLIST_TASKS
        from app.services.herramientas_service import get_asignaciones_por_empleado
        items = []
        non_asset_tasks = [t for t in DEFAULT_CHECKLIST_TASKS
                           if getattr(t["category"], "value", t["category"]) != "assets"]
        for t in non_asset_tasks:
            items.append(ChecklistItem(
                task=t["task"],
                category=t["category"].value if hasattr(t["category"], "value") else t["category"],
                isMandatory=t["isMandatory"],
            ).model_dump())
        active_assignments = get_asignaciones_por_empleado(
            self.company_id, employee_id, sandbox=self.sandbox
        )
        active_assignments = [a for a in active_assignments if a.get("status") == "activa"]
        for a in active_assignments:
            h_name = a.get("herramientaName", "")
            h_code = a.get("herramientaCode", "")
            items.append(ChecklistItem(
                task=f"Devolver {h_name}",
                category="assets",
                isMandatory=True,
                assignedAssetId=a.get("id", ""),
                description=f"{h_name} ({h_code})",
            ).model_dump())
        checklist = TerminationChecklist(
            requestId=request_id,
            employeeId=employee_id,
            items=items,
            totalItems=len(items),
            completedItems=0,
            allCompleted=False,
        )
        ods.save("offboarding_checklists", checklist.id, checklist.model_dump(),
                 self.company_id, self.sandbox)

        req_data = self.get_request(request_id)
        if req_data:
            req_data["checklistId"] = checklist.id
            self.save_request_raw(request_id, req_data, "system")
        return checklist.id

    def get_checklist(self, checklist_id: str) -> Optional[dict]:
        return ods.get_one("offboarding_checklists", checklist_id, self.company_id, self.sandbox)

    def update_checklist_item(self, checklist_id: str, item_id: str,
                              updates: dict, user_email: str) -> dict:
        checklist = self.get_checklist(checklist_id)
        if not checklist:
            raise ValueError(f"Checklist {checklist_id} no encontrado")
        for item in checklist.get("items", []):
            if item.get("id") == item_id:
                item.update(updates)
                was_completed = item.get("completed", False)
                if updates.get("completed") and not was_completed:
                    item["completedBy"] = user_email
                    item["completedAt"] = self._now()
                    self._sync_asset_return(checklist, item)
                break
        completed = sum(1 for i in checklist.get("items", []) if i.get("completed"))
        checklist["completedItems"] = completed
        checklist["allCompleted"] = completed >= checklist.get("totalItems", 0)
        ods.save("offboarding_checklists", checklist_id, checklist,
                 self.company_id, self.sandbox)
        return checklist

    def _sync_asset_return(self, checklist: dict, item: dict):
        assigned_id = item.get("assignedAssetId", "")
        if not assigned_id:
            return
        try:
            from app.services.herramientas_service import (
                get_asignaciones_por_empleado, save_asignacion,
                get_herramienta, save_herramienta,
            )
            req = self.get_request(checklist.get("requestId", ""))
            if not req:
                return
            emp_id = req.get("employeeId", "")
            assigns = get_asignaciones_por_empleado(
                self.company_id, emp_id, sandbox=self.sandbox
            )
            for a in assigns:
                if a.get("id") == assigned_id:
                    a["returnedDate"] = self._now()
                    a["status"] = "devuelta"
                    a["conditionOnReturn"] = item.get("notes", "")
                    save_asignacion(self.company_id, assigned_id, a, sandbox=self.sandbox)
                    h_id = a.get("herramientaId", "")
                    if h_id:
                        h = get_herramienta(self.company_id, h_id, sandbox=self.sandbox)
                        if h:
                            h["assignmentStatus"] = "disponible"
                            save_herramienta(self.company_id, h_id, h, sandbox=self.sandbox)
                    break
        except Exception as e:
            print(f"⚠️ Offboarding._sync_asset_return: {e}")

    # ── Document ───────────────────────────────────────────────────────────

    def save_document(self, data: dict, user_email: str) -> str:
        doc = TerminationDocument(**data)
        doc.generatedBy = user_email
        doc.generatedAt = self._now()
        ods.save("offboarding_documents", doc.id, doc.model_dump(),
                 self.company_id, self.sandbox)
        return doc.id

    def get_documents(self, request_id: str) -> list[dict]:
        return ods.get_all("offboarding_documents", self.company_id, self.sandbox,
                           where_filters=[("requestId", "==", request_id)])

    # ── Payment ────────────────────────────────────────────────────────────

    def save_payment(self, data: dict, user_email: str) -> str:
        payment = TerminationPayment(**data)
        payment.paidBy = user_email
        payment.paidAt = self._now()
        ods.save("offboarding_payments", payment.id, payment.model_dump(),
                 self.company_id, self.sandbox)
        log_action(self.company_id, "payment_registered", "offboarding_payment",
                   payment.id, user_email, {"requestId": payment.requestId},
                   sandbox=self.sandbox)
        return payment.id

    def get_payments(self, request_id: str) -> list[dict]:
        return ods.get_all("offboarding_payments", self.company_id, self.sandbox,
                           where_filters=[("requestId", "==", request_id)])

    # ── Interview ──────────────────────────────────────────────────────────

    def save_interview(self, data: dict, user_email: str) -> str:
        interview = TerminationInterview(**data)
        interview.createdBy = user_email
        interview.createdAt = self._now()
        ods.save("offboarding_interviews", interview.id, interview.model_dump(),
                 self.company_id, self.sandbox)
        return interview.id

    def get_interviews(self, request_id: str) -> list[dict]:
        return ods.get_all("offboarding_interviews", self.company_id, self.sandbox,
                           where_filters=[("requestId", "==", request_id)])

    # ── Risk Assessment ────────────────────────────────────────────────────

    def save_risk_assessment(self, data: dict, user_email: str) -> str:
        ra = TerminationRiskAssessment(**data)
        ra.assessedBy = user_email
        ra.assessedAt = self._now()
        ods.save("offboarding_risk_assessments", ra.id, ra.model_dump(),
                 self.company_id, self.sandbox)
        return ra.id

    def get_risk_assessment(self, ra_id: str) -> Optional[dict]:
        return ods.get_one("offboarding_risk_assessments", ra_id, self.company_id, self.sandbox)

    # ── Legal Case ─────────────────────────────────────────────────────────

    def save_legal_case(self, data: dict, user_email: str) -> str:
        lc = TerminationLegalCase(**data)
        lc.createdBy = user_email
        lc.createdAt = self._now()
        ods.save("offboarding_legal_cases", lc.id, lc.model_dump(),
                 self.company_id, self.sandbox)
        return lc.id

    def get_legal_case(self, lc_id: str) -> Optional[dict]:
        return ods.get_one("offboarding_legal_cases", lc_id, self.company_id, self.sandbox)

    # ── Rehire ─────────────────────────────────────────────────────────────

    def save_rehire(self, data: dict, user_email: str) -> str:
        rh = RehireRequest(**data)
        rh.createdBy = user_email
        rh.createdAt = self._now()
        ods.save("offboarding_rehire_requests", rh.id, rh.model_dump(),
                 self.company_id, self.sandbox)
        return rh.id

    # ── Versioning ─────────────────────────────────────────────────────────

    def save_version(self, request_id: str, snapshot: dict, user_email: str,
                     reason: str = "") -> str:
        req = self.get_request(request_id)
        version = req.get("version", 1) if req else 1
        v = TerminationRequestVersion(
            requestId=request_id,
            version=version + 1,
            snapshot=snapshot,
            changedBy=user_email,
            changedAt=self._now(),
            changeReason=reason,
        )
        ods.save("offboarding_versions", v.id, v.model_dump(),
                 self.company_id, self.sandbox)
        if req:
            req["version"] = version + 1
            self.save_request_raw(request_id, req, user_email)
        return v.id
