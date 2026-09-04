"""Tests del bloqueo secuencial de períodos de nómina."""

import pytest

from app.services.payroll_period_sequence import (
    blocked_period_keys,
    PAYROLL_CLOSED_STATUSES,
    _sort_key,
)


def _monthly_periods(year=2026, start=1, end=12):
    return [
        {"key": f"{year}-{m:02d}-M", "start": f"{year}-{m:02d}-01",
         "end": f"{year}-{m:02d}-28", "type": "mensual", "label": f"M: {m} {year}"}
        for m in range(start, end + 1)
    ]


def _quincenal_periods(year=2026, start_month=1, end_month=12):
    periods = []
    for m in range(start_month, end_month + 1):
        periods.append({"key": f"{year}-{m:02d}-1", "start": f"{year}-{m:02d}-01",
                        "end": f"{year}-{m:02d}-15", "type": "quincenal",
                        "label": f"Q1: {m}"})
        periods.append({"key": f"{year}-{m:02d}-2", "start": f"{year}-{m:02d}-16",
                        "end": f"{year}-{m:02d}-28", "type": "quincenal",
                        "label": f"Q2: {m}"})
    return periods


def _period(group_id, key, start, status="borrador", subtype="regular"):
    return {
        "payrollGroupId": group_id,
        "periodKey": key,
        "startDate": start,
        "status": status,
        "periodSubType": subtype,
        "periodRange": key,
    }


GROUP = "g1"


def test_sin_periodos_bloquea_todo_menos_primero_del_anio():
    available = _monthly_periods()
    blocked, label, closed = blocked_period_keys([], available, GROUP)
    assert blocked == {p["key"] for p in available[1:]}
    assert available[0]["key"] not in blocked
    assert label is None
    assert closed == set()


def test_periodo_abierto_bloquea_solo_posteriores():
    periods = [
        _period(GROUP, "2026-01-M", "2026-01-01", status="cerrada"),
        _period(GROUP, "2026-02-M", "2026-02-01", status="cerrada"),
        _period(GROUP, "2026-03-M", "2026-03-01", status="borrador"),
    ]
    available = _monthly_periods()
    blocked, label, closed = blocked_period_keys(periods, available, GROUP)
    assert "2026-03-M" not in blocked
    assert "2026-02-M" not in blocked
    assert "2026-04-M" in blocked
    assert "2026-12-M" in blocked
    assert label == "2026-03-M"
    assert closed == {"2026-01-M", "2026-02-M"}


def test_estados_abiertos_bloquean():
    for status in ("borrador", "calculada", "validada", "aprobada", "pagada",
                   "contabilizada", "reopened"):
        periods = [
            _period(GROUP, "2026-01-M", "2026-01-01", status="cerrada"),
            _period(GROUP, "2026-02-M", "2026-02-01", status=status),
        ]
        blocked, _, _ = blocked_period_keys(periods, _monthly_periods(), GROUP)
        assert "2026-03-M" in blocked, f"status {status} debería bloquear"


def test_todo_cerrado_habilitar_siguiente_al_ultimo_cerrado():
    periods = [
        _period(GROUP, "2026-01-M", "2026-01-01", status="cerrada"),
        _period(GROUP, "2026-02-M", "2026-02-01", status="cerrada"),
    ]
    available = _monthly_periods()
    blocked, label, closed = blocked_period_keys(periods, available, GROUP)
    # El siguiente procesable es marzo; lo posterior queda bloqueado.
    assert "2026-03-M" not in blocked
    assert "2026-04-M" in blocked
    assert "2026-12-M" in blocked
    assert label is None
    assert closed == {"2026-01-M", "2026-02-M"}


def test_todo_cerrado_quincenal_habilita_q1_siguiente():
    periods = [
        _period(GROUP, "2026-01-1", "2026-01-01", status="cerrada"),
        _period(GROUP, "2026-01-2", "2026-01-16", status="cerrada"),
    ]
    available = _quincenal_periods()
    blocked, label, closed = blocked_period_keys(periods, available, GROUP)
    assert "2026-02-1" not in blocked
    assert "2026-02-2" in blocked
    assert "2026-03-1" in blocked
    assert label is None
    assert closed == {"2026-01-1", "2026-01-2"}


def test_cancelled_no_bloquea_y_permite_siguiente():
    periods = [
        _period(GROUP, "2026-01-M", "2026-01-01", status="cancelled"),
    ]
    available = _monthly_periods()
    blocked, _, closed = blocked_period_keys(periods, available, GROUP)
    assert "2026-02-M" not in blocked
    assert "2026-03-M" in blocked
    assert closed == {"2026-01-M"}


def test_subtipos_especiales_no_cuentan_para_boundary():
    periods = [
        _period(GROUP, "2026-01-M", "2026-01-01", status="cerrada"),
        # Regalía/liquidación abierta no debe bloquear la secuencia regular
        _period(GROUP, "2026-12-M", "2026-12-01", status="borrador",
                subtype="christmas_bonus"),
    ]
    available = _monthly_periods()
    blocked, _, _ = blocked_period_keys(periods, available, GROUP)
    # Sin período regular abierto (solo enero cerrado) -> siguiente = febrero
    assert "2026-02-M" not in blocked
    assert "2026-03-M" in blocked


def test_quincenal_orden_cronologico():
    periods = [
        _period(GROUP, "2026-01-1", "2026-01-01", status="cerrada"),
        _period(GROUP, "2026-01-2", "2026-01-16", status="borrador"),
    ]
    available = _quincenal_periods()
    blocked, label, _ = blocked_period_keys(periods, available, GROUP)
    assert "2026-01-1" not in blocked
    assert "2026-01-2" not in blocked
    assert "2026-02-1" in blocked
    assert "2026-02-2" in blocked
    assert label == "2026-01-2"


def test_ignora_periodos_de_otro_grupo():
    periods = [
        _period("otro", "2026-05-M", "2026-05-01", status="borrador"),
    ]
    available = _monthly_periods()
    blocked, _, _ = blocked_period_keys(periods, available, GROUP)
    # El período abierto pertenece a otro grupo -> no afecta a GROUP
    assert "2026-01-M" not in blocked
    assert "2026-02-M" in blocked


def test_sort_key_usa_start_date_antes_que_key():
    assert _sort_key({"startDate": "2026-01-01", "periodKey": "x"}) < \
           _sort_key({"startDate": "2026-02-01", "periodKey": "a"})


if __name__ == "__main__":
    pytest.main([__file__])
