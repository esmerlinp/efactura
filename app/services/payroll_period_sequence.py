"""Bloqueo secuencial de períodos de nómina.

Regla de negocio: no se puede procesar el período N+1 mientras el período N
anterior siga abierto (no cerrado). Solo aplica a nóminas regulares
(periodSubType == "regular"); los tipos especiales (liquidación, regalía
pascual, extraordinaria, retroactiva, vacaciones) quedan exentos.

Un período se considera "cerrado" cuando su estado es ``cerrada`` o
``cancelled``. Cualquier otro estado (borrador, calculada, validada, aprobada,
pagada, contabilizada, reopened) mantiene el período "abierto" y bloquea los
siguientes.
"""

# Estados que liberan la secuencia (el período queda cerrado de forma terminal).
PAYROLL_CLOSED_STATUSES = ("cerrada", "cancelled")

# Subtipos exentos del bloqueo secuencial.
EXEMPT_PERIOD_SUBTYPES = (
    "liquidation",
    "christmas_bonus",
    "extraordinary",
    "retroactive",
    "vacation",
)


def _sort_key(period: dict) -> tuple:
    """Orden cronológico estable: (fecha de inicio, clave de período).

    Soporta tanto períodos persistidos (``startDate``/``periodKey``) como
    períodos disponibles generados por ``_generate_periods`` (``start``/``key``).
    """
    start = (
        period.get("startDate")
        or period.get("start")
        or period.get("periodKey")
        or period.get("key")
        or ""
    )
    key = period.get("periodKey") or period.get("key") or ""
    return (start, key)


def _is_regular(period: dict) -> bool:
    return period.get("periodSubType", "regular") == "regular"


def blocked_period_keys(periods, available_periods, group_id):
    """Calcula qué períodos disponibles están bloqueados para un grupo.

    Args:
        periods: Lista de todos los períodos de la empresa (dicts con al menos
            ``payrollGroupId``, ``periodKey``, ``startDate``, ``status`` y
            ``periodSubType``).
        available_periods: Lista de períodos seleccionables
            ``[{key, start, end, type, label}]`` (salida de ``_generate_periods``).
        group_id: ID del grupo de nómina evaluado.

    Returns:
        ``(blocked_keys: set[str], open_label: str | None, closed_keys: set[str])``
        donde ``blocked_keys`` son los periodKeys deshabilitados, ``open_label``
        es el rótulo del período abierto que hay que cerrar (o ``None``) y
        ``closed_keys`` son los periodKeys ya cerrados (para mostrar el
        indicador "(cerrado)" en la UI).
    """
    group_periods = [p for p in periods if p.get("payrollGroupId") == group_id]
    regular = [p for p in group_periods if _is_regular(p)]
    open_regular = [
        p for p in regular if p.get("status") not in PAYROLL_CLOSED_STATUSES
    ]
    closed_keys = {
        p.get("periodKey") for p in group_periods
        if p.get("periodKey") and p.get("status") in PAYROLL_CLOSED_STATUSES
    }

    if open_regular:
        boundary = min(open_regular, key=_sort_key)
        open_label = boundary.get("periodRange") or boundary.get("periodKey") or ""
        boundary_key = _sort_key(boundary)
    else:
        open_label = None
        closed_regular = [
            p for p in regular if p.get("status") in PAYROLL_CLOSED_STATUSES
        ]
        if closed_regular:
            latest = max(closed_regular, key=_sort_key)
            latest_key = _sort_key(latest)
            # El siguiente período procesable es el primero posterior al último cerrado.
            boundary_key = min(
                (_sort_key(p) for p in available_periods if _sort_key(p) > latest_key),
                default=None,
            )
        else:
            boundary_key = _sort_key(available_periods[0]) if available_periods else None

    if boundary_key is None:
        return set(), open_label, closed_keys

    blocked = {
        p["key"] for p in available_periods if _sort_key(p) > boundary_key
    }
    return blocked, open_label, closed_keys
