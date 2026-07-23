"""OvertimeService — Gestión de Horas Extras.

Responsabilidades:
  - CRUD de registros de horas extras.
  - Flujo de estados (draft, pending, approved, locked, processed, reopened).
  - Congelamiento de valores al aprobar (hourlyRateAtApproval, factorAtApproval).
  - Vinculación con autorizaciones (authorizationId).
  - Marcar como procesadas al integrarse con nómina.
  - Prevención de duplicidad de procesamiento.

No hace cálculos monetarios — delega en PayrollOvertimeCalculator.
"""

from datetime import datetime, timezone
from typing import Optional

from app.models.overtime import OvertimeRecord, OvertimePayrollLink
from app.services import hr_data_service as hr
from app.services.payroll_overtime_calculator import PayrollOvertimeCalculator


class OvertimeService:
    """Operaciones de negocio sobre Horas Extras."""

    # ── Estados válidos ──
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    LOCKED = "locked"
    PROCESSED = "processed"
    REOPENED = "reopened"
    REJECTED = "rejected"

    VALID_TRANSITIONS = {
        DRAFT:     [PENDING, REJECTED],
        PENDING:   [APPROVED, REJECTED],
        APPROVED:  [LOCKED, REOPENED],
        LOCKED:    [PROCESSED, APPROVED],
        PROCESSED: [REOPENED],
        REOPENED:  [DRAFT],
        REJECTED:  [DRAFT],
    }

    # ── Helper ──

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _next_number(company_id: str, sandbox: bool) -> str:
        """Genera el siguiente número visible HE-XXXXXX."""
        records = hr.get_overtime_records(company_id, sandbox=sandbox)
        max_num = 0
        for r in records:
            num_str = r.get("number", "")
            if num_str.startswith("HE-"):
                try:
                    n = int(num_str[3:])
                    if n > max_num:
                        max_num = n
                except ValueError:
                    pass
        return f"HE-{max_num + 1:06d}"

    @staticmethod
    def can_transition(current: str, next_status: str) -> bool:
        return next_status in OvertimeService.VALID_TRANSITIONS.get(current, [])

    # ── CRUD ──

    @staticmethod
    def create_record(company_id: str, data: dict, user_email: str,
                       sandbox: bool = True) -> dict:
        """Crea un nuevo registro de hora extra en estado draft."""
        from uuid import uuid4
        now = OvertimeService._now_iso()
        record_id = str(uuid4())
        number = OvertimeService._next_number(company_id, sandbox)

        record = {
            "id": record_id,
            "number": number,
            "employeeId": data.get("employeeId", ""),
            "employeeSnapshot": {
                "code": data.get("employeeCode", ""),
                "name": data.get("employeeName", ""),
            },
            "companyCode": data.get("companyCode", ""),
            "departmentCode": data.get("departmentCode", ""),
            "payrollCode": data.get("payrollCode", ""),
            "date": data.get("date", ""),
            "overtimeTypeCode": data.get("overtimeTypeCode", ""),
            "totalMinutes": data.get("totalMinutes", 0),
            "comment": data.get("comment", ""),
            "source": data.get("source", "manual"),
            "sourceReference": data.get("sourceReference", ""),
            "status": OvertimeService.DRAFT,
            "authorizationId": "",
            "registeredBy": user_email,
            "registeredAt": now,
            "approvedBy": "",
            "approvedAt": None,
            "hourlyRateAtApproval": 0.0,
            "factorAtApproval": 0.0,
            "processedPayrollId": "",
            "processedAt": None,
            "statusHistory": [{"status": OvertimeService.DRAFT, "by": user_email,
                               "at": now, "comment": "Creado"}],
            "details": data.get("details", []),
        }

        hr.save_overtime_record(company_id, record_id, record, sandbox=sandbox)
        return record

    @staticmethod
    def get_record(company_id: str, record_id: str,
                    sandbox: bool = True) -> dict | None:
        return hr.get_overtime_record(company_id, record_id, sandbox=sandbox)

    @staticmethod
    def list_records(company_id: str, sandbox: bool = True) -> list:
        return hr.get_overtime_records(company_id, sandbox=sandbox)

    @staticmethod
    def list_by_status(company_id: str, status: str,
                        sandbox: bool = True) -> list:
        return hr.get_overtime_records_by_status(company_id, status, sandbox=sandbox)

    # ── Flujo de estados ──

    @staticmethod
    def _transition(company_id: str, record_id: str, new_status: str,
                    user_email: str, comment: str = "",
                    extra: Optional[dict] = None,
                    sandbox: bool = True) -> dict | tuple:
        """Ejecuta una transición de estado con validación y auditoría."""
        record = hr.get_overtime_record(company_id, record_id, sandbox=sandbox)
        if not record:
            return {"error": "Registro no encontrado."}, 404

        current = record.get("status", "")
        if not OvertimeService.can_transition(current, new_status):
            return {"error": f"Transición inválida: {current} → {new_status}"}, 400

        now = OvertimeService._now_iso()
        history = record.get("statusHistory", [])
        history.append({
            "status": new_status,
            "by": user_email,
            "at": now,
            "comment": comment or f"Cambió a {new_status}",
        })

        record["status"] = new_status
        record["statusHistory"] = history

        if extra:
            record.update(extra)

        hr.save_overtime_record(company_id, record_id, record, sandbox=sandbox)
        return record

    @staticmethod
    def submit_for_approval(company_id: str, record_id: str,
                             user_email: str, sandbox: bool = True) -> dict | tuple:
        """Envía a aprobación (draft → pending). Calcula y congela hourlyRate."""
        record = hr.get_overtime_record(company_id, record_id, sandbox=sandbox)
        if not record:
            return {"error": "Registro no encontrado."}, 404

        if record.get("status") != OvertimeService.DRAFT:
            return {"error": "Solo registros en borrador pueden enviarse a aprobación."}, 400

        emp = hr.get_employee(company_id, record.get("employeeId", ""), sandbox=sandbox)
        if not emp:
            return {"error": "Empleado no encontrado."}, 400

        base_salary = float(emp.get("baseSalary", emp.get("salary", 0)))
        hourly_rate = PayrollOvertimeCalculator.calculate_hourly_rate(base_salary)

        # Obtener factor desde el tipo de HE
        otype = hr.get_overtime_type(company_id, record.get("overtimeTypeCode", ""), sandbox=sandbox)
        factor = float(otype.get("factor", 1.35)) if otype else 1.35

        extra = {
            "hourlyRateAtApproval": hourly_rate,
            "factorAtApproval": factor,
        }

        return OvertimeService._transition(
            company_id, record_id, OvertimeService.PENDING,
            user_email, "Enviado a aprobación", extra, sandbox=sandbox,
        )

    @staticmethod
    def approve(company_id: str, record_id: str, user_email: str,
                 authorization_id: str = "", sandbox: bool = True) -> dict | tuple:
        """Aprueba el registro (pending → approved)."""
        record = hr.get_overtime_record(company_id, record_id, sandbox=sandbox)
        if not record:
            return {"error": "Registro no encontrado."}, 404

        if record.get("status") != OvertimeService.PENDING:
            return {"error": "Solo registros pendientes pueden aprobarse."}, 400

        now = OvertimeService._now_iso()
        extra = {
            "approvedBy": user_email,
            "approvedAt": now,
            "authorizationId": authorization_id or record.get("authorizationId", ""),
        }

        return OvertimeService._transition(
            company_id, record_id, OvertimeService.APPROVED,
            user_email, "Aprobado", extra, sandbox=sandbox,
        )

    @staticmethod
    def reject(company_id: str, record_id: str, user_email: str,
                reason: str = "", sandbox: bool = True) -> dict | tuple:
        """Rechaza el registro (pending → rejected)."""
        if not reason:
            return {"error": "Debes proporcionar un motivo de rechazo."}, 400

        record = hr.get_overtime_record(company_id, record_id, sandbox=sandbox)
        if not record:
            return {"error": "Registro no encontrado."}, 404

        if record.get("status") != OvertimeService.PENDING:
            return {"error": "Solo registros pendientes pueden rechazarse."}, 400

        return OvertimeService._transition(
            company_id, record_id, OvertimeService.REJECTED,
            user_email, reason, sandbox=sandbox,
        )

    @staticmethod
    def lock(company_id: str, record_id: str, user_email: str,
              sandbox: bool = True) -> dict | tuple:
        """Bloquea el registro para procesamiento (approved → locked)."""
        return OvertimeService._transition(
            company_id, record_id, OvertimeService.LOCKED,
            user_email, "Bloqueado para procesamiento en nómina",
            sandbox=sandbox,
        )

    @staticmethod
    def mark_as_processed(company_id: str, record_id: str,
                           payroll_id: str, user_email: str,
                           sandbox: bool = True) -> dict | tuple:
        """Marca como procesado en nómina (locked → processed)."""
        record = hr.get_overtime_record(company_id, record_id, sandbox=sandbox)
        if not record:
            return {"error": "Registro no encontrado."}, 404

        if record.get("status") not in (OvertimeService.LOCKED, OvertimeService.APPROVED):
            return {"error": "Solo registros bloqueados o aprobados pueden marcarse como procesados."}, 400

        if record.get("processedPayrollId"):
            return {"error": "Este registro ya fue procesado en otra nómina."}, 400

        now = OvertimeService._now_iso()
        extra = {
            "processedPayrollId": payroll_id,
            "processedAt": now,
        }
        return OvertimeService._transition(
            company_id, record_id, OvertimeService.PROCESSED,
            user_email, f"Procesado en nómina {payroll_id}", extra,
            sandbox=sandbox,
        )

    @staticmethod
    def reopen(company_id: str, record_id: str, user_email: str,
                sandbox: bool = True) -> dict | tuple:
        """Reabre un registro procesado (processed → reopened).
        Útil cuando se reversa una nómina."""
        return OvertimeService._transition(
            company_id, record_id, OvertimeService.REOPENED,
            user_email, "Reabierto por reversión de nómina",
            sandbox=sandbox,
        )

    @staticmethod
    def reset_to_draft(company_id: str, record_id: str, user_email: str,
                        sandbox: bool = True) -> dict | tuple:
        """Vuelve un registro rechazado o reabierto a borrador."""
        return OvertimeService._transition(
            company_id, record_id, OvertimeService.DRAFT,
            user_email, "Devuelto a borrador",
            sandbox=sandbox,
        )

    # ── Integración con nómina ──

    @staticmethod
    def get_approved_for_period(company_id: str, start_date: str,
                                 end_date: str,
                                 sandbox: bool = True) -> list:
        """Retorna registros aprobados (no procesados) en el rango de fechas."""
        all_records = hr.get_overtime_records(company_id, sandbox=sandbox)
        filtered = []
        for r in all_records:
            status = r.get("status", "")
            if status not in (OvertimeService.APPROVED,):
                continue
            if r.get("processedPayrollId"):
                continue
            rec_date = r.get("date", "")
            if rec_date and start_date <= rec_date <= end_date:
                filtered.append(r)
        return filtered

    @staticmethod
    def group_by_employee_and_type(records: list) -> dict:
        """Agrupa registros por employeeId y overtimeTypeCode.

        Returns:
            {employee_id: {type_code: {"minutes": total, "records": [ids],
                                        "hourlyRate": x, "factor": y}}}
        """
        result = {}
        for r in records:
            emp_id = r.get("employeeId", "")
            tcode = r.get("overtimeTypeCode", "")
            minutes = r.get("totalMinutes", 0)
            rate = float(r.get("hourlyRateAtApproval", 0))
            factor = float(r.get("factorAtApproval", 1.35))

            emp_group = result.setdefault(emp_id, {})
            type_group = emp_group.setdefault(tcode, {
                "minutes": 0,
                "records": [],
                "hourlyRate": rate,
                "factor": factor,
                "conceptCode": r.get("overtimeTypeCode", ""),
            })
            type_group["minutes"] += minutes
            type_group["records"].append(r.get("id", ""))
            # Usar el primer rate/factor encontrado (todos deberían ser iguales)
            if not type_group.get("_rate_set"):
                type_group["hourlyRate"] = rate
                type_group["factor"] = factor
                type_group["_rate_set"] = True
        return result

    @staticmethod
    def create_payroll_link(company_id: str, overtime_id: str,
                             payroll_id: str, period_key: str,
                             transaction_id: str, concept_code: str,
                             amount: float, sandbox: bool = True) -> dict:
        """Crea un vínculo entre HE y nómina para trazabilidad."""
        from uuid import uuid4
        link_id = str(uuid4())
        now = OvertimeService._now_iso()
        link = {
            "overtimeId": overtime_id,
            "payrollId": payroll_id,
            "periodKey": period_key,
            "transactionId": transaction_id,
            "conceptCode": concept_code,
            "amount": amount,
            "createdAt": now,
        }
        hr.save_overtime_payroll_link(company_id, link_id, link, sandbox=sandbox)
        return link

    @staticmethod
    def get_links_for_payroll(company_id: str, payroll_id: str,
                               sandbox: bool = True) -> list:
        return hr.get_overtime_payroll_links(company_id, payroll_id, sandbox=sandbox)

    @staticmethod
    def validate_no_duplicate_processing(company_id: str, record_ids: list,
                                          payroll_id: str,
                                          sandbox: bool = True) -> list:
        """Valida que ningún registro esté ya procesado. Retorna errores."""
        errors = []
        for rid in record_ids:
            record = hr.get_overtime_record(company_id, rid, sandbox=sandbox)
            if record and record.get("processedPayrollId"):
                errors.append(
                    f"HE {record.get('number', rid)} ya procesada en nómina "
                    f"{record['processedPayrollId']}"
                )
            # Segunda barrera: verificar vínculo
            links = hr.get_overtime_payroll_links(company_id, "", sandbox=sandbox)
            for link in links:
                if link.get("overtimeId") == rid and link.get("payrollId") == payroll_id:
                    errors.append(
                        f"HE {record.get('number', rid)} ya tiene un vínculo "
                        f"con esta nómina"
                    )
                    break
        return errors

    # ── Seed data ──

    DEFAULT_OVERTIME_TYPES = [
        {"code": "HE01", "name": "Hora Extra Diurna",    "factor": 1.35, "conceptCode": "HE_DIURNA"},
        {"code": "HE02", "name": "Hora Extra Nocturna",  "factor": 1.50, "conceptCode": "HE_NOCTURNA"},
        {"code": "HE03", "name": "Día Feriado / Descanso", "factor": 2.00, "conceptCode": "HE_FERIADO"},
    ]

    @staticmethod
    def seed_default_types(company_id: str, sandbox: bool = True):
        """Crea los tipos de HE por defecto si no existen."""
        existing = hr.get_overtime_types(company_id, sandbox=sandbox)
        existing_codes = {t["code"] for t in existing}
        for ot in OvertimeService.DEFAULT_OVERTIME_TYPES:
            if ot["code"] not in existing_codes:
                data = dict(ot)
                data["active"] = True
                hr.save_overtime_type(company_id, ot["code"], data, sandbox=sandbox)
