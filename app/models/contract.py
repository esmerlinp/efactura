"""EmploymentContract — Contrato laboral como entidad independiente del empleado."""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class EmploymentContract(BaseModel):
    """Contrato laboral de un empleado. Un empleado puede tener múltiples contratos."""

    id: str = ""
    employeeId: str = ""
    legalEntityId: str = ""  # Futuro: multi-razón social

    # Datos contractuales
    contractType: str = ""  # "tiempo_indefinido" | "tiempo_definido" | "por_obra" | ...
    position: str = ""  # Cargo en este contrato
    department: str = ""
    area: str = ""  # "Administrativa", "Operativa", "Ventas", etc.
    costCenter: str = ""  # Centro de costo para contabilidad
    branchId: str = ""  # Sucursal donde trabaja

    # Compensación
    salary: float = 0.0  # Salario base mensual
    salaryType: str = "fijo"  # "fijo" | "por_hora"
    hourlyRate: float = 0.0  # Tarifa por hora si salaryType = "por_hora"
    currency: str = "DOP"

    # Jornada
    workday: str = "completa"  # "completa" | "media_jornada" | "por_horas"
    weeklyHours: int = 44
    workShift: int = 1  # 1=Diurno, 2=Nocturno, 3=Mixto
    isVigilante: bool = False

    # TSS / Seguridad Social
    tssKey: str = ""  # Clave nómina TSS (3 dígitos)
    afpProvider: str = ""  # AFP del empleado para este contrato

    # Vigencia
    startDate: str = ""  # YYYY-MM-DD
    endDate: str = ""  # Vacío = contrato vigente
    probationEndDate: str = ""  # Fin período de prueba

    # Estado
    status: str = "activo"  # "activo" | "terminado" | "suspendido"
    terminationDate: Optional[str] = None
    terminationReason: Optional[str] = None
    terminationType: str = ""  # "renuncia" | "despido" | "mutuo_acuerdo" | "fin_contrato" | "otro"

    # Grupos de nómina donde participa este contrato
    payrollGroupIds: List[str] = []

    # Datos DGT/SIRLA
    occupationCode: str = ""  # Código CNO-2019
    educationLevel: int = 0
    vacationGranted: int = 1

    # Metadatos
    notes: str = ""
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == "activo" and (not self.endDate or self.endDate >= date.today().isoformat())

    @property
    def is_terminated(self) -> bool:
        return self.status == "terminado"

    @property
    def daily_salary(self) -> float:
        if self.salaryType == "por_hora":
            return self.hourlyRate * 8
        return round(self.salary / 23.83, 2)

    def to_dict(self) -> dict:
        return self.model_dump()


class ContractGroupAssignment(BaseModel):
    """Asignación de un contrato a un grupo de nómina con salario y parámetros específicos."""

    id: str = ""
    contractId: str = ""
    groupId: str = ""

    # Salario asignado para este contrato en este grupo (puede diferir del salary del contrato)
    assignedSalary: float = 0.0
    costCenter: str = ""  # Centro de costo específico para este grupo
    position: str = ""  # Cargo en este grupo (puede diferir)

    # Período de vigencia de esta asignación
    effectiveFrom: str = ""
    effectiveTo: str = ""  # Vacío = vigente

    # Metadatos
    createdBy: str = ""
    createdAt: str = ""
