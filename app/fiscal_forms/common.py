"""Infraestructura común para formularios fiscales versionados.

Los motores de cada declaración permanecen separados; este módulo solo
normaliza metadatos, dinero, validaciones y fuentes de conciliación.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY = Decimal("0.01")


def money(value) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def non_negative(value, field: str, errors: list[str]) -> Decimal:
    amount = money(value)
    if amount < 0:
        errors.append(f"{field} no puede ser negativo.")
    return amount


@dataclass(frozen=True)
class FiscalRulesVersion:
    form: str
    version: str
    status: str
    source: str
    effective_from: str = ""
    effective_to: str = ""


@dataclass(frozen=True)
class ReconciliationDifference:
    source: str
    field: str
    declared: str
    source_value: str
    difference: str
    document_ids: tuple = ()
