"""Tests para VacationBalanceService (desglose de vacaciones por año de servicio).

Cubre las funciones puras que alimentan tanto el reporte "Acumulado por Año"
como el formulario de solicitud de vacaciones, y el scope de contrato.
"""

from datetime import date

from app.services.vacation_balance_service import (
    _add_years,
    vacation_period_accrual,
    vacation_request_days,
    build_vacation_yearly_periods,
    _scope_requests_for_contract,
)


def _vac(status="aprobada", start="2021-05-01", days=5, consumed=0, contract_id=""):
    return {
        "id": "v1", "employeeId": "e1", "status": status,
        "startDate": start, "endDate": "2021-05-10",
        "days": days, "consumedDays": consumed, "contractId": contract_id,
    }


def test_accrual_14_first_five_years_18_after():
    assert vacation_period_accrual(1) == 14
    assert vacation_period_accrual(5) == 14
    assert vacation_period_accrual(6) == 18
    assert vacation_period_accrual(10) == 18


def test_request_days_by_status():
    assert vacation_request_days(_vac(status="aprobada", days=8)) == 8
    assert vacation_request_days(_vac(status="anulada", days=8, consumed=3)) == 3
    assert vacation_request_days(_vac(status="revocada", days=8, consumed=2)) == 2
    assert vacation_request_days(_vac(status="pendiente", days=8)) == 0
    assert vacation_request_days(_vac(status="rechazada", days=8)) == 0


def test_full_years_no_taken():
    periods = build_vacation_yearly_periods("2020-01-01", [], today=date(2023, 1, 1))
    assert [p["year"] for p in periods] == [1, 2, 3]
    assert [p["accruedDays"] for p in periods] == [14, 14, 14]
    assert [p["runningBalance"] for p in periods] == [14, 28, 42]


def test_partial_current_period_is_prorated():
    periods = build_vacation_yearly_periods("2020-01-01", [], today=date(2023, 6, 1))
    assert len(periods) == 4
    assert periods[3]["isCurrent"] is True
    assert periods[3]["accruedDays"] == 6
    assert periods[3]["runningBalance"] == 14 + 14 + 14 + 6


def test_taken_days_attributed_to_period_by_start_date():
    reqs = [
        _vac(status="aprobada", start="2021-05-01", days=5),
        _vac(status="anulada", start="2021-08-01", days=10, consumed=3),
    ]
    periods = build_vacation_yearly_periods("2020-01-01", reqs, today=date(2022, 6, 1))
    assert periods[0]["takenDays"] == 0
    assert periods[1]["takenDays"] == 8
    assert periods[1]["pendingDays"] == 14 - 8
    assert periods[1]["runningBalance"] == 14 + (14 - 8)


def test_empty_when_no_base_date():
    assert build_vacation_yearly_periods("", [], today=date(2023, 1, 1)) == []
    assert build_vacation_yearly_periods(None, [], today=date(2023, 1, 1)) == []


def test_add_years_leap_day():
    assert _add_years(date(2020, 2, 29), 1) == date(2021, 2, 28)
    assert _add_years(date(2020, 2, 29), 4) == date(2024, 2, 29)


def test_scope_requests_reset_filters_by_contract():
    ctr = {"id": "c2", "vacationPolicy": "reset"}
    reqs = [
        _vac(contract_id="c2"),
        _vac(contract_id="c1"),
        _vac(contract_id="", start="2024-05-01"),
        _vac(contract_id="", start="2020-01-01"),
    ]
    scoped = _scope_requests_for_contract(reqs, ctr, "2023-01-01")
    ids = [r["id"] for r in scoped]
    # c2 explícito + legacy sin contractId con startDate >= base
    assert scoped[0]["id"] == "v1"
    assert scoped[1]["contractId"] == ""


def test_scope_requests_preserve_keeps_all():
    ctr = {"id": "c2", "vacationPolicy": "preserve"}
    reqs = [_vac(contract_id="c2"), _vac(contract_id="c1")]
    assert _scope_requests_for_contract(reqs, ctr, "2023-01-01") == reqs


def test_scope_requests_no_contract_returns_all():
    reqs = [_vac(contract_id="c2"), _vac(contract_id="c1")]
    assert _scope_requests_for_contract(reqs, None, "2023-01-01") == reqs
