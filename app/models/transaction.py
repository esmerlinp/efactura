"""PayrollTransaction — Transacción atómica de nómina por concepto."""

from pydantic import BaseModel, Field
from typing import Optional


class PayrollTransaction(BaseModel):
    """Transacción atómica de nómina — un concepto aplicado a un empleado en un período.

    Almacenada en colección independiente {prefix}hr_payroll_transactions
    para consultas rápidas, reportes y escalabilidad.

    Cada transacción congela el snapshot del concepto al momento de creación
    (conceptSnapshot), garantizando auditoría histórica incluso si el concepto
    cambia años después.
    """
    id: str = ""

    # ── Referencias ──
    periodId: str = ""
    periodKey: str = ""
    payrollLineId: str = ""
    employeeId: str = ""
    contractId: str = ""
    legalEntityId: str = ""
    groupId: str = ""

    # ── Concepto (solo código; el snapshot tiene el resto) ──
    conceptCode: str = ""
    type: str = ""                   # earning | deduction | employer_contrib

    # ── Valor ──
    amount: float = 0.0

    # ── Trazabilidad ──
    source: str = ""                  # system | manual | rule:{ruleId} | recurring:{rmId} | variable:{vmId}
    sourceId: str = ""
    isRecurring: bool = False
    recurringMovementId: str = ""
    periodRevision: int = 0          # PayrollPeriod.revision al momento de crear esta tx

    # ── Estado ──
    status: str = "applied"         # pending | applied | reversed | cancelled | adjusted

    # ── Snapshot inmutable del concepto en el momento de la transacción ──
    conceptSnapshot: dict = Field(default_factory=lambda: {
        "code": "",
        "name": "",
        "type": "",
        "affectsISR": False,
        "affectsTSS": False,
        "affectsNet": True,
        "accountDebit": "",
        "accountCredit": "",
        "conceptVersion": 1,
        "category": "fixed",
        "maxPercentage": 0.0,
    })

    # ── Orden y agrupación ──
    priority: int = 100
    periodYear: int = 0

    # ── Metadatos ──
    notes: str = ""
    createdAt: str = ""
    updatedAt: str = ""


class VariableMovement(BaseModel):
    """Movimiento variable ingresado manualmente para un período específico.

    A diferencia de RecurringMovement, este no se repite ni tiene vigencia.
    Se crea al procesar la nómina y se almacena por separado para trazabilidad.
    """
    id: str = ""
    contractId: str = ""
    employeeId: str = ""
    employeeName: str = ""
    periodId: str = ""
    periodKey: str = ""
    conceptCode: str = ""
    conceptName: str = ""
    type: str = "earning"            # earning | deduction | employer_contrib
    amount: float = 0.0
    notes: str = ""
    createdBy: str = ""
    createdAt: str = ""