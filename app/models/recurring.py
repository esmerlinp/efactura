"""RecurringMovement — Movimiento recurrente de nómina (unificado: préstamos, embargos, descuentos, ingresos)."""

from pydantic import BaseModel, Field
from typing import Optional


class RecurringMovement(BaseModel):
    """Movimiento recurrente de nómina.

    Unifica:
      - Ingresos recurrentes (incentivos, asignaciones, beneficios)
      - Descuentos recurrentes (préstamos, cooperativas, seguros, ahorros)
      - Embargos (judiciales, pensión alimenticia)
      - Aportes patronales especiales
    """
    id: str = ""
    contractId: str = ""
    employeeId: str = ""
    employeeName: str = ""
    legalEntityId: str = ""

    # ── Concepto ──
    conceptCode: str = ""
    movementType: str = "deduction"  # earning | deduction | employer_contrib
    description: str = ""

    # ── Grupos de nómina (requerido: al menos uno) ──
    payrollGroupIds: list = Field(default_factory=list)

    # ── Monto ──
    amountType: str = "fixed"        # fixed | percentage | formula
    amount: float = 0.0
    percentage: float = 0.0
    formula: str = ""

    # ── Préstamo ──
    isLoan: bool = False
    totalAmount: float = 0.0
    installmentAmount: float = 0.0
    totalInstallments: int = 0
    paidInstallments: int = 0
    remainingBalance: float = 0.0

    # ── Embargo ──
    isGarnishment: bool = False
    garnishmentType: str = ""
    referenceNumber: str = ""
    issuingEntity: str = ""
    beneficiaryName: str = ""
    beneficiaryAccount: str = ""
    deductionType: str = "fixed"       # fixed | percentage | max_of_legal
    deductionPercent: float = 0.0
    maxLegalRate: float = 0.0

    # ── Vigencia ──
    startDate: str = ""
    endDate: str = ""
    indefinite: bool = False

    # ── Frecuencia ──
    applyFrequency: str = "every_period"  # every_period | monthly | specific_months
    applyMonths: list = []

    # ── Control ──
    priority: int = 50
    status: str = "active"            # scheduled | active | paused | completed | cancelled
    autoComplete: bool = True

    # ── Auditoría ──
    notes: str = ""
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""
    auditLog: list = []


class RecurringException(BaseModel):
    """Excepción para omitir o modificar un movimiento recurrente en un período específico."""
    id: str = ""
    recurringMovementId: str = ""
    employeeId: str = ""
    periodKey: str = ""
    action: str = "skip"              # skip | modify
    modifiedAmount: float = 0.0
    reason: str = ""
    createdBy: str = ""
    createdAt: str = ""


class RecurringApplication(BaseModel):
    """Registro de aplicación de un movimiento recurrente en un período de nómina."""
    id: str = ""
    recurringMovementId: str = ""
    employeeId: str = ""
    periodId: str = ""
    periodKey: str = ""
    periodRevision: int = 1
    transactionId: str = ""
    appliedAmount: float = 0.0
    remainingAfter: float = 0.0
    action: str = "applied"           # applied | skipped | modified
    appliedAt: str = ""