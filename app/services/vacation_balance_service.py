"""VacationBalanceService — Saldo y desglose de vacaciones por año de servicio.

Fuente única de verdad para el acumulado de vacaciones de un empleado. Desglosa
el balance por período de aniversario (14 días/año los primeros 5 años, 18 a
partir del 6to), aplica el alcance de contrato (vacationPolicy=reset) y expone
el saldo disponible. Es usado tanto por el reporte "Acumulado por Año" como por
el formulario de solicitud de vacaciones (RRHH), de modo que el número mostrado
al seleccionar un empleado coincide con el que se guarda en remainingDaysBefore.
"""

from datetime import date
from typing import Optional

from app.services import hr_data_service as hr


def _add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def vacation_period_accrual(period_number: int) -> int:
    """Días ganados por período de servicio según Ley 16-92.

    14 días/año los primeros 5 años, 18 días/año a partir del 6to año.
    """
    return 14 if period_number <= 5 else 18


def vacation_request_days(r: dict) -> int:
    """Días efectivamente descontados de una solicitud (misma regla que
    EmployeeStatusService.taken_vacation_days)."""
    status = r.get("status", "")
    if status == "aprobada":
        return int(r.get("days", 0) or 0)
    if status in ("anulada", "revocada"):
        return int(r.get("consumedDays", 0) or 0)
    return 0


def build_vacation_yearly_periods(base_date_str, requests, today=None):
    """Desglosa el acumulado de vacaciones por año de servicio (aniversario).

    Retorna una lista de dicts por período, con días ganados, tomados,
    pendientes y saldo corrido. Función pura (testeable).
    """
    if today is None:
        today = date.today()
    try:
        base = date.fromisoformat((base_date_str or "")[:10])
    except (ValueError, TypeError):
        return []

    req_items = []
    for r in requests or []:
        days = vacation_request_days(r)
        if days <= 0:
            continue
        req_items.append({
            "startDate": (r.get("startDate") or "")[:10],
            "days": days,
        })

    periods = []
    period_number = 1
    period_start = base
    running_accrued = 0
    running_taken = 0

    while period_start < today:
        full_end = _add_years(base, period_number)
        is_current = full_end > today
        period_end = today if is_current else full_end

        if is_current:
            elapsed = (today - period_start).days
            accrued = max(0, round((elapsed / 365.0) * vacation_period_accrual(period_number)))
        else:
            accrued = vacation_period_accrual(period_number)

        taken = sum(
            it["days"] for it in req_items
            if it["startDate"] and period_start.isoformat() <= it["startDate"] < period_end.isoformat()
        )

        running_accrued += accrued
        running_taken += taken

        periods.append({
            "year": period_number,
            "startDate": period_start,
            "endDate": period_end,
            "accruedDays": accrued,
            "takenDays": taken,
            "pendingDays": accrued - taken,
            "runningBalance": running_accrued - running_taken,
            "isCurrent": is_current,
        })

        period_start = full_end
        period_number += 1

    return periods


def _scope_requests_for_contract(requests, active_contract, base_date):
    """Filtra las solicitudes al período de la relación laboral vigente.

    Con vacationPolicy=reset solo cuentan las solicitudes del contrato actual
    (o las legacy sin contractId cuyo startDate cae dentro del período).
    """
    if not active_contract:
        return requests
    if (active_contract.get("vacationPolicy", "reset") or "reset") != "reset":
        return requests
    cid = active_contract.get("id", "")
    return [
        r for r in requests
        if (r.get("contractId") or "") == cid
        or (not (r.get("contractId") or "") and (r.get("startDate", "") or "") >= (base_date or ""))
    ]


def build_vacation_summary(company_id: str, employee: dict, sandbox: bool,
                           active_contract: Optional[dict] = None) -> dict:
    """Resumen completo del acumulado de vacaciones de un empleado.

    Retorna:
      base_date: fecha base del período (vacationBaseDate o hireDate).
      periods: desglose por año de servicio (función pura).
      totals: {accrued, taken, pending}.
      availableDays: días disponibles (pending).
    """
    emp = employee or {}
    emp_id = emp.get("id", "")

    if active_contract is None:
        try:
            active_contract = hr.get_active_contract_for_employee(company_id, emp_id, sandbox=sandbox)
        except Exception:
            active_contract = None

    ctx = hr.get_employment_context(emp, active_contract)
    base_date = ctx.get("vacationBaseDate") or emp.get("hireDate", "") or ""

    requests = [
        r for r in hr.get_vacation_requests(company_id, sandbox=sandbox)
        if r.get("employeeId") == emp_id
    ]
    requests = _scope_requests_for_contract(requests, active_contract, base_date)

    periods = build_vacation_yearly_periods(base_date, requests)

    totals = {
        "accrued": sum(p["accruedDays"] for p in periods),
        "taken": sum(p["takenDays"] for p in periods),
        "pending": sum(p["pendingDays"] for p in periods),
    }

    return {
        "base_date": base_date,
        "active_contract": active_contract,
        "periods": periods,
        "totals": totals,
        "availableDays": totals["pending"],
    }
