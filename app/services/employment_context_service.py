"""EmploymentContextService — Resolver único del contexto laboral.

Responde, para cada cálculo nuevo: ¿esto representa al empleado (identidad)
o a una relación laboral (contrato)?

    - Identidad → Employee (id, code, nombre, documentos personales).
    - Relación  → EmploymentContract (fechas, salario, puesto, políticas).

Reglas:
    - Todo cálculo nuevo usa ``contractId`` explícito cuando existe contrato.
    - Legacy (``contractId == ""``) usa ``employeeId`` + rango de fechas.
    - Ambigüedad (varios contratos candidatos) → se bloquea con error,
      nunca se elige uno silenciosamente.
    - Nada aquí modifica Firestore: solo lectura + funciones puras
      (testeables sin base de datos).
"""

from datetime import datetime, timezone


class EmploymentContextError(ValueError):
    """Error de resolución de contexto laboral (mensaje mostrable)."""

    def __init__(self, message: str, code: str = "employment_context_error"):
        super().__init__(message)
        self.code = code


def _norm_date(value) -> str:
    """Normaliza a YYYY-MM-DD. "" si es inválida."""
    if not value:
        return ""
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return ""


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ─────────────────────────────────────────────────────────────────
# Resolución (lectura vía hr_data_service, import perezoso)
# ─────────────────────────────────────────────────────────────────

def resolve_by_contract_id(company_id: str, contract_id: str,
                           sandbox: bool = True) -> dict | None:
    """Contrato por ID. None si no existe."""
    if not (contract_id or "").strip():
        return None
    from app.services import hr_data_service as hr
    return hr.get_contract(company_id, contract_id.strip(), sandbox=sandbox)


def resolve_active(company_id: str, employee_id: str,
                   sandbox: bool = True) -> dict | None:
    """Contrato activo único. None si no hay. Lanza si hay >1 (inconsistencia)."""
    from app.services import hr_data_service as hr
    active = hr.get_active_contracts_for_employee(company_id, employee_id, sandbox=sandbox)
    if not active:
        return None
    if len(active) > 1:
        raise EmploymentContextError(
            f"El empleado tiene {len(active)} contratos activos. "
            "Resolver la inconsistencia antes de continuar.",
            code="multiple_active_contracts",
        )
    return active[0]


def resolve_for_termination(company_id: str, employee_id: str,
                            termination_date: str,
                            sandbox: bool = True) -> dict | None:
    """Contrato correspondiente a una fecha de salida.

    Orden de preferencia:
      1. Terminado exacto (endDate/terminationDate == fecha). Varios → error.
      2. Vigente que cubre la fecha (start <= fecha <= end|abierto). Varios → error.
      3. Terminado más reciente con fin <= fecha.
      4. None → el llamador usa fallback legacy (employeeId + fechas).
    """
    from app.services import hr_data_service as hr
    term = _norm_date(termination_date)
    if not term:
        raise EmploymentContextError(
            "Fecha de terminación inválida para resolver el contrato.",
            code="invalid_termination_date",
        )
    contracts = hr.get_contracts_for_employee(company_id, employee_id, sandbox=sandbox)
    if not contracts:
        return None

    exact = [c for c in contracts
             if (c.get("status") or "") == "terminado"
             and (_norm_date(c.get("endDate") or "") == term
                  or _norm_date(c.get("terminationDate") or "") == term)]
    if len(exact) > 1:
        raise EmploymentContextError(
            "Varios contratos terminan en la misma fecha. Resolver antes de liquidar.",
            code="ambiguous_termination_contract",
        )
    if exact:
        return exact[0]

    covering = [c for c in contracts
                if _norm_date(c.get("startDate") or "") <= term
                and (not _norm_date(c.get("endDate") or "")
                     or _norm_date(c.get("endDate") or "") >= term)]
    if len(covering) > 1:
        raise EmploymentContextError(
            "Varios contratos cubren la fecha de salida. Resolver antes de liquidar.",
            code="ambiguous_termination_contract",
        )
    if covering:
        return covering[0]

    past = [c for c in contracts
            if (c.get("status") or "") == "terminado"
            and _norm_date(c.get("endDate") or "") <= term]
    if past:
        past.sort(key=lambda c: (_norm_date(c.get("endDate") or ""),
                                 int(c.get("periodNumber") or 0)))
        return past[-1]
    return None


def build_context(employee: dict, contract: dict | None) -> dict:
    """Contexto laboral completo. ``contract=None`` → legacy (comportamiento actual)."""
    emp = employee or {}
    ctr = contract or {}
    cid = (ctr.get("id", "") or "").strip()
    salary = ctr.get("salary", "") if ctr else ""
    try:
        salary = float(salary) if salary not in (None, "") else \
            float(emp.get("baseSalary", emp.get("salary", 0)) or 0)
    except Exception:
        salary = float(emp.get("baseSalary", emp.get("salary", 0)) or 0)
    seniority_policy = (ctr.get("seniorityPolicy", "") or "reset") if ctr else "reset"
    seniority_base = (_norm_date(ctr.get("seniorityBaseDate", "")) if ctr else "") or ""
    vacation_policy = (ctr.get("vacationPolicy", "") or "reset") if ctr else "reset"
    vacation_base = (_norm_date(ctr.get("vacationBaseDate", "")) if ctr else "") or ""
    start = (_norm_date(ctr.get("startDate", "")) if ctr else "") or \
        _norm_date(emp.get("hireDate", ""))
    if not seniority_base:
        seniority_base = start
    if not vacation_base:
        vacation_base = start
    end = (_norm_date(ctr.get("endDate", "")) if ctr else "") or \
        _norm_date(ctr.get("terminationDate", "") if ctr else "")
    try:
        period_number = int(ctr.get("periodNumber") or 0) if ctr else 0
    except Exception:
        period_number = 0
    return {
        "employeeId": emp.get("id", ""),
        "contractId": cid,
        "isLegacy": not bool(cid and ctr),
        "periodNumber": period_number,
        "origin": (ctr.get("origin", "") if ctr else "") or "",
        "previousContractId": (ctr.get("previousContractId", "") if ctr else "") or "",
        "startDate": start,
        "endDate": end,
        "salary": salary,
        "position": (ctr.get("position", "") if ctr else "") or emp.get("position", ""),
        "department": ((ctr.get("department", "") or ctr.get("departmentId", "")) if ctr else "")
                      or emp.get("department", emp.get("departmentId", "")),
        "seniorityPolicy": seniority_policy,
        "seniorityBaseDate": seniority_base,
        "vacationPolicy": vacation_policy,
        "vacationBaseDate": vacation_base,
        "contract": dict(ctr) if ctr else None,
    }


def resolve_for_employee(company_id: str, employee: dict,
                         reference_date: str = "",
                         sandbox: bool = True) -> dict:
    """Atajo: contexto del contrato vigente a una fecha (o activo hoy).

    - Con contrato → contexto contractual.
    - Sin contrato → legacy (employeeId + fechas del Employee).
    """
    emp = employee or {}
    ref = _norm_date(reference_date) or _today()
    contract = None
    try:
        contract = resolve_for_termination(
            company_id, emp.get("id", ""), ref, sandbox=sandbox)
    except EmploymentContextError:
        raise
    except Exception:
        contract = None
    if contract is None:
        try:
            contract = resolve_active(company_id, emp.get("id", ""), sandbox=sandbox)
        except EmploymentContextError:
            raise
        except Exception:
            contract = None
    return build_context(emp, contract)


# ─────────────────────────────────────────────────────────────────
# Aislamiento de transacciones y movimientos (funciones puras)
# ─────────────────────────────────────────────────────────────────

def _tx_month(tx: dict) -> str:
    return ((tx.get("periodKey", "") or "")[:7])


def filter_transactions(transactions: list, ctx: dict) -> list:
    """Filtra transacciones al período del contexto.

    - Legacy (sin contrato) → todo (comportamiento actual, sin cambios).
    - Con contrato → solo ``contractId`` coincidente, más legacy
      (``contractId == ""``) cuyo mes caiga dentro del rango del contrato.
      El histórico anterior al rehire queda excluido por fecha.
    """
    ctx = ctx or {}
    cid = (ctx.get("contractId") or "").strip()
    if not cid:
        return list(transactions or [])
    start_m = (ctx.get("startDate") or "")[:7]
    end_m = (ctx.get("endDate") or _today())[:7]
    scoped = []
    for tx in (transactions or []):
        tx_cid = (tx.get("contractId") or "").strip()
        if tx_cid:
            if tx_cid == cid:
                scoped.append(tx)
            continue
        month = _tx_month(tx)
        if month and start_m and month < start_m:
            continue
        if month and end_m and month > end_m:
            continue
        scoped.append(tx)
    return scoped


def get_transactions_for_context(company_id: str, employee_id: str, ctx: dict,
                                 sandbox: bool = True) -> list:
    """Transacciones del empleado ya aisladas al contexto laboral."""
    from app.services import hr_data_service as hr
    txs = hr.get_payroll_transactions(company_id, employee_id=employee_id,
                                      sandbox=sandbox)
    return filter_transactions(txs, ctx)


def filter_movements(movements: list, ctx: dict) -> list:
    """Movimientos del contrato: coincidentes + legacy sin contrato.

    Los préstamos/cerrados se excluyen en la capa de rehire; aquí solo se
    delimita el alcance contractual (no se reactiva nada automáticamente).
    """
    ctx = ctx or {}
    cid = (ctx.get("contractId") or "").strip()
    if not cid:
        return list(movements or [])
    return [m for m in (movements or [])
            if not (m.get("contractId") or "").strip()
            or (m.get("contractId") or "").strip() == cid]


def contract_snapshot(contract: dict | None) -> dict:
    """Snapshot slim del contrato para guardar en liquidaciones/pagos."""
    if not contract:
        return {}
    keys = ("id", "employeeId", "periodNumber", "origin", "previousContractId",
            "contractType", "position", "department", "salary", "salaryType",
            "startDate", "endDate", "status", "terminationDate", "terminationType",
            "seniorityPolicy", "seniorityBaseDate", "vacationPolicy", "vacationBaseDate")
    return {k: contract.get(k, "") for k in keys}
