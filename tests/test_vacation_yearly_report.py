"""Tests para el reporte "Acumulado de Vacaciones por Año".

Cubre el desglose por año de servicio (aniversario): días ganados por período
(14 los primeros 5 años, 18 desde el 6to), prorrateo del período en curso,
atribución de días tomados por startDate y saldo corrido.
"""

from datetime import date

from app.web.rrhh.reports import (
    _build_vacation_yearly_periods,
    _vacation_period_accrual,
    _vacation_request_days,
    _add_years,
    _resolve_logo_src,
)


def _vac(status="aprobada", start="2021-05-01", days=5, consumed=0):
    return {
        "id": "v1", "employeeId": "e1", "status": status,
        "startDate": start, "endDate": "2021-05-10",
        "days": days, "consumedDays": consumed,
    }


# ── Reglas unitarias ──


def test_accrual_14_first_five_years_18_after():
    assert _vacation_period_accrual(1) == 14
    assert _vacation_period_accrual(5) == 14
    assert _vacation_period_accrual(6) == 18
    assert _vacation_period_accrual(10) == 18


def test_request_days_by_status():
    assert _vacation_request_days(_vac(status="aprobada", days=8)) == 8
    assert _vacation_request_days(_vac(status="anulada", days=8, consumed=3)) == 3
    assert _vacation_request_days(_vac(status="revocada", days=8, consumed=2)) == 2
    assert _vacation_request_days(_vac(status="pendiente", days=8)) == 0
    assert _vacation_request_days(_vac(status="rechazada", days=8)) == 0


# ── Desglose por año de servicio ──


def test_full_years_no_taken():
    periods = _build_vacation_yearly_periods("2020-01-01", [], today=date(2023, 1, 1))
    assert [p["year"] for p in periods] == [1, 2, 3]
    assert [p["accruedDays"] for p in periods] == [14, 14, 14]
    assert [p["takenDays"] for p in periods] == [0, 0, 0]
    assert [p["runningBalance"] for p in periods] == [14, 28, 42]


def test_partial_current_period_is_prorated():
    # 3 períodos completos + fracción del 4to (151 días → 6 días)
    periods = _build_vacation_yearly_periods("2020-01-01", [], today=date(2023, 6, 1))
    assert len(periods) == 4
    assert periods[3]["isCurrent"] is True
    assert periods[3]["accruedDays"] == 6
    assert periods[3]["runningBalance"] == 14 + 14 + 14 + 6


def test_taken_days_attributed_to_period_by_start_date():
    reqs = [
        _vac(status="aprobada", start="2021-05-01", days=5),
        _vac(status="anulada", start="2021-08-01", days=10, consumed=3),
    ]
    periods = _build_vacation_yearly_periods("2020-01-01", reqs, today=date(2022, 6, 1))
    # Año 1 (2020→2021): sin tomadas; Año 2 (2021→2022): 5 + 3 = 8
    assert periods[0]["takenDays"] == 0
    assert periods[1]["takenDays"] == 8
    assert periods[1]["pendingDays"] == 14 - 8
    assert periods[1]["runningBalance"] == 14 + (14 - 8)


def test_sixth_year_accrues_18():
    periods = _build_vacation_yearly_periods("2018-01-01", [], today=date(2024, 1, 1))
    assert len(periods) == 6
    assert periods[5]["accruedDays"] == 18


def test_empty_when_no_base_date():
    assert _build_vacation_yearly_periods("", [], today=date(2023, 1, 1)) == []
    assert _build_vacation_yearly_periods(None, [], today=date(2023, 1, 1)) == []


def test_add_years_leap_day():
    assert _add_years(date(2020, 2, 29), 1) == date(2021, 2, 28)
    assert _add_years(date(2020, 2, 29), 4) == date(2024, 2, 29)


# ── Resolución del logo para PDF ──


def test_logo_src_base64_raw():
    assert _resolve_logo_src({"logoBase64": "iVBORw0KGgo="}) == "data:image/png;base64,iVBORw0KGgo="


def test_logo_src_base64_prefixed():
    src = _resolve_logo_src({"logoBase64": "data:image/png;base64,iVBORw0KGgo="})
    assert src == "data:image/png;base64,iVBORw0KGgo="


def test_logo_src_url_fallback_and_embed():
    # URL remota que falla al descargar → devuelve la URL como último recurso
    assert _resolve_logo_src({"logoUrl": "https://x/y.png"}) == "https://x/y.png"


def test_logo_src_none():
    assert _resolve_logo_src({}) == ""
