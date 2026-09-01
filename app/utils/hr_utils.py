"""HR utility helpers — age calculation, minor detection, and dependent-related."""

from datetime import date as dt_date, datetime

# Estados de ciclo de vida del empleado (campo `status`)
# "activo" | "inactivo" | "suspendido" | "vacaciones" | "licencia"
# Los tres primeros son gestionados manualmente; "vacaciones" y "licencia"
# son transitorios y los gestiona EmployeeStatusService automáticamente.
EMPLOYEE_LIFECYCLE_STATUSES = ("activo", "inactivo", "suspendido")

# Estados transitorios (gestionados por el motor de solicitudes)
EMPLOYEE_TRANSIENT_STATUSES = ("vacaciones", "licencia")

EMPLOYEE_STATUS_VALUES = EMPLOYEE_LIFECYCLE_STATUSES + EMPLOYEE_TRANSIENT_STATUSES

# Estados en los que el empleado sigue vigente: cobra nómina y se reporta
# en TSS/DGT/IR-13 con normalidad.
ACTIVE_EQUIVALENT_STATUSES = ("activo", "vacaciones", "licencia")


def is_active_equivalent(status: str | None) -> bool:
    """True si el empleado sigue vigente a efectos de nómina, TSS y DGT
    (activo o en vacaciones/licencia transitoria)."""
    return (status or "") in ACTIVE_EQUIVALENT_STATUSES


def calculate_age(birth_date_str: str) -> int:
    """Calcula la edad a partir de una fecha de nacimiento YYYY-MM-DD."""
    if not birth_date_str:
        return 0
    try:
        bd = datetime.strptime(birth_date_str[:10], "%Y-%m-%d").date()
        today = dt_date.today()
        age = today.year - bd.year
        if today.month < bd.month or (today.month == bd.month and today.day < bd.day):
            age -= 1
        return max(0, age)
    except (ValueError, TypeError):
        return 0


def is_minor(birth_date_str: str, adult_age: int = 18) -> bool:
    """Determina si una persona es menor de edad (default < 18 años)."""
    return 0 < calculate_age(birth_date_str) < adult_age


RELATIONSHIP_CATALOG = [
    {"code": "hijo", "name": "Hijo"},
    {"code": "hija", "name": "Hija"},
    {"code": "conyuge", "name": "Cónyuge"},
    {"code": "padre", "name": "Padre"},
    {"code": "madre", "name": "Madre"},
    {"code": "hijastro", "name": "Hijastro"},
    {"code": "hijastra", "name": "Hijastra"},
    {"code": "nieto", "name": "Nieto"},
    {"code": "nieta", "name": "Nieta"},
    {"code": "hermano", "name": "Hermano"},
    {"code": "hermana", "name": "Hermana"},
    {"code": "tutor", "name": "Tutor"},
    {"code": "otro", "name": "Otro"},
]
