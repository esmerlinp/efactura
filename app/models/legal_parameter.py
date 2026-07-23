"""LegalParameter — Parámetro legal con vigencia histórica y versionado."""

from pydantic import BaseModel, Field
from typing import Any, Optional


class LegalParameter(BaseModel):
    """Parámetro legal de nómina con vigencia y versionado.

    Almacena un valor histórico (tasa, tabla ISR, tope, % protegido)
    con fecha de vigencia y número de versión para trazabilidad.

    Tipos de parámetros comunes:
      - afp_employee_rate       (float)
      - afp_employer_rate       (float)
      - sfs_employee_rate       (float)
      - sfs_employer_rate       (float)
      - srl_employer_rate       (float)
      - infotep_rate            (float)
      - afp_salary_cap          (float)
      - sfs_salary_cap          (float)
      - min_salary              (float)
      - isr_annual_table        (list[dict])
      - education_deduction     (float)
      - overtime_rate           (float)
      - working_days_per_month  (float)
      - working_hours_per_day   (float)
      - infotep_threshold_multiplier (float)
      - deduction_max_pct       (float)
      - protected_income_pct    (float)
      - pension_max_pct         (float)
      - judicial_max_pct        (float)
      - loan_max_pct            (float)
      - cooperative_max_pct     (float)
    """
    id: str = ""
    parameterType: str = ""
    parameterName: str = ""
    version: int = 1
    value: Any = None
    effectiveFrom: str = ""
    effectiveTo: str = ""
    isActive: bool = True
    legalEntityId: str = ""
    supersedesVersion: int = 0
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""
    notes: str = ""


# Constantes de tipos de parámetros
PARAM_TYPES = {
    "afp_employee_rate": {"type": float, "default": 0.0287},
    "afp_employer_rate": {"type": float, "default": 0.0710},
    "sfs_employee_rate": {"type": float, "default": 0.0304},
    "sfs_employer_rate": {"type": float, "default": 0.0709},
    "srl_employer_rate": {"type": float, "default": 0.0120},
    "infotep_rate": {"type": float, "default": 0.01},
    "afp_salary_cap": {"type": float, "default": 464460.00},
    "sfs_salary_cap": {"type": float, "default": 232230.00},
    "min_salary": {"type": float, "default": 23223.00},
    "education_deduction": {"type": float, "default": 50000.00},
    "overtime_rate": {"type": float, "default": 1.35},
    "working_days_per_month": {"type": float, "default": 23.83},
    "working_hours_per_day": {"type": float, "default": 8.0},
    "infotep_threshold_multiplier": {"type": float, "default": 5.0},
    "deduction_max_pct": {"type": float, "default": 0.30},
    "protected_income_pct": {"type": float, "default": 0.40},
    "pension_max_pct": {"type": float, "default": 0.50},
    "judicial_max_pct": {"type": float, "default": 0.30},
    "loan_max_pct": {"type": float, "default": 0.15},
    "cooperative_max_pct": {"type": float, "default": 0.20},
    "isr_annual_table": {
        "type": list,
        "default": [
            [0.0, 416220.00, 0.0, 0.0],
            [416220.01, 624329.00, 0.15, 0.0],
            [624329.01, 867123.00, 0.20, 31216.00],
            [867123.01, 999999999.0, 0.25, 79775.00],
        ]
    },
}


def get_default_params() -> dict:
    """Retorna un dict con todos los parámetros default (formato get_rates)."""
    return {
        "afp_employee_rate": PARAM_TYPES["afp_employee_rate"]["default"],
        "afp_employer_rate": PARAM_TYPES["afp_employer_rate"]["default"],
        "sfs_employee_rate": PARAM_TYPES["sfs_employee_rate"]["default"],
        "sfs_employer_rate": PARAM_TYPES["sfs_employer_rate"]["default"],
        "srl_employer_rate": PARAM_TYPES["srl_employer_rate"]["default"],
        "infotep_rate": PARAM_TYPES["infotep_rate"]["default"],
        "afp_salary_cap": PARAM_TYPES["afp_salary_cap"]["default"],
        "sfs_salary_cap": PARAM_TYPES["sfs_salary_cap"]["default"],
        "min_salary": PARAM_TYPES["min_salary"]["default"],
        "education_deduction": PARAM_TYPES["education_deduction"]["default"],
        "isr_table": PARAM_TYPES["isr_annual_table"]["default"],
        "isr_annual_table": PARAM_TYPES["isr_annual_table"]["default"],
        "overtime_rate": PARAM_TYPES["overtime_rate"]["default"],
        "working_days_per_month": PARAM_TYPES["working_days_per_month"]["default"],
        "working_hours_per_day": PARAM_TYPES["working_hours_per_day"]["default"],
        "infotep_threshold_multiplier": PARAM_TYPES["infotep_threshold_multiplier"]["default"],
        "deduction_max_pct": PARAM_TYPES["deduction_max_pct"]["default"],
        "protected_income_pct": PARAM_TYPES["protected_income_pct"]["default"],
        "pension_max_pct": PARAM_TYPES["pension_max_pct"]["default"],
        "judicial_max_pct": PARAM_TYPES["judicial_max_pct"]["default"],
        "loan_max_pct": PARAM_TYPES["loan_max_pct"]["default"],
        "cooperative_max_pct": PARAM_TYPES["cooperative_max_pct"]["default"],
    }