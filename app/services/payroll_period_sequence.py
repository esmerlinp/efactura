"""Bloqueo secuencial de períodos de nómina y soporte de migración de históricos.

Regla de negocio: no se puede procesar el período N+1 mientras el período N
anterior siga abierto (no cerrado). Solo aplica a nóminas regulares
operativas (periodSubType == "regular"); los tipos especiales (liquidación, regalía
pascual, extraordinaria, retroactiva, vacaciones) quedan exentos.

Períodos Históricos vs. Períodos Operativos:
- Los períodos importados (isHistorical=True, source="import", status="importado")
  representan antecedentes y no bloquean el inicio operativo de la empresa.
- Las empresas pueden configurar un ``initial_live_period`` (ej. "2026-10-M") para
  indicar a partir de qué período comienzan a operar en vivo en VykOne, sin necesidad
  de reconstruir ni cerrar artificialmente los períodos previos.
- Un período operativo se considera "cerrado" cuando su estado es ``cerrada`` o
  ``cancelled``. Cualquier otro estado (borrador, calculada, validada, aprobada,
  pagada, contabilizada, reopened) mantiene el período operativo "abierto" y bloquea
  los siguientes.
"""

# Estados que liberan la secuencia operativa (el período queda cerrado de forma terminal).
PAYROLL_CLOSED_STATUSES = ("cerrada", "cancelled")

# Subtipos exentos del bloqueo secuencial.
EXEMPT_PERIOD_SUBTYPES = (
    "liquidation",
    "christmas_bonus",
    "extraordinary",
    "retroactive",
    "vacation",
)


def _sort_key(period, available_periods: list = None) -> tuple:
    """Orden cronológico estable: (fecha de inicio, clave de período).

    Soporta tanto períodos persistidos (``startDate``/``periodKey``), dicts
    generados por ``_generate_periods`` (``start``/``key``) como strings de clave.
    """
    if isinstance(period, str):
        key = period
        start = ""
        if available_periods:
            for p in available_periods:
                if p.get("key") == key or p.get("periodKey") == key:
                    start = p.get("start") or p.get("startDate") or ""
                    break
        if not start:
            start = key
        return (start, key)

    key = period.get("periodKey") or period.get("key") or ""
    start = (
        period.get("startDate")
        or period.get("start")
        or ""
    )
    if not start and available_periods and key:
        for p in available_periods:
            if p.get("key") == key or p.get("periodKey") == key:
                start = p.get("start") or p.get("startDate") or ""
                break
    if not start:
        start = key
    return (start, key)


def _is_regular(period: dict) -> bool:
    return period.get("periodSubType", "regular") == "regular"


def _is_historical(period: dict) -> bool:
    """True si el período proviene de una migración/importación histórica."""
    return bool(
        period.get("isHistorical")
        or period.get("source") == "import"
        or period.get("status") == "importado"
    )


def get_initial_live_period(company_id: str, group_id: str = None, sandbox: bool = True) -> str | None:
    """Obtiene el primer período operativo configurado para el grupo o la empresa."""
    from app.services import hr_data_service as hr
    if group_id:
        try:
            group = hr.get_payroll_group(company_id, group_id, sandbox=sandbox)
            if group:
                val = group.get("initialLivePeriod") or group.get("initial_live_period")
                if val:
                    return str(val).strip()
        except Exception:
            pass

    try:
        cfg = hr.get_payroll_config(company_id, sandbox=sandbox)
        val = cfg.get("initial_live_period") or cfg.get("initialLivePeriod")
        if val:
            return str(val).strip()
    except Exception:
        pass
    return None


def get_historical_cutoff_period(company_id: str, group_id: str = None, sandbox: bool = True) -> str | None:
    """Obtiene el último período cubierto por histórico importado para el grupo o la empresa."""
    from app.services import hr_data_service as hr
    if group_id:
        try:
            group = hr.get_payroll_group(company_id, group_id, sandbox=sandbox)
            if group:
                val = group.get("historicalCutoffPeriod") or group.get("historical_cutoff_period")
                if val:
                    return str(val).strip()
        except Exception:
            pass

    try:
        cfg = hr.get_payroll_config(company_id, sandbox=sandbox)
        val = cfg.get("historical_cutoff_period") or cfg.get("historicalCutoffPeriod")
        if val:
            return str(val).strip()
    except Exception:
        pass
    return None


def get_payroll_migration_status(company_id: str, sandbox: bool = True) -> str:
    """Obtiene el estado de la migración de nómina ('not_started', 'in_progress', 'completed')."""
    from app.services import hr_data_service as hr
    try:
        cfg = hr.get_payroll_config(company_id, sandbox=sandbox)
        return str(cfg.get("payroll_migration_status") or cfg.get("payrollMigrationStatus") or "not_started")
    except Exception:
        return "not_started"


def set_payroll_migration_config(company_id: str, initial_live_period: str = None,
                                 historical_cutoff_period: str = None,
                                 migration_status: str = None,
                                 sandbox: bool = True) -> dict:
    """Actualiza la configuración de migración de nómina en hr_config/payroll."""
    from app.services import hr_data_service as hr
    cfg = hr.get_payroll_config(company_id, sandbox=sandbox) or {}
    if initial_live_period is not None:
        cfg["initial_live_period"] = initial_live_period
    if historical_cutoff_period is not None:
        cfg["historical_cutoff_period"] = historical_cutoff_period
    if migration_status is not None:
        cfg["payroll_migration_status"] = migration_status
    hr.save_payroll_config(company_id, cfg, sandbox=sandbox)
    return cfg


def blocked_period_keys(periods, available_periods, group_id,
                        initial_live_period: str = None,
                        historical_cutoff_period: str = None):
    """Calcula qué períodos disponibles están bloqueados para un grupo.

    Diferencia períodos operativos de períodos históricos:
    1. Si hay un período operativo regular abierto, bloquea los períodos posteriores.
    2. Si todos los operativos existentes están cerrados, habilita el inmediatamente
       siguiente al último cerrado.
    3. Si no hay operativos previos:
       - Si existe ``initial_live_period``, desbloquea ese período operativo inicial
         y bloquea los anteriores (pre-operativos) y los posteriores.
       - Si no existe pero hay históricos importados, desbloquea el siguiente al
         último histórico.
       - Si no hay ningún registro ni configuración, mantiene el fallback retrocompatible
         desbloqueando el primer período del año.

    Args:
        periods: Lista de todos los períodos de la empresa (dicts con al menos
            ``payrollGroupId``, ``periodKey``, ``startDate``, ``status``,
            ``periodSubType``, ``isHistorical``).
        available_periods: Lista de períodos seleccionables
            ``[{key, start, end, type, label}]`` (salida de ``_generate_periods``).
        group_id: ID del grupo de nómina evaluado.
        initial_live_period: Clave del primer período operativo en vivo (opcional).
        historical_cutoff_period: Clave del último período migrado (opcional).

    Returns:
        ``(blocked_keys: set[str], open_label: str | None, closed_keys: set[str])``
        donde ``blocked_keys`` son los periodKeys deshabilitados, ``open_label``
        es el rótulo del período abierto que hay que cerrar (o ``None``) y
        ``closed_keys`` son los periodKeys ya cerrados o históricos.
    """
    # Filtrar períodos pertenecientes a este grupo o históricos generales
    group_periods = [
        p for p in periods
        if p.get("payrollGroupId") == group_id or (not p.get("payrollGroupId") and _is_historical(p))
    ]
    regular = [p for p in group_periods if _is_regular(p)]

    # Separar operativos de históricos
    operational_regular = [p for p in regular if not _is_historical(p)]
    historical_regular = [p for p in regular if _is_historical(p)]

    # Períodos operativos abiertos
    open_operational = [
        p for p in operational_regular if p.get("status") not in PAYROLL_CLOSED_STATUSES
    ]

    # Conjunto de claves ya cerradas u operadas históricamente
    closed_keys = {
        p.get("periodKey") for p in group_periods
        if p.get("periodKey") and (
            p.get("status") in PAYROLL_CLOSED_STATUSES or _is_historical(p)
        )
    }

    if open_operational:
        # El período operativo abierto más antiguo define el límite actual
        boundary = min(open_operational, key=lambda p: _sort_key(p, available_periods))
        open_label = boundary.get("periodRange") or boundary.get("periodKey") or ""
        boundary_key = _sort_key(boundary, available_periods)
    else:
        open_label = None
        closed_operational = [
            p for p in operational_regular if p.get("status") in PAYROLL_CLOSED_STATUSES
        ]
        if closed_operational:
            latest = max(closed_operational, key=lambda p: _sort_key(p, available_periods))
            latest_key = _sort_key(latest, available_periods)
            # El siguiente período procesable es el primero posterior al último operativo cerrado.
            boundary_key = min(
                (_sort_key(p, available_periods) for p in available_periods if _sort_key(p, available_periods) > latest_key),
                default=None,
            )
        else:
            # Sin períodos operativos previos: evaluar inicio operativo / históricos
            if initial_live_period:
                init_key = _sort_key(initial_live_period, available_periods)
                # Si existen históricos posteriores o iguales a initial_live_period (contradicción),
                # la frontera procesable avanza al período posterior al último histórico
                if historical_regular:
                    latest_hist = max(historical_regular, key=lambda p: _sort_key(p, available_periods))
                    latest_hist_key = _sort_key(latest_hist, available_periods)
                    if latest_hist_key >= init_key:
                        init_key = min(
                            (_sort_key(p, available_periods) for p in available_periods if _sort_key(p, available_periods) > latest_hist_key),
                            default=init_key,
                        )
                boundary_key = min(
                    (_sort_key(p, available_periods) for p in available_periods if _sort_key(p, available_periods) >= init_key),
                    default=init_key,
                )
            elif historical_cutoff_period:
                cutoff_key = _sort_key(historical_cutoff_period, available_periods)
                boundary_key = min(
                    (_sort_key(p, available_periods) for p in available_periods if _sort_key(p, available_periods) > cutoff_key),
                    default=None,
                )
            elif historical_regular:
                latest_hist = max(historical_regular, key=lambda p: _sort_key(p, available_periods))
                latest_hist_key = _sort_key(latest_hist, available_periods)
                boundary_key = min(
                    (_sort_key(p, available_periods) for p in available_periods if _sort_key(p, available_periods) > latest_hist_key),
                    default=None,
                )
            else:
                boundary_key = _sort_key(available_periods[0], available_periods) if available_periods else None

    if boundary_key is None:
        return set(), open_label, closed_keys

    blocked = set()
    for p in available_periods:
        p_key = _sort_key(p, available_periods)
        if p_key > boundary_key:
            blocked.add(p["key"])
        elif initial_live_period and not open_operational and not closed_operational:
            init_key = _sort_key(initial_live_period, available_periods)
            # Si es anterior al período operativo configurado y no fue importado/cerrado,
            # no se permite procesar como nómina operativa
            if p_key < init_key and p["key"] not in closed_keys:
                blocked.add(p["key"])

    return blocked, open_label, closed_keys
