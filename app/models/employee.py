"""Modelos Pydantic para RRHH: Employee, Attendance, Vacation, Leave, Payroll, Evaluation, Training."""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class Employee(BaseModel):
    """Empleado — datos personales, laborales y de TSS."""
    id: str = ""
    idType: str = "cedula"  # "cedula" | "rnc" | "pasaporte"
    cedula: str = ""  # RNC/Cédula (11 dígitos sin guiones)
    idNumber: str = ""  # Número de identificación (general)
    firstName: str = ""  # Primer nombre
    middleName: str = ""  # Segundo nombre
    lastName: str = ""  # (legacy, se mantiene compatibilidad)
    firstLastName: str = ""  # Primer apellido
    secondLastName: str = ""  # Segundo apellido
    fullName: str = ""  # autocompletado
    position: str = ""  # Cargo
    department: str = ""  # Departamento (legacy)
    area: str = ""  # Área (Administrativa, Operativa, Ventas, etc.)
    costCenter: str = ""  # Centro de costo (ej. "CC-Ventas")
    branchId: str = ""  # Sucursal
    hireDate: str = ""  # Fecha ingreso (YYYY-MM-DD)
    baseSalary: float = 0.0  # Salario base mensual
    salaryType: str = "fijo"  # "fijo" | "por_hora"
    salary: float = 0.0  # Valor salario (alias for baseSalary)
    hourlyRate: float = 0.0  # Tarifa por hora (si aplica)
    status: str = "activo"  # "activo" | "inactivo" | "suspendido"
    email: str = ""
    phone: str = ""
    address: str = ""
    municipality: str = ""  # Municipio
    emergencyContact: str = ""
    emergencyPhone: str = ""

    # Datos personales adicionales
    gender: str = ""  # "masculino" | "femenino" | "otro"
    birthDate: str = ""  # YYYY-MM-DD
    probationEndDate: str = ""  # Fin período de prueba

    # Datos contractuales
    contractType: str = ""  # "tiempo_indefinido" | "tiempo_definido" | ...
    workday: str = "completa"  # "completa" | "media_jornada" | ...
    isVigilante: bool = False  # ¿Trabaja como vigilante?
    tssKey: str = ""  # Clave nómina TSS (3 dígitos)

    # Datos de pago
    paymentMethod: str = ""  # "transferencia" | "cheque" | "efectivo" | "deposito"
    accountNumber: str = ""  # Número de cuenta del empleado
    bank: str = ""  # Banco
    accountType: str = ""  # "ahorro" | "corriente"

    # Datos TSS (seguridad social)
    afpProvider: str = ""  # AFP (ej: AFP Popular, Siembra, etc.)
    afpSalaryCap: float = 0.0  # Salario tope AFP (máximo cotizable)
    sfsSalaryCap: float = 0.0  # Tope SFS
    tssRegistrationNumber: str = ""  # Número registro TSS

    # Jerarquía
    reportsTo: str = ""  # Employee ID del supervisor directo

    # Datos DGT/SIRLA
    nationality: int = 1  # Código de país (1 = Dominicana)
    maritalStatus: str = ""  # Estado civil: S/Soltero, C/Casado, U/Unión Libre, D/Divorciado, V/Viudo
    occupationCode: str = ""  # Código CNO-2019 (4 dígitos, catálogo oficial MT)
    weeklyHours: int = 44  # Horas semanales contratadas (max 44)
    workShift: int = 1  # Turno: 1=Diurno, 2=Nocturno, 3=Mixto
    educationLevel: int = 0  # Grado instrucción: 1=Primaria, 2=Secundaria, 3=Técnico, 4=Grado, 5=Postgrado, 6=Ninguno
    vacationGranted: int = 1  # Concesión vacaciones: 1=Tomará en el año, 2=Ya las tomó

    # Bajas
    terminationDate: Optional[str] = None
    terminationReason: Optional[str] = None
    terminationType: str = ""  # "renuncia" | "despido" | "mutuo_acuerdo" | "fin_contrato" | "otro"

    # Nóminas múltiples
    payrollGroupIds: List[str] = []  # IDs de grupos de nómina a los que pertenece

    notes: str = ""

    @property
    def display_name(self) -> str:
        parts = [self.firstName, self.middleName, self.firstLastName, self.secondLastName]
        name = " ".join(p for p in parts if p)
        return name or self.fullName or f"{self.firstName} {self.lastName}".strip()


class Dependent(BaseModel):
    """Dependiente de un empleado — hijos, cónyuge, padres, etc."""
    id: str = ""
    employeeId: str = ""
    firstName: str = ""
    middleName: str = ""
    firstLastName: str = ""
    secondLastName: str = ""

    @property
    def full_name(self) -> str:
        parts = [self.firstName, self.middleName, self.firstLastName, self.secondLastName]
        return " ".join(p for p in parts if p)

    relationshipCode: str = ""  # "hijo" | "hija" | "conyuge" | "padre" | "madre" | "otro"
    relationshipName: str = ""  # Nombre del parentesco desde catálogo
    birthDate: str = ""  # YYYY-MM-DD
    gender: str = ""  # "masculino" | "femenino" | "otro"
    isStudent: bool = False
    isFinancialDependent: bool = True
    active: bool = True
    endDate: str = ""  # Fecha fin de dependencia (si aplica)
    idNumber: str = ""  # Cédula opcional del dependiente
    notes: str = ""
    createdAt: str = ""
    createdBy: str = ""
    updatedAt: str = ""
    updatedBy: str = ""


class AttendanceRecord(BaseModel):
    """Registro de asistencia diaria."""
    id: str = ""
    employeeId: str = ""
    employeeName: str = ""
    date: str = ""  # YYYY-MM-DD
    checkIn: str = ""  # HH:MM
    checkOut: str = ""  # HH:MM
    status: str = "presente"  # "presente" | "ausente" | "tardia" | "permiso"
    notes: str = ""


class VacationRequest(BaseModel):
    """Solicitud de vacaciones."""
    id: str = ""
    employeeId: str = ""
    employeeName: str = ""
    startDate: str = ""  # YYYY-MM-DD
    endDate: str = ""  # YYYY-MM-DD
    days: int = 0  # Días hábiles solicitados
    status: str = "pendiente"  # "pendiente" | "aprobada" | "rechazada"
    approvedBy: str = ""
    approvedDate: str = ""
    remainingDaysBefore: int = 0  # Saldo de vacaciones antes de esta solicitud
    notes: str = ""
    createdDate: str = ""


class LeaveRequest(BaseModel):
    """Permiso o licencia laboral."""
    id: str = ""
    employeeId: str = ""
    employeeName: str = ""
    leaveType: str = "otro"  # "maternidad" | "enfermedad" | "sindical" | "luto" | "otro"
    startDate: str = ""
    endDate: str = ""
    days: int = 0
    status: str = "pendiente"  # "pendiente" | "aprobada" | "rechazada"
    approvedBy: str = ""
    notes: str = ""


class PayrollLine(BaseModel):
    """Línea de nómina por empleado en un período."""
    employeeId: str = ""
    employeeName: str = ""
    cedula: str = ""
    position: str = ""
    department: str = ""
    baseSalary: float = 0.0

    # Ingresos
    grossSalary: float = 0.0
    overtimeHours: float = 0.0
    overtimePay: float = 0.0
    overtimeBreakdown: dict = Field(default_factory=dict)
    commission: float = 0.0
    bonus: float = 0.0  # Bonificación
    otherIncome: float = 0.0

    # Descuentos al empleado
    afpEmployee: float = 0.0  # 2.87%
    sfsEmployee: float = 0.0  # 3.04%
    infotepEmployee: float = 0.0  # 1% (si gana >5x salario mínimo)
    isrRetention: float = 0.0  # Según tabla DGII
    otherDeductions: float = 0.0  # Préstamos, anticipos, etc.

    # Neto
    totalIncome: float = 0.0
    totalDeductions: float = 0.0
    netSalary: float = 0.0

    # Aportes empleador (no son descuentos al empleado, son gasto para la empresa)
    afpEmployer: float = 0.0  # 7.10%
    sfsEmployer: float = 0.0  # 7.09%
    srlEmployer: float = 0.0  # 1.20%
    infotepEmployer: float = 0.0  # 1%
    totalEmployerContrib: float = 0.0


class PayrollGroup(BaseModel):
    """Grupo de nómina — permite múltiples nóminas con distintos períodos y configuraciones."""
    id: str = ""
    name: str = ""  # "Administrativa", "Producción", etc.
    description: str = ""
    frequency: str = "mensual"  # "quincenal" | "mensual"
    isActive: bool = True
    policyId: str = ""  # ID de PayrollPolicy asignada (vacío = usar default)
    policyOverrides: dict = {}  # Sobrescrituras parciales de la política (PolicyOverride)
    overtimeRules: dict = {}  # {"default_rate": 1.35, "night_rate": 2.0, "holiday_rate": 2.5}
    deductionRules: dict = {}  # {"max_loan_pct": 0.20, "max_garnishment_pct": 0.30}
    createdAt: str = ""
    updatedAt: str = ""
    createdBy: str = ""


class PayrollPeriod(BaseModel):
    """Período de nómina."""
    id: str = ""
    payrollGroupId: str = ""  # "" = grupo por defecto (compatibilidad)
    legalEntityId: str = ""  # Para multiempresa futuro
    periodKey: str = ""  # "2026-07" o "2026-01-15"
    periodType: str = "mensual"  # "quincenal" | "mensual"
    periodSubType: str = "regular"  # regular | christmas_bonus | extraordinary | retroactive | vacation | liquidation
    periodRange: str = ""  # "1 Ene - 15 Ene"
    startDate: str = ""  # Fecha inicio del período trabajado (YYYY-MM-DD)
    endDate: str = ""  # Fecha fin del período trabajado (YYYY-MM-DD)
    scheduledPaymentDate: str = ""  # Fecha planificada de pago (YYYY-MM-DD)
    month: int = 0
    year: int = 0
    revision: int = 1  # Se incrementa cada vez que se recalcula el período
    status: str = "borrador"  # borrador | calculada | validada | aprobada | contabilizada | pagada | cerrada | reopened | cancelled
    lines: List[PayrollLine] = []
    totalGross: float = 0.0
    totalNet: float = 0.0
    totalEmployerContrib: float = 0.0
    processedDate: str = ""
    paidDate: str = ""
    notes: str = ""

    # Workflow tracking
    calculatedBy: str = ""
    calculatedAt: str = ""
    validatedBy: str = ""
    validatedAt: str = ""
    approvedBy: str = ""
    approvedAt: str = ""
    postedBy: str = ""
    postedAt: str = ""
    paidBy: str = ""
    paidAt: str = ""
    closedBy: str = ""
    closedAt: str = ""
    statusHistory: List[dict] = []  # [{"from": "borrador", "to": "calculada", "by": "...", "at": "...", "comment": ""}]

    # Snapshot de empleados al momento del cálculo (para DGT-4)
    employeeSnapshot: List[dict] = []  # Lista de empleados activos con sus datos al corte

    # Snapshot inmutable de tasas usadas para calcular este período
    taxRatesSnapshot: dict = {}  # Copia de tax_rates al momento del cálculo
    appliedRatesDate: str = ""  # ISO date de cuándo se aplicaron las tasas
    parameterVersions: dict = {}  # {"afp_employee_rate": "param_id_123_v2", ...} — IDs + versión de cada parámetro usado

    # Nómina especial: referencia al período padre (para retroactivos)
    parentPeriodId: str = ""
    specialNotes: str = ""


class Evaluation(BaseModel):
    """Evaluación de desempeño."""
    id: str = ""
    employeeId: str = ""
    employeeName: str = ""
    date: str = ""
    evalType: str = "anual"  # "periodica" | "anual"
    score: float = 3.0  # 1-5
    strengths: str = ""
    improvements: str = ""
    evaluatorName: str = ""
    notes: str = ""


class Training(BaseModel):
    """Capacitación registrada."""
    id: str = ""
    employeeId: str = ""
    employeeName: str = ""
    trainingName: str = ""
    institution: str = ""
    date: str = ""
    hours: int = 0
    hasCertificate: bool = False
    notes: str = ""


class SalaryHistory(BaseModel):
    """Historial de cambios salariales de un empleado."""
    id: str = ""
    employeeId: str = ""
    amount: float = 0.0
    previousAmount: float = 0.0
    effectiveDate: str = ""  # YYYY-MM-DD
    endDate: str = ""  # YYYY-MM-DD, vacío mientras esté vigente
    reason: str = ""
    approvedBy: str = ""
    createdAt: str = ""
    payrollPeriodKey: str = ""  # Período de nómina al que aplica (ej: "2026-08-1")


class MassAction(BaseModel):
    """Acción de personal masiva con workflow de aprobación."""
    ACTION_TYPES = (
        "salary_change",
        "position_change",
        "supervisor_change",
        "promotion",
        "mass_absence",
    )
    STATUSES = ("draft", "pending_approval", "approved", "rejected", "processing", "completed", "partial", "failed")

    id: str = ""
    actionType: str = "salary_change"
    status: str = "draft"
    createdBy: str = ""
    createdAt: str = ""
    submittedAt: str = ""
    approvedBy: str = ""
    approvedAt: str = ""
    rejectedBy: str = ""
    rejectedAt: str = ""
    rejectionReason: str = ""
    processedAt: str = ""
    ownerUid: str = ""
    sandbox: bool = True

    selectionCriteria: dict = {}
    totalEmployees: int = 0
    successCount: int = 0
    errorCount: int = 0

    payload: dict = {}
    results: list = []
    errorLog: list = []
    statusHistory: list = []  # [{from, to, by, at, comment}]

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_executable(self) -> bool:
        return self.status in ("approved", "draft")


class MassActionResult(BaseModel):
    """Resultado por empleado en una acción masiva."""
    employeeId: str = ""
    employeeName: str = ""
    status: str = ""  # "success" | "error" | "skipped"
    errorMessage: str = ""
    changes: dict = {}
    processedAt: str = ""


class MassActionError(BaseModel):
    """Error individual de una acción masiva."""
    employeeId: str = ""
    employeeName: str = ""
    field: str = ""
    message: str = ""
