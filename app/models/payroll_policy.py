"""PayrollPolicy — Política de nómina con reglas de cálculo, tasas y cuentas contables."""

from typing import List, Optional
from pydantic import BaseModel, Field


class PayrollPolicy(BaseModel):
    """Política de nómina: agrupa todas las reglas de cálculo, tasas y cuentas contables.

    Una política puede asignarse a uno o más PayrollGroup. Si un grupo no tiene
    política asignada, se usa la política marcada como `isDefault=True`.
    """

    id: str = ""
    name: str = ""
    description: str = ""
    isDefault: bool = False

    # ── Tasas de seguridad social ──
    afpEmployeeRate: float = 0.0287
    afpEmployerRate: float = 0.0710
    sfsEmployeeRate: float = 0.0304
    sfsEmployerRate: float = 0.0709
    srlEmployerRate: float = 0.0120
    infotepRate: float = 0.01

    # ── Topes cotizables ──
    afpSalaryCap: float = 464460.00
    sfsSalaryCap: float = 232230.00
    infotepThresholdMultiplier: float = 5.0  # Múltiplo del salario mínimo
    minSalary: float = 23223.00

    # ── ISR ──
    isrAnnualTable: list = Field(default_factory=lambda: [
        [0.0, 416220.00, 0.0, 0.0],
        [416220.01, 624329.00, 0.15, 0.0],
        [624329.01, 867123.00, 0.20, 31216.00],
        [867123.01, float("inf"), 0.25, 79775.00],
    ])
    educationDeduction: float = 50000.00

    # ── Parámetros de cálculo ──
    overtimeRate: float = 1.35
    workingDaysPerMonth: float = 23.83
    workingHoursPerDay: float = 8.0

    # ── Cuentas contables ──
    accountSalariesPayable: str = "2.1.2.1.02"
    accountAfpEmployee: str = "2.1.2.1.05"
    accountSfsEmployee: str = "2.1.2.1.06"
    accountIsrEmployee: str = "2.1.2.1.08"
    accountAfpEmployer: str = "2.1.2.1.10"
    accountSfsEmployer: str = "2.1.2.1.09"
    accountSrlEmployer: str = "2.1.2.1.11"
    accountInfotepEmployer: str = "2.1.2.1.12"
    accountInfotepEmployee: str = "2.1.2.1.12"
    accountOtherDeductions: str = "2.1.2.1.13"

    costCenterAccounts: dict = Field(default_factory=lambda: {
        "General": "6.2.1.01",
        "Ventas": "6.2.1.01.01",
        "Produccion": "6.2.1.01.02",
        "Administrativa": "6.2.1.01.03",
    })

    # ── País (para multi-país futuro) ──
    country: str = "DO"
    currency: str = "DOP"

    # ── Metadatos ──
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""

    def to_rates_dict(self) -> dict:
        """Convierte la política al formato esperado por PayrollService.get_rates()."""
        return {
            "afp_employee_rate": self.afpEmployeeRate,
            "afp_employer_rate": self.afpEmployerRate,
            "sfs_employee_rate": self.sfsEmployeeRate,
            "sfs_employer_rate": self.sfsEmployerRate,
            "srl_employer_rate": self.srlEmployerRate,
            "infotep_rate": self.infotepRate,
            "afp_salary_cap": self.afpSalaryCap,
            "sfs_salary_cap": self.sfsSalaryCap,
            "min_salary": self.minSalary,
            "education_deduction": self.educationDeduction,
            "isr_table": self.isrAnnualTable,
            "overtime_rate": self.overtimeRate,
            "working_days_per_month": self.workingDaysPerMonth,
            "working_hours_per_day": self.workingHoursPerDay,
            "infotep_threshold_multiplier": self.infotepThresholdMultiplier,
            "account_salaries_payable": self.accountSalariesPayable,
            "account_afp_employee": self.accountAfpEmployee,
            "account_sfs_employee": self.accountSfsEmployee,
            "account_isr_employee": self.accountIsrEmployee,
            "account_afp_employer": self.accountAfpEmployer,
            "account_sfs_employer": self.accountSfsEmployer,
            "account_srl_employer": self.accountSrlEmployer,
            "account_infotep_employer": self.accountInfotepEmployer,
            "account_infotep_employee": self.accountInfotepEmployee,
            "account_other_deductions": self.accountOtherDeductions,
            "cost_center_accounts": self.costCenterAccounts,
        }


class PolicyOverride(BaseModel):
    """Sobrescritura parcial de una política para un grupo o empleado específico.

    Solo los campos no-None se aplican como override. None = hereda del nivel superior.
    """

    # Tasas
    afpEmployeeRate: Optional[float] = None
    afpEmployerRate: Optional[float] = None
    sfsEmployeeRate: Optional[float] = None
    sfsEmployerRate: Optional[float] = None
    srlEmployerRate: Optional[float] = None
    infotepRate: Optional[float] = None

    # Topes
    afpSalaryCap: Optional[float] = None
    sfsSalaryCap: Optional[float] = None
    infotepThresholdMultiplier: Optional[float] = None
    minSalary: Optional[float] = None

    # ISR
    isrAnnualTable: Optional[list] = None
    educationDeduction: Optional[float] = None

    # Cálculo
    overtimeRate: Optional[float] = None
    workingDaysPerMonth: Optional[float] = None
    workingHoursPerDay: Optional[float] = None

    # Cuentas contables
    accountSalariesPayable: Optional[str] = None
    accountAfpEmployee: Optional[str] = None
    accountSfsEmployee: Optional[str] = None
    accountIsrEmployee: Optional[str] = None
    accountAfpEmployer: Optional[str] = None
    accountSfsEmployer: Optional[str] = None
    accountSrlEmployer: Optional[str] = None
    accountInfotepEmployer: Optional[str] = None
    accountInfotepEmployee: Optional[str] = None
    accountOtherDeductions: Optional[str] = None
    costCenterAccounts: Optional[dict] = None

    def apply_to(self, base: dict) -> dict:
        """Aplica los overrides no-None sobre un dict base (formato get_rates)."""
        result = dict(base)
        mapping = {
            "afp_employee_rate": self.afpEmployeeRate,
            "afp_employer_rate": self.afpEmployerRate,
            "sfs_employee_rate": self.sfsEmployeeRate,
            "sfs_employer_rate": self.sfsEmployerRate,
            "srl_employer_rate": self.srlEmployerRate,
            "infotep_rate": self.infotepRate,
            "afp_salary_cap": self.afpSalaryCap,
            "sfs_salary_cap": self.sfsSalaryCap,
            "min_salary": self.minSalary,
            "education_deduction": self.educationDeduction,
            "isr_table": self.isrAnnualTable,
            "overtime_rate": self.overtimeRate,
            "working_days_per_month": self.workingDaysPerMonth,
            "working_hours_per_day": self.workingHoursPerDay,
            "infotep_threshold_multiplier": self.infotepThresholdMultiplier,
            "account_salaries_payable": self.accountSalariesPayable,
            "account_afp_employee": self.accountAfpEmployee,
            "account_sfs_employee": self.accountSfsEmployee,
            "account_isr_employee": self.accountIsrEmployee,
            "account_afp_employer": self.accountAfpEmployer,
            "account_sfs_employer": self.accountSfsEmployer,
            "account_srl_employer": self.accountSrlEmployer,
            "account_infotep_employer": self.accountInfotepEmployer,
            "account_infotep_employee": self.accountInfotepEmployee,
            "account_other_deductions": self.accountOtherDeductions,
            "cost_center_accounts": self.costCenterAccounts,
        }
        for key, value in mapping.items():
            if value is not None:
                result[key] = value
        return result
