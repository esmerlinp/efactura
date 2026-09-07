"""RehireService — Proceso formal de reincorporación de empleados.

Regla fundamental:
    Una reincorporación es una NUEVA relación laboral del MISMO empleado.
    Nunca modifica la relación anterior.

Modelo:
    Employee = identidad + snapshot operativo temporal
    EmploymentContract = cada período laboral (fuente de verdad de períodos nuevos)

Frontera legacy (Fase 2.5):
    Registros nuevos desde rehire → contractId obligatorio (cuando aplique).
    Registros legacy → contractId = "" con fallback a employeeId.

Políticas determinísticas:
    seniorityPolicy: reset | preserve  + seniorityBaseDate explícita
    vacationPolicy: reset | preserve   + vacationBaseDate explícita
    reset   → baseDate = contract.startDate
    preserve→ baseDate = fecha explícita negociada (nunca inferida luego)
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models.contract import EmploymentContract


class RehireValidationError(ValueError):
    """Error de validación de reincorporación (mensaje mostrable al usuario)."""
    def __init__(self, message: str, code: str = "validation_error"):
        super().__init__(message)
        self.code = code


REHIREABLE_STATUSES = {"inactivo"}
BLOCKED_ACTIVE_EQUIVALENT = {"activo", "vacaciones", "licencia", "suspendido"}

VALID_SENIORITY_POLICIES = {"reset", "preserve"}
VALID_VACATION_POLICIES = {"reset", "preserve"}
VALID_ORIGINS = {"initial_hire", "rehire", "contract_change", "legacy"}


def _today_iso_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(value: str) -> Optional[str]:
    """Normaliza YYYY-MM-DD (acepta ISO datetime). Retorna YYYY-MM-DD o None."""
    if not value:
        return None
    s = str(value).strip()[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        return None


def validate_rehire_eligibility(employee: dict | None,
                                active_contracts: list,
                                start_date: str,
                                previous_contract: dict | None = None) -> dict:
    """Validación pura (sin Firestore) — testeable unitariamente.

    Retorna {"previousContract": ...} si es elegible, lanza RehireValidationError si no.
    """
    if not employee:
        raise RehireValidationError("Empleado no encontrado.", code="employee_not_found")

    status = (employee.get("status") or "").strip()
    if status in BLOCKED_ACTIVE_EQUIVALENT:
        raise RehireValidationError(
            "No es posible reincorporar un empleado que ya posee una relación laboral activa.",
            code="employee_active",
        )
    if status not in REHIREABLE_STATUSES:
        raise RehireValidationError(
            f"Estado '{status or '—'}' no compatible con reincorporación. Solo 'inactivo'.",
            code="invalid_status",
        )

    if active_contracts and len(active_contracts) > 1:
        raise RehireValidationError(
            f"Inconsistencia: el empleado tiene {len(active_contracts)} contratos activos. "
            "Resolver antes de reincorporar.",
            code="multiple_active_contracts",
        )
    if active_contracts and len(active_contracts) == 1:
        raise RehireValidationError(
            "El empleado ya posee una relación laboral activa. Cerrar la relación anterior primero.",
            code="active_contract_exists",
        )

    norm_start = _parse_date(start_date)
    if not norm_start:
        raise RehireValidationError(
            "Fecha de reincorporación inválida (formato YYYY-MM-DD).",
            code="invalid_date",
        )

    if previous_contract:
        prev_end = (
            _parse_date(previous_contract.get("endDate") or "")
            or _parse_date(previous_contract.get("terminationDate") or "")
        )
        if prev_end and norm_start <= prev_end:
            raise RehireValidationError(
                f"La fecha de reincorporación ({norm_start}) debe ser posterior "
                f"al fin de la relación anterior ({prev_end}).",
                code="invalid_date_order",
            )

    return {"previousContract": previous_contract, "startDate": norm_start}


def resolve_policy_base_dates(start_date: str,
                              seniority_policy: str = "reset",
                              vacation_policy: str = "reset",
                              seniority_base_input: str = "",
                              vacation_base_input: str = "") -> dict:
    """Resuelve fechas base determinísticas. Nunca infiere desde Employee.hireDate."""
    seniority_policy = (seniority_policy or "reset").strip()
    vacation_policy = (vacation_policy or "reset").strip()
    if seniority_policy not in VALID_SENIORITY_POLICIES:
        raise RehireValidationError(f"seniorityPolicy inválida: {seniority_policy}", code="invalid_policy")
    if vacation_policy not in VALID_VACATION_POLICIES:
        raise RehireValidationError(f"vacationPolicy inválida: {vacation_policy}", code="invalid_policy")

    norm_start = _parse_date(start_date) or ""
    if seniority_policy == "reset":
        seniority_base = norm_start
    else:
        seniority_base = _parse_date(seniority_base_input) or ""
        if not seniority_base:
            raise RehireValidationError(
                "Con seniorityPolicy=preserve debe indicarse seniorityBaseDate explícita.",
                code="missing_seniority_base",
            )

    if vacation_policy == "reset":
        vacation_base = norm_start
    else:
        vacation_base = _parse_date(vacation_base_input) or ""
        if not vacation_base:
            raise RehireValidationError(
                "Con vacationPolicy=preserve debe indicarse vacationBaseDate explícita.",
                code="missing_vacation_base",
            )

    return {
        "seniorityPolicy": seniority_policy,
        "seniorityBaseDate": seniority_base,
        "vacationPolicy": vacation_policy,
        "vacationBaseDate": vacation_base,
    }


def build_new_contract_dict(employee: dict,
                            previous_contract: dict | None,
                            period_number: int,
                            start_date: str,
                            contract_data: dict,
                            policies: dict,
                            actor_email: str = "",
                            rehire_request_id: str = "") -> dict:
    """Construye el dict del nuevo EmploymentContract (sin persistir). No toca el anterior."""
    prev = previous_contract or {}
    now = _now_iso()
    new_id = contract_data.get("id") or f"ctr_{uuid.uuid4().hex[:12]}"

    def _pick(key: str, default: str = "") -> str:
        val = contract_data.get(key, "")
        if val not in (None, ""):
            return val
        # Copiar desde relación anterior solo si el llamador lo pidió explícitamente
        # (el frontend usa "Copiar datos" para llenar el formulario, no auto-magía aquí).
        return prev.get(key, default) if contract_data.get("_copyFromPrevious") else default

    salary = float(contract_data.get("salary", 0) or 0)
    if salary <= 0 and prev.get("salary"):
        # No heredar salario silenciosamente: exigirlo salvo copia explícita.
        if contract_data.get("_copyFromPrevious"):
            salary = float(prev.get("salary") or 0)

    contract = {
        "id": new_id,
        "employeeId": employee.get("id", ""),
        "legalEntityId": contract_data.get("legalEntityId", prev.get("legalEntityId", "")),
        "contractType": contract_data.get("contractType", prev.get("contractType", "") if contract_data.get("_copyFromPrevious") else ""),
        "position": contract_data.get("position", ""),
        "positionId": contract_data.get("positionId", prev.get("positionId", "")),
        "department": contract_data.get("department", ""),
        "departmentId": contract_data.get("departmentId", ""),
        "area": contract_data.get("area", prev.get("area", "") if contract_data.get("_copyFromPrevious") else ""),
        "costCenter": contract_data.get("costCenter", ""),
        "branchId": contract_data.get("branchId", prev.get("branchId", "") if contract_data.get("_copyFromPrevious") else ""),
        "salary": salary,
        "salaryType": contract_data.get("salaryType", prev.get("salaryType", "fijo")),
        "hourlyRate": float(contract_data.get("hourlyRate", prev.get("hourlyRate", 0) or 0) or 0),
        "currency": contract_data.get("currency", "DOP"),
        "workday": contract_data.get("workday", prev.get("workday", "completa")),
        "weeklyHours": int(contract_data.get("weeklyHours", prev.get("weeklyHours", 44)) or 44),
        "workShift": int(contract_data.get("workShift", prev.get("workShift", 1)) or 1),
        "isVigilante": bool(contract_data.get("isVigilante", prev.get("isVigilante", False))),
        "tssKey": contract_data.get("tssKey", prev.get("tssKey", "")),
        "afpProvider": contract_data.get("afpProvider", prev.get("afpProvider", "")),
        "startDate": start_date,
        "endDate": "",
        "probationEndDate": contract_data.get("probationEndDate", ""),
        "status": "activo",
        "terminationDate": None,
        "terminationReason": None,
        "terminationType": "",
        # Período laboral
        "periodNumber": int(period_number or 1),
        "origin": "rehire",
        "previousContractId": prev.get("id", "") if prev else "",
        "rehireRequestId": rehire_request_id or "",
        "closedAt": "",
        # Políticas determinísticas
        "seniorityPolicy": policies.get("seniorityPolicy", "reset"),
        "seniorityBaseDate": policies.get("seniorityBaseDate", start_date),
        "vacationPolicy": policies.get("vacationPolicy", "reset"),
        "vacationBaseDate": policies.get("vacationBaseDate", start_date),
        # Snapshot extendido
        "reportsTo": contract_data.get("reportsTo", contract_data.get("supervisorId", "")),
        "paymentMethod": contract_data.get("paymentMethod", prev.get("paymentMethod", "") if contract_data.get("_copyFromPrevious") else ""),
        "bank": contract_data.get("bank", prev.get("bank", "") if contract_data.get("_copyFromPrevious") else ""),
        "accountNumber": contract_data.get("accountNumber", prev.get("accountNumber", "") if contract_data.get("_copyFromPrevious") else ""),
        "accountType": contract_data.get("accountType", prev.get("accountType", "") if contract_data.get("_copyFromPrevious") else ""),
        "variableSalary": float(contract_data.get("variableSalary", 0) or 0),
        "workLocation": contract_data.get("workLocation", contract_data.get("location", "")),
        "payrollGroupIds": contract_data.get("payrollGroupIds", prev.get("payrollGroupIds", []) or []),
        "occupationCode": contract_data.get("occupationCode", prev.get("occupationCode", "")),
        "educationLevel": int(contract_data.get("educationLevel", prev.get("educationLevel", 0)) or 0),
        "vacationGranted": int(contract_data.get("vacationGranted", 1) or 1),
        "notes": contract_data.get("notes", ""),
        "createdBy": actor_email,
        "createdAt": now,
        "updatedBy": actor_email,
        "updatedAt": now,
    }
    # Validación best-effort con el modelo (tolerar pydantic mockeado en tests).
    try:
        _fields = getattr(EmploymentContract, "model_fields", None)
        if isinstance(_fields, dict):
            EmploymentContract(**{k: v for k, v in contract.items() if k in _fields})
        else:
            try:
                EmploymentContract(**contract)
            except StopIteration:
                pass
    except Exception:
        pass
    return contract


def build_employee_snapshot(employee: dict, new_contract: dict) -> dict:
    """Snapshot operativo del Employee para la nueva relación. No borra historia personal.

    Actualiza SOLO campos operativos de la relación activa + vínculo al contrato.
    Conserva id, code e identidad. Limpia campos de baja (ya liquidados en período anterior).
    """
    updated = dict(employee)
    start = new_contract.get("startDate", "")
    salary = float(new_contract.get("salary") or 0)

    updated["status"] = "activo"
    updated["currentEmploymentContractId"] = new_contract.get("id", "")
    # Snapshot operativo (fuente de verdad del período = el contrato; esto es compatibilidad)
    if start:
        updated["hireDate"] = start
    if salary > 0:
        updated["baseSalary"] = salary
        updated["salary"] = salary
    for key in ("position", "positionId", "department", "departmentId", "area",
                "costCenter", "branchId", "contractType", "workday", "salaryType",
                "hourlyRate", "tssKey", "afpProvider", "reportsTo",
                "paymentMethod", "bank", "accountNumber", "accountType",
                "weeklyHours", "workShift", "isVigilante", "occupationCode"):
        if new_contract.get(key) not in (None, ""):
            updated[key] = new_contract.get(key)
    if new_contract.get("payrollGroupIds"):
        updated["payrollGroupIds"] = new_contract.get("payrollGroupIds")
    # Limpiar baja (la relación anterior ya quedó cerrada en su contrato + offboarding/liquidación)
    updated.pop("terminationDate", None)
    updated.pop("terminationReason", None)
    updated["terminationType"] = ""
    updated.pop("lastWorkDate", None)
    updated["keepInCurrentPayroll"] = False
    # Trazabilidad de rehire (no sustituye al contrato como fuente)
    updated["rehireDate"] = _now_iso()
    updated["rehireCount"] = int(employee.get("rehireCount") or 0) + 1
    updated["lastRehireContractId"] = new_contract.get("id", "")
    updated["lastSeniorityPolicy"] = new_contract.get("seniorityPolicy", "reset")
    updated["lastSeniorityBaseDate"] = new_contract.get("seniorityBaseDate", start)
    updated["lastVacationPolicy"] = new_contract.get("vacationPolicy", "reset")
    updated["lastVacationBaseDate"] = new_contract.get("vacationBaseDate", start)
    return updated


def _is_loan_copyable(movement: dict) -> tuple[bool, str]:
    """Préstamos nunca se copian automáticamente en rehire (deben crearse manual)."""
    if movement.get("isLoan"):
        return False, "loan_never_copied"
    if (movement.get("status") or "") in ("completed", "cancelled"):
        return False, "movement_closed"
    return True, ""


class RehireService:
    """Servicio de dominio — única implementación de reincorporación."""

    def __init__(self, company_id: str, sandbox: bool = True):
        self.company_id = company_id
        self.sandbox = sandbox

    def rehire_employee(self,
                        employee_id: str,
                        start_date: str,
                        contract_data: dict | None = None,
                        selected_movement_ids: list | None = None,
                        seniority_policy: str = "reset",
                        vacation_policy: str = "reset",
                        seniority_base_date: str = "",
                        vacation_base_date: str = "",
                        rehire_request_id: str = "",
                        actor_email: str = "") -> dict:
        """Ejecuta la reincorporación completa. Ver FASE 5 del diseño.

        Retorna {"contract": ..., "employee": ..., "reused": bool, "copiedMovements": [...]}.
        Lanza RehireValidationError en validaciones.
        """
        from app.services import hr_data_service as hr

        contract_data = contract_data or {}
        selected_movement_ids = selected_movement_ids or []
        rehire_request_id = (rehire_request_id or "").strip() or f"reh_{uuid.uuid4().hex[:12]}"

        # ── 0. Idempotencia: ¿ya existe contrato para esta solicitud? ──
        existing = hr.get_contract_by_rehire_request(self.company_id, rehire_request_id, sandbox=self.sandbox)
        if existing:
            emp = hr.get_employee(self.company_id, employee_id, sandbox=self.sandbox)
            return {"contract": existing, "employee": emp, "reused": True,
                    "copiedMovements": [], "rehireRequestId": rehire_request_id}

        # ── 1. Cargar empleado ──
        employee = hr.get_employee(self.company_id, employee_id, sandbox=self.sandbox)
        if not employee:
            raise RehireValidationError("Empleado no encontrado.", code="employee_not_found")
        prev_code = employee.get("code")
        prev_id = employee.get("id", employee_id)

        # ── 2/3/4. Validar estado + contratos ──
        active_contracts = hr.get_active_contracts_for_employee(self.company_id, employee_id, sandbox=self.sandbox)
        contracts_all = hr.get_contracts_for_employee(self.company_id, employee_id, sandbox=self.sandbox)
        previous = hr.get_last_terminated_contract(self.company_id, employee_id, sandbox=self.sandbox)
        # Si no hay contratos pero hay historia en Employee (legacy con baja), construir
        # un "previous virtual" desde Employee para validar orden de fechas sin crear registros.
        if not previous and (employee.get("terminationDate") or employee.get("hireDate")):
            previous = {
                "id": "",
                "periodNumber": 0,
                "startDate": employee.get("hireDate", "") or "",
                "endDate": employee.get("terminationDate", "") or "",
                "terminationDate": employee.get("terminationDate", "") or "",
                "status": "terminado",
                "salary": employee.get("baseSalary", employee.get("salary", 0)),
                "position": employee.get("position", ""),
            }

        validated = validate_rehire_eligibility(employee, active_contracts, start_date, previous)
        norm_start = validated["startDate"]

        # ── Offboarding abierto incompatible ──
        try:
            from app.services.offboarding_service import OffboardingService
            off = OffboardingService(self.company_id, self.sandbox)
            active_req = off.get_active_request_for_employee(employee_id)
            if active_req:
                raise RehireValidationError(
                    "El empleado tiene un proceso de desvinculación abierto. Resolverlo antes de reincorporar.",
                    code="offboarding_open",
                )
        except RehireValidationError:
            raise
        except Exception:
            pass  # si offboarding no disponible, no bloquear

        # ── 5/6. Políticas determinísticas ──
        policies = resolve_policy_base_dates(norm_start, seniority_policy, vacation_policy,
                                             seniority_base_date, vacation_base_date)

        # ── 7. Crear nuevo contrato (nunca reutilizar anterior) ──
        period_number = hr.get_next_contract_period_number(self.company_id, employee_id, sandbox=self.sandbox)
        # Si existe historia legacy sin contratos, el nuevo período es 1 o max+1 coherente.
        new_contract = build_new_contract_dict(employee, previous if previous and previous.get("id") else (previous or {}),
                                               period_number, norm_start, contract_data,
                                               policies, actor_email, rehire_request_id)
        new_contract_id = new_contract.get("id", "")

        # Persistir contrato primero (fuente de verdad del período nuevo)
        hr.save_contract(self.company_id, new_contract_id, new_contract, sandbox=self.sandbox)

        # ── 8. Snapshot operativo del empleado ──
        before_employee = dict(employee)
        updated_employee = build_employee_snapshot(employee, new_contract)
        # Preservar code/id
        updated_employee["id"] = prev_id
        if prev_code:
            updated_employee["code"] = prev_code
        hr.save_employee(self.company_id, employee_id, updated_employee, sandbox=self.sandbox)

        # ── 9. Historial salarial del nuevo período ──
        try:
            prev_salary = float(before_employee.get("baseSalary", before_employee.get("salary", 0)) or 0)
            hr.save_salary_history_entry(self.company_id, {
                "id": f"sal_{uuid.uuid4().hex[:12]}",
                "employeeId": employee_id,
                "contractId": new_contract_id,
                "amount": float(new_contract.get("salary") or 0),
                "previousAmount": prev_salary,
                "effectiveDate": norm_start,
                "endDate": "",
                "reason": f"reincorporación período {period_number}",
                "approvedBy": actor_email,
                "createdAt": _now_iso(),
                "payrollPeriodKey": "",
            }, sandbox=self.sandbox)
        except Exception as e:
            print(f"⚠️ RehireService salary_history: {e}")

        # ── 10. Movimientos: solo selección explícita, nunca auto-copia ──
        copied = []
        if selected_movement_ids:
            try:
                from app.services.recurring_service import get_recurring_movements, save_recurring_movement
                for mv_id in selected_movement_ids:
                    src = None
                    for mv in get_recurring_movements(self.company_id, employee_id=employee_id, sandbox=self.sandbox):
                        if mv.get("id") == mv_id:
                            src = mv
                            break
                    if not src:
                        continue
                    ok, reason = _is_loan_copyable(src)
                    if not ok:
                        continue  # préstamo o cerrado: nunca copiar
                    new_mv = dict(src)
                    new_mv["id"] = f"rm_{uuid.uuid4().hex[:12]}"
                    new_mv["contractId"] = new_contract_id
                    new_mv["sourceMovementId"] = src.get("id", "")
                    new_mv["status"] = "active"
                    new_mv["startDate"] = norm_start
                    new_mv["paidInstallments"] = 0
                    # remainingBalance solo aplica a préstamos (ya excluidos); conservar monto base
                    new_mv["createdBy"] = actor_email
                    new_mv["createdAt"] = _now_iso()
                    new_mv["updatedBy"] = actor_email
                    new_mv["updatedAt"] = _now_iso()
                    new_mv["notes"] = ((src.get("notes") or "") + f" | copiado en rehire {norm_start}").strip(" |")
                    save_recurring_movement(self.company_id, new_mv["id"], new_mv, sandbox=self.sandbox)
                    copied.append({"from": src.get("id", ""), "to": new_mv["id"],
                                   "conceptCode": src.get("conceptCode", "")})
            except Exception as e:
                print(f"⚠️ RehireService copy_movements: {e}")

        # ── 11. Vacaciones: no tocar histórico (el nuevo período usa vacationBaseDate) ──
        # (Sin escritura: los saldos se calculan desde el contrato activo.)

        # ── 12. Auditoría ──
        try:
            from app.services.payroll_audit_service import log_action
            prev_contract_id = (previous or {}).get("id", "") if previous else ""
            log_action(self.company_id, "rehire", "employee", employee_id, actor_email,
                       changes={
                           "status": {"from": before_employee.get("status"), "to": "activo"},
                           "previousContractId": prev_contract_id,
                           "newContractId": new_contract_id,
                           "periodNumber": period_number,
                           "previousHireDate": before_employee.get("hireDate", ""),
                           "newHireDate": norm_start,
                           "seniorityPolicy": policies["seniorityPolicy"],
                           "seniorityBaseDate": policies["seniorityBaseDate"],
                           "vacationPolicy": policies["vacationPolicy"],
                           "vacationBaseDate": policies["vacationBaseDate"],
                           "copiedMovements": len(copied),
                           "rehireRequestId": rehire_request_id,
                       },
                       comment=f"Reincorporación período {period_number} ({norm_start})",
                       sandbox=self.sandbox,
                       before={"status": before_employee.get("status"),
                               "hireDate": before_employee.get("hireDate", ""),
                               "currentEmploymentContractId": before_employee.get("currentEmploymentContractId", "")},
                       after={"status": "activo", "hireDate": norm_start,
                              "currentEmploymentContractId": new_contract_id})
        except Exception as e:
            print(f"⚠️ RehireService audit: {e}")

        # ── Historial laboral: registrar hito de reincorporación (sin alterar cambios previos) ──
        try:
            hr.save_employment_history(self.company_id, {
                "id": f"eh_{uuid.uuid4().hex[:12]}",
                "employeeId": employee_id,
                "contractId": new_contract_id,
                "changeType": "rehire",
                "previousContractId": (previous or {}).get("id", "") if previous else "",
                "newPosition": new_contract.get("position", ""),
                "newDepartment": new_contract.get("department", new_contract.get("departmentId", "")),
                "newSalary": float(new_contract.get("salary") or 0),
                "changedAt": _now_iso(),
                "changedBy": actor_email,
                "reason": f"Reincorporación período {period_number}",
            }, sandbox=self.sandbox)
        except Exception as e:
            print(f"⚠️ RehireService employment_history: {e}")

        return {"contract": new_contract, "employee": updated_employee, "reused": False,
                "copiedMovements": copied, "rehireRequestId": rehire_request_id,
                "previousContractId": (previous or {}).get("id", "") if previous else ""}
