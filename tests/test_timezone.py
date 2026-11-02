from datetime import datetime, timezone

from app.utils.timezone import (
    SANTO_DOMINGO,
    format_local_datetime,
    today_santo_domingo,
)


def test_santo_domingo_is_four_hours_behind_utc_in_winter():
    value = datetime(2026, 1, 15, 3, 30, tzinfo=timezone.utc)
    assert value.astimezone(SANTO_DOMINGO).strftime("%Y-%m-%d %H:%M") == "2026-01-14 23:30"


def test_format_local_datetime_converts_utc_iso_timestamp():
    assert format_local_datetime("2026-01-15T03:30:00+00:00") == "14/01/2026 23:30"


def test_today_is_a_date_in_santo_domingo():
    assert today_santo_domingo().isoformat()
