"""PayrollRule — Reglas de cálculo configurables (tipo Fast Formulas)."""

from typing import Optional, List
from pydantic import BaseModel, Field


class RuleCondition(BaseModel):
    """Condición individual de una regla."""
    field: str = ""          # "department", "salary", "position", "seniority_years", etc.
    operator: str = "=="     # "==", "!=", ">", "<", ">=", "<=", "contains", "in", "not_in"
    value: str = ""          # Valor a comparar (todo es string, se parsea según field)


class RuleAction(BaseModel):
    """Acción a ejecutar si las condiciones se cumplen."""
    type: str = "add_concept"  # "set_bonus", "set_commission", "set_deduction", "set_overtime_rate",
                                # "set_other_income", "set_other_deduction", "add_concept"
    conceptCode: str = ""      # Código del concepto de nómina a afectar. Si está vacío, se usa el mapeo
                                # por defecto según el type (ej: set_bonus → BONIFICACION).
    formula: str = ""          # Expresión: "salary * 0.10", "5000", "salary * 0.05 + 2000"
    description: str = ""      # Descripción legible de la acción


class PayrollRule(BaseModel):
    """Regla de cálculo de nómina configurable sin programación."""

    id: str = ""
    name: str = ""
    description: str = ""
    priority: int = 0        # Menor número = mayor prioridad (se evalúa primero)
    scope: str = "global"    # "global", "group", "employee"
    scopeId: str = ""        # group_id o employee_id si scope != global
    logic: str = "AND"       # "AND" | "OR" — cómo combinar múltiples condiciones

    conditions: List[RuleCondition] = Field(default_factory=list)
    actions: List[RuleAction] = Field(default_factory=list)

    isActive: bool = True

    # Metadatos
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""
