"""Utilidades centralizadas para el control de límites y políticas de sobreconsumo en planes."""

RESOURCE_KEYS = ["employees", "users", "branches", "warehouses", "boxes", "documents"]

RESOURCE_LABELS = {
    "employees": "Empleados en Nómina",
    "users": "Usuarios / Colaboradores",
    "branches": "Sucursales",
    "warehouses": "Almacenes",
    "boxes": "Cajas POS",
    "documents": "Documentos Fiscales (e-CF)",
}


def _to_bool(val) -> bool:
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def is_resource_excess_blocked(company_or_profile: dict, resource_key: str) -> bool:
    """
    Retorna True si la empresa tiene bloqueada la creación de registros adicionales
    para este concepto al alcanzar el cupo contratado del plan.
    Por defecto retorna False (desbloqueado / permite sobreconsumo con cargo adicional).
    """
    if not company_or_profile or not isinstance(company_or_profile, dict):
        return False

    controls = company_or_profile.get("excess_controls") or company_or_profile.get("excessControls") or {}
    if isinstance(controls, dict) and resource_key in controls:
        return _to_bool(controls[resource_key])

    # Fallback plano
    return _to_bool(company_or_profile.get(f"block_excess_{resource_key}", False))

