"""EmployeeStatusService — Motor de estados transitorios del empleado.

Gestiona las transiciones automáticas activo ⇄ vacaciones ⇄ licencia a partir
de las solicitudes aprobadas de vacaciones y licencias:

- Al iniciar una solicitud aprobada (startDate <= hoy <= endDate) el empleado
  pasa a "vacaciones" o "licencia" (la licencia tiene prioridad).
- Al terminar (o anular/revocar) la solicitud vigente, vuelve a "activo".
- Si se aprueba una licencia que se solapa con vacaciones aprobadas, la
  vacación se revoca automáticamente devolviendo los días no consumidos.
- Anular una vacación a mitad de curso solo descuenta los días hábiles
  realmente tomados y devuelve el resto al balance disponible.

Todos los cambios quedan registrados en `employee_status_events` y en el
log global de auditoría (`payroll_audit_service.log_action`).

El servicio es idempotente: puede ejecutarse tantas veces como sea necesario
(diario vía APScheduler y/o al abrir listas/fichas) sin efectos duplicados.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from app.services import hr_data_service as hr
from app.utils.hr_utils import ACTIVE_EQUIVALENT_STATUSES


class EmployeeStatusService:
    """Motor de estados transitorios (vacaciones/licencia) del empleado."""

    # ═══════════════════════════════════════════════════════════════════════
    # Helpers de fechas y consultas
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _today() -> date:
        return date.today()

    @staticmethod
    def _parse_date(value) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    @classmethod
    def _in_range(cls, req: dict, today: date) -> bool:
        start = cls._parse_date(req.get("startDate", ""))
        end = cls._parse_date(req.get("endDate", "")) or start
        if not start:
            return False
        return start <= today <= end

    @staticmethod
    def _ranges_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
        try:
            s1 = datetime.strptime(str(start1)[:10], "%Y-%m-%d").date()
            e1 = datetime.strptime(str(end1)[:10], "%Y-%m-%d").date()
            s2 = datetime.strptime(str(start2)[:10], "%Y-%m-%d").date()
            e2 = datetime.strptime(str(end2)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return False
        return s1 <= e2 and s2 <= e1

    @staticmethod
    def _business_days(company_id: str, start: date, end: date, sandbox: bool) -> int:
        if not start or not end or start > end:
            return 0
        from app.services.holiday_service import HolidayService
        from app.services.payroll_service import PayrollService
        try:
            holidays = HolidayService.get_holiday_dates(
                company_id, start.isoformat(), end.isoformat(), sandbox=sandbox)
        except Exception:
            holidays = set()
        return PayrollService.calculate_business_days(
            start.isoformat(), end.isoformat(), holidays=holidays)

    @staticmethod
    def _approved_vacations_for(company_id: str, employee_id: str, sandbox: bool) -> list:
        return [
            r for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
            if r.get("employeeId") == employee_id and r.get("status") == "aprobada"
        ]

    @staticmethod
    def _approved_leaves_for(company_id: str, employee_id: str, sandbox: bool) -> list:
        return [
            r for r in hr.get_leave_requests(company_id, sandbox=sandbox)
            if r.get("employeeId") == employee_id and r.get("status") == "aprobada"
        ]

    # ═══════════════════════════════════════════════════════════════════════
    # Días disponibles
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def taken_vacation_days(requests: list) -> int:
        """Días efectivamente descontados del balance:
        - aprobada  → días completos de la solicitud
        - anulada/revocada → solo los días realmente consumidos (consumedDays)
        """
        total = 0
        for r in requests or []:
            status = r.get("status", "")
            if status == "aprobada":
                total += int(r.get("days", 0) or 0)
            elif status in ("anulada", "revocada"):
                total += int(r.get("consumedDays", 0) or 0)
        return total

    # ═══════════════════════════════════════════════════════════════════════
    # Registro de eventos e historial
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def _log_event(cls, company_id: str, employee: dict, from_status: str,
                   to_status: str, trigger: str, request_id: str, actor: str,
                   reason: str, sandbox: bool):
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        event = {
            "id": event_id,
            "employeeId": employee.get("id", ""),
            "employeeName": employee.get("fullName", ""),
            "fromStatus": from_status,
            "toStatus": to_status,
            "trigger": trigger,
            "requestId": request_id or "",
            "actor": actor or "Sistema",
            "reason": reason or "",
            "date": cls._today().isoformat(),
            "timestamp": now,
        }
        hr.save_employee_status_event(company_id, event_id, event, sandbox=sandbox)

        from app.services.payroll_audit_service import log_action
        try:
            log_action(
                company_id,
                f"employee_status_{to_status if to_status != from_status else trigger}",
                "employee",
                employee.get("id", ""),
                actor or "Sistema",
                changes={
                    "from": from_status, "to": to_status,
                    "trigger": trigger, "requestId": request_id or "",
                },
                comment=reason or "",
                sandbox=sandbox,
            )
        except Exception as e:
            print(f"⚠️ EmployeeStatusService._log_event → log_action: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # Transición de estado
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def _transition(cls, company_id: str, employee: dict, to_status: str,
                    trigger: str, request_id: str, actor: str, reason: str,
                    sandbox: bool) -> dict:
        from_status = employee.get("status", "activo")
        employee["status"] = to_status
        hr.save_employee(company_id, employee.get("id", ""), employee, sandbox=sandbox)
        cls._log_event(company_id, employee, from_status, to_status, trigger,
                       request_id, actor, reason, sandbox)
        return {
            "employeeId": employee.get("id", ""),
            "from": from_status,
            "to": to_status,
            "trigger": trigger,
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Sincronización (idempotente)
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def sync_employee(cls, company_id: str, employee_id: str, sandbox: bool = True,
                      today: date | None = None, actor: str = "Sistema") -> dict | None:
        """Sincroniza el estado de UN empleado con sus solicitudes vigentes.

        Reglas:
        - inactivo/suspendido nunca se toca.
        - licencia aprobada vigente → "licencia" (y revoca vacaciones solapadas).
        - vacaciones aprobadas vigentes → "vacaciones".
        - sin solicitud vigente → "activo".
        """
        if today is None:
            today = cls._today()
        employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
        if not employee:
            return None

        current = employee.get("status", "activo")
        if current not in ACTIVE_EQUIVALENT_STATUSES:
            # inactivo / suspendido / desconocido: no transicionar
            return None

        vacations = cls._approved_vacations_for(company_id, employee_id, sandbox)
        leaves = cls._approved_leaves_for(company_id, employee_id, sandbox)
        vac_active = next((v for v in vacations if cls._in_range(v, today)), None)
        leave_active = next((l for l in leaves if cls._in_range(l, today)), None)

        # Regla: la licencia gana — revocar vacación solapada vigente
        if leave_active and vac_active:
            cls.revoke_vacation_for_leave(company_id, vac_active, leave_active,
                                          actor=actor, sandbox=sandbox)
            vac_active = None

        if leave_active:
            target, trigger = "licencia", "leave_start"
            req = leave_active
            reason = f"Licencia {leave_active.get('leaveType', '')} del " \
                     f"{leave_active.get('startDate', '')} al {leave_active.get('endDate', '')}"
        elif vac_active:
            target, trigger = "vacaciones", "vacation_start"
            req = vac_active
            reason = f"Vacaciones del {vac_active.get('startDate', '')} al {vac_active.get('endDate', '')}"
        else:
            target, trigger, req = "activo", "", None
            if current == "vacaciones":
                trigger = "vacation_end"
            elif current == "licencia":
                trigger = "leave_end"
            else:
                return None
            reason = "Fin de la solicitud vigente — retorno automático a activo"

        if current == target:
            return None

        return cls._transition(company_id, employee, target, trigger,
                               req.get("id", "") if req else "",
                               actor, reason, sandbox)

    @classmethod
    def sync_employee_statuses(cls, company_id: str, sandbox: bool = True,
                               today: date | None = None,
                               actor: str = "Sistema (APScheduler)") -> list:
        """Barrido completo de todos los empleados de la empresa."""
        if today is None:
            today = cls._today()
        transitions = []
        for emp in hr.get_employees(company_id, sandbox=sandbox):
            try:
                res = cls.sync_employee(company_id, emp.get("id", ""),
                                        sandbox=sandbox, today=today,
                                        actor=actor)
                if res:
                    transitions.append(res)
            except Exception as e:
                print(f"⚠️ EmployeeStatusService.sync_employee_statuses"
                      f"({emp.get('id')}): {e}")
        return transitions

    # ═══════════════════════════════════════════════════════════════════════
    # Anulación y revocación de vacaciones
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def cancel_vacation_request(cls, company_id: str, request_id: str,
                                cancel_date: str = "", actor: str = "",
                                reason: str = "", sandbox: bool = True,
                                today: date | None = None) -> dict:
        """Anula una solicitud de vacaciones aprobada.

        - Si la fecha de anulación es anterior al inicio → reembolso total.
        - Si es a mitad del período → solo se descuentan los días hábiles
          realmente tomados (desde startDate hasta min(cancelDate, endDate))
          y el resto se devuelve al balance disponible.
        - No se puede anular una solicitud ya concluida (endDate en el pasado).
        """
        req = hr.get_vacation_request(company_id, request_id, sandbox=sandbox)
        if not req:
            return {"success": False, "error": "Solicitud no encontrada."}
        if req.get("status") != "aprobada":
            return {"success": False,
                    "error": "Solo se pueden anular solicitudes aprobadas."}

        today = today or cls._today()
        end = cls._parse_date(req.get("endDate", ""))
        if end and end < today:
            return {"success": False,
                    "error": "La solicitud ya concluyó y no puede anularse."}

        cd = cls._parse_date(cancel_date) if cancel_date else today
        if cd is None:
            return {"success": False, "error": "Fecha de anulación inválida."}
        start = cls._parse_date(req.get("startDate", ""))
        end = end or start
        if not start:
            return {"success": False, "error": "La solicitud no tiene fecha de inicio."}

        original_days = int(req.get("days", 0) or 0)
        if cd < start:
            consumed = 0
        else:
            last_taken = min(cd, end)
            consumed = cls._business_days(company_id, start, last_taken, sandbox)
        consumed = min(consumed, original_days)
        refunded = max(0, original_days - consumed)

        req["status"] = "anulada"
        req["consumedDays"] = consumed
        req["refundedDays"] = refunded
        req["cancelDate"] = cd.isoformat()
        req["cancelledAt"] = datetime.now(timezone.utc).isoformat()
        req["cancelledBy"] = actor or "Sistema"
        req["cancelReason"] = reason or "Anulada por RRHH"
        hr.save_vacation_request(company_id, request_id, req, sandbox=sandbox)

        employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
        if employee:
            cls._log_event(
                company_id, employee, employee.get("status", ""),
                employee.get("status", ""), "vacation_cancelled", request_id,
                actor,
                f"Anulación: {consumed} día(s) consumido(s), {refunded} devuelto(s).",
                sandbox)
            cls.sync_employee(company_id, employee.get("id", ""),
                              sandbox=sandbox, actor=actor or "Sistema")

        return {"success": True, "consumedDays": consumed, "refundedDays": refunded}

    @classmethod
    def revoke_vacation_for_leave(cls, company_id: str, vac_req: dict,
                                  leave_req: dict, actor: str = "Sistema",
                                  sandbox: bool = True) -> dict:
        """Revoca una vacación aprobada porque se aprobó una licencia solapada.

        Solo se descuentan los días hábiles tomados hasta el inicio de la
        licencia; el resto vuelve al balance disponible.
        """
        if vac_req.get("status") != "aprobada":
            return {"success": False, "error": "La vacación no está aprobada."}

        leave_start = cls._parse_date(leave_req.get("startDate", ""))
        vac_start = cls._parse_date(vac_req.get("startDate", ""))
        vac_end = cls._parse_date(vac_req.get("endDate", "")) or vac_start
        if not leave_start or not vac_start:
            return {"success": False, "error": "Fechas inválidas."}

        original_days = int(vac_req.get("days", 0) or 0)
        if leave_start <= vac_start:
            consumed = 0
        else:
            last_taken = min(leave_start - timedelta(days=1), vac_end)
            consumed = cls._business_days(company_id, vac_start, last_taken, sandbox)
        consumed = min(consumed, original_days)
        refunded = max(0, original_days - consumed)

        vac_req["status"] = "revocada"
        vac_req["consumedDays"] = consumed
        vac_req["refundedDays"] = refunded
        vac_req["revokedAt"] = datetime.now(timezone.utc).isoformat()
        vac_req["revokedBy"] = actor or "Sistema"
        vac_req["revokedByLeaveId"] = leave_req.get("id", "")
        vac_req["revokeReason"] = ("Revocada automáticamente: licencia aprobada "
                                   "durante las vacaciones.")
        hr.save_vacation_request(company_id, vac_req.get("id", ""), vac_req,
                                 sandbox=sandbox)

        employee = hr.get_employee(company_id, vac_req.get("employeeId", ""),
                                   sandbox=sandbox)
        if employee:
            cls._log_event(
                company_id, employee, employee.get("status", ""),
                employee.get("status", ""), "vacation_revoked",
                vac_req.get("id", ""), actor,
                f"Revocada por licencia {leave_req.get('id', '')}: "
                f"{consumed} día(s) consumido(s), {refunded} devuelto(s).",
                sandbox)

        return {"success": True, "consumedDays": consumed, "refundedDays": refunded}

    @classmethod
    def revoke_overlapping_vacations(cls, company_id: str, leave_req: dict,
                                     actor: str = "Sistema",
                                     sandbox: bool = True) -> list:
        """Revoca todas las vacaciones aprobadas que se solapen con una licencia."""
        emp_id = leave_req.get("employeeId", "")
        leave_start = leave_req.get("startDate", "")
        leave_end = leave_req.get("endDate", "")
        revoked = []
        for vac in cls._approved_vacations_for(company_id, emp_id, sandbox):
            if cls._ranges_overlap(vac.get("startDate", ""), vac.get("endDate", ""),
                                   leave_start, leave_end):
                res = cls.revoke_vacation_for_leave(company_id, vac, leave_req,
                                                    actor=actor, sandbox=sandbox)
                revoked.append({"requestId": vac.get("id", ""), **res})
        return revoked

    # ═══════════════════════════════════════════════════════════════════════
    # Consultas para UI
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def get_active_requests(cls, company_id: str, employee_id: str,
                            sandbox: bool = True, today: date | None = None) -> dict:
        """Solicitudes aprobadas vigentes hoy (para badges de la ficha)."""
        if today is None:
            today = cls._today()
        vacations = cls._approved_vacations_for(company_id, employee_id, sandbox)
        leaves = cls._approved_leaves_for(company_id, employee_id, sandbox)
        return {
            "vacation": next((v for v in vacations if cls._in_range(v, today)), None),
            "leave": next((l for l in leaves if cls._in_range(l, today)), None),
        }

    @classmethod
    def request_is_in_progress(cls, req: dict, today: date | None = None) -> bool:
        """True si una solicitud aprobada está en curso hoy."""
        if not req or req.get("status") != "aprobada":
            return False
        return cls._in_range(req, today or cls._today())
