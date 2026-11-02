"""Date and time helpers for the Dominican Republic deployment."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


SANTO_DOMINGO = ZoneInfo("America/Santo_Domingo")


def now_santo_domingo() -> datetime:
    """Return the current aware datetime in Santo Domingo."""
    return datetime.now(SANTO_DOMINGO)


def today_santo_domingo() -> date:
    """Return today's date in Santo Domingo."""
    return now_santo_domingo().date()


def today_iso() -> str:
    """Return today's ISO date in Santo Domingo."""
    return today_santo_domingo().isoformat()


def format_local_datetime(value, fmt="%d/%m/%Y %H:%M"):
    """Format an ISO/Firestore timestamp in Santo Domingo local time."""
    if not value:
        return value
    if hasattr(value, "to_datetime"):
        value = value.to_datetime()
    if not isinstance(value, datetime):
        text = str(value).strip()
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SANTO_DOMINGO).strftime(fmt)
