"""HR utility helpers — age calculation, minor detection, and dependent-related."""

from datetime import date as dt_date, datetime


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
