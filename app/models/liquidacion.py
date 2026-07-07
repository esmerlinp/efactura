"""Modelos Pydantic para Cálculo de Prestaciones Laborales y Derechos Adquiridos (RD).

Basado en:
- Ley 16-92 (Código de Trabajo de la República Dominicana)
- Art. 76 (Preaviso)
- Art. 80 (Cesantía)
- Art. 85 (Salario Diario Promedio)
- Art. 177 y 182 (Vacaciones)
- Art. 219 (Salario de Navidad / Regalía Pascual)
- Ley 87-01 (Seguridad Social) — exenciones TSS
- Norma 08-04 DGII — exenciones ISR
"""

from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional, List
from pydantic import BaseModel, Field

TERMINATION_TYPES = [
    "desahucio_empleador",
    "dimision_justificada",
    "despido_justificado",
    "renuncia",
]

SALARY_FREQUENCIES = [
    "mensual",
    "quincenal",
    "semanal",
    "diario",
]

TIPOS_PRESTACIONES = ["desahucio_empleador", "dimision_justificada"]
TIPOS_SIN_PRESTACIONES = ["despido_justificado", "renuncia"]


class LiquidacionInput(BaseModel):
    employeeId: str = ""
    employeeName: str = ""
    cedula: str = ""
    hireDate: str = ""
    terminationDate: str = ""
    terminationType: str = "renuncia"
    lastBaseSalary: float = 0.0
    salaryFrequency: str = "mensual"
    monthlySalariesLast12: List[float] = Field(default_factory=list)
    monthlySalariesYearToDate: List[float] = Field(default_factory=list)
    preavisoTrabajado: bool = False
    vacationPendingDays: int = 0
    vacationDaysTakenThisPeriod: int = 0


class ConceptoResult(BaseModel):
    aplica: bool = False
    dias: float = 0.0
    monto: float = 0.0
    detalle: str = ""
    exentoTSS: bool = True
    exentoISR: bool = True
    baseLegal: str = ""


class Antiguedad(BaseModel):
    years: int = 0
    months: int = 0
    days: int = 0
    total_months: int = 0


class Totales(BaseModel):
    montoPrestaciones: float = 0.0
    montoDerechosAdquiridos: float = 0.0
    montoTotal: float = 0.0
    montoGravableTSS: float = 0.0
    montoGravableISR: float = 0.0
    montoExento: float = 0.0


class LiquidacionOutput(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    employeeId: str = ""
    employeeName: str = ""
    cedula: str = ""
    hireDate: str = ""
    terminationDate: str = ""
    terminationType: str = ""
    aplicaPrestaciones: bool = False
    antiguedad: Antiguedad = Field(default_factory=Antiguedad)
    salarioDiarioPromedio: float = 0.0
    conceptos: dict = Field(default_factory=dict)
    totales: Totales = Field(default_factory=Totales)
    notas: str = ""
    status: str = "calculada"
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    createdBy: str = ""
    paidAt: Optional[str] = None
