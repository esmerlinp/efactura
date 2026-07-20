"""Modelos Pydantic para el módulo de Offboarding (Gestión de Salida de Empleados).

Agregado raíz: TerminationRequest
Entidades satélite: TerminationSettlement, TerminationChecklist, TerminationDocument,
                     TerminationPayment, TerminationInterview, TerminationRiskAssessment,
                     TerminationLegalCase, RehireRequest, TerminationRequestVersion
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from typing import Optional
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# ENUMERACIONES
# ═══════════════════════════════════════════════════════════════════════════

class TerminationType(str, Enum):
    RENUNCIA_VOLUNTARIA      = "renuncia_voluntaria"
    DESAHUCIO_EMPLEADOR      = "desahucio_empleador"
    DIMISION_JUSTIFICADA     = "dimision_justificada"
    DESPIDO_JUSTIFICADO      = "despido_justificado"
    DESPIDO_INJUSTIFICADO    = "despido_injustificado"
    MUTUO_ACUERDO            = "mutuo_acuerdo"
    JUBILACION               = "jubilacion"
    FALLECIMIENTO            = "fallecimiento"
    FIN_CONTRATO_TEMPORAL    = "fin_contrato_temporal"
    ABANDONO                 = "abandono"
    OTRO                     = "otro"


class TerminationStatus(str, Enum):
    DRAFT                       = "draft"
    PENDING_SUPERVISOR_APPROVAL    = "pending_supervisor_approval"
    PENDING_HR_APPROVAL         = "pending_hr_approval"
    APPROVED                    = "approved"
    PENDING_SETTLEMENT          = "pending_settlement"
    PENDING_ASSETS              = "pending_assets"
    PENDING_PAYMENT             = "pending_payment"
    PENDING_DOCUMENTS           = "pending_documents"
    PENDING_TSS                 = "pending_tss"
    COMPLETED                   = "completed"
    CANCELLED                   = "cancelled"
    REJECTED                    = "rejected"


class LegalRiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class PaymentMethod(str, Enum):
    PAYROLL  = "payroll"
    TRANSFER = "transfer"
    CHECK    = "check"
    CASH     = "cash"
    MIXED    = "mixed"


class DocumentType(str, Enum):
    TERMINATION_LETTER     = "termination_letter"
    DISMISSAL_LETTER       = "dismissal_letter"
    RESIGNATION_ACCEPTANCE = "resignation_acceptance"
    SETTLEMENT_ACTA        = "settlement_acta"
    PAYMENT_RECEIPT        = "payment_receipt"
    WORK_CERTIFICATE       = "work_certificate"
    ASSET_RETURN_ACTA      = "asset_return_acta"
    NON_DISCLOSURE         = "non_disclosure"
    SETTLEMENT_AGREEMENT   = "settlement_agreement"
    INTERVIEW_SUMMARY      = "interview_summary"


class ChecklistCategory(str, Enum):
    ASSETS  = "assets"
    ACCESS  = "access"
    DOCS    = "docs"
    UNIFORM = "uniform"
    FINANCE = "finance"
    HR      = "hr"


class SettlementStatus(str, Enum):
    BORRADOR  = "borrador"
    CALCULADA = "calculada"
    APROBADA  = "aprobada"
    PAGADA    = "pagada"


# ═══════════════════════════════════════════════════════════════════════════
# VALUE OBJECTS
# ═══════════════════════════════════════════════════════════════════════════

class StatusChange(BaseModel):
    fromStatus: str = ""
    toStatus: str = ""
    changedBy: str = ""
    changedAt: str = ""
    comment: str = ""
    source: str = "user"


class ApprovalRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    approverEmail: str = ""
    approverName: str = ""
    role: str = ""
    decision: str = ""
    comment: str = ""
    decidedAt: str = ""
    level: int = 1


class ChecklistItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task: str = ""
    category: ChecklistCategory = ChecklistCategory.ASSETS
    description: str = ""
    isMandatory: bool = True
    assignedAssetId: Optional[str] = None
    completed: bool = False
    completedBy: Optional[str] = None
    completedAt: Optional[str] = None
    notes: str = ""
    hasIncident: bool = False
    incidentType: Optional[str] = None
    incidentValue: float = 0.0
    chargeGenerated: bool = False
    chargeAmount: float = 0.0
    signedByEmployee: bool = False
    signedByHR: bool = False


class RiskFactor(BaseModel):
    factor: str = ""
    weight: int = 0
    description: str = ""
    source: str = ""


class EvidenceFile(BaseModel):
    id: str = ""
    fileName: str = ""
    fileType: str = ""
    fileUrl: str = ""
    uploadedBy: str = ""
    uploadedAt: str = ""
    description: str = ""
    category: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# AGREGADO RAÍZ: TERMINATION REQUEST
# ═══════════════════════════════════════════════════════════════════════════

class TerminationRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestNumber: str = ""

    employeeId: str = ""
    employeeName: str = ""
    cedula: str = ""
    departmentId: str = ""
    positionId: str = ""
    supervisorId: str = ""

    requestDate: str = ""
    effectiveDate: str = ""
    lastWorkDate: str = ""
    noticePeriodDays: int = 0

    terminationType: TerminationType = TerminationType.RENUNCIA_VOLUNTARIA
    terminationReason: str = ""
    detailedReason: str = ""
    initiatedBy: str = ""
    initiatedByRole: str = ""

    status: TerminationStatus = TerminationStatus.DRAFT
    riskAssessmentId: Optional[str] = None

    submittedAt: Optional[str] = None
    supervisorApprovedAt: Optional[str] = None
    hrApprovedAt: Optional[str] = None
    settlementCalculatedAt: Optional[str] = None
    settlementApprovedAt: Optional[str] = None
    assetsReturnedAt: Optional[str] = None
    accessRevokedAt: Optional[str] = None
    paidAt: Optional[str] = None
    documentsGeneratedAt: Optional[str] = None
    tssNotifiedAt: Optional[str] = None
    closedAt: Optional[str] = None

    approvalHistory: list[ApprovalRecord] = []

    settlementId: Optional[str] = None
    checklistId: Optional[str] = None
    interviewId: Optional[str] = None
    legalCaseId: Optional[str] = None
    rehireId: Optional[str] = None

    version: int = 1
    createdBy: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedBy: str = ""
    updatedAt: str = ""
    statusHistory: list[StatusChange] = []

    ownerUid: str = ""
    sandbox: bool = True
    tags: list[str] = []


# ═══════════════════════════════════════════════════════════════════════════
# ENTIDADES SATÉLITE
# ═══════════════════════════════════════════════════════════════════════════

class ConceptoResult(BaseModel):
    aplica: bool = False
    dias: Optional[float] = None
    monto: float = 0.0
    detalle: str = ""
    exentoTSS: bool = True
    exentoISR: bool = True
    baseLegal: str = ""


class Totales(BaseModel):
    montoPrestaciones: float = 0.0
    montoDerechosAdquiridos: float = 0.0
    montoSalarioPendiente: float = 0.0
    montoComisiones: float = 0.0
    montoBonificaciones: float = 0.0
    montoHorasExtras: float = 0.0
    montoDescuentos: float = 0.0
    montoBruto: float = 0.0
    montoNeto: float = 0.0
    montoGravableTSS: float = 0.0
    montoGravableISR: float = 0.0
    montoExento: float = 0.0


class TerminationSettlement(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestId: str = ""

    hireDate: str = ""
    terminationDate: str = ""
    terminationType: TerminationType = TerminationType.RENUNCIA_VOLUNTARIA
    baseSalary: float = 0.0
    salaryFrequency: str = "mensual"
    monthlySalariesLast12: list[float] = []
    monthlySalariesYTD: list[float] = []
    preavisoTrabajado: bool = False
    vacationPendingCompleteYears: int = 0
    vacationTakenCurrentPeriod: int = 0

    unpaidDays: int = 0
    pendingCommissions: float = 0.0
    pendingBonuses: float = 0.0
    pendingOvertime: float = 0.0
    loanDeductions: float = 0.0
    advanceDeductions: float = 0.0
    otherDeductions: float = 0.0

    antiguedad: dict = {}
    salarioDiarioPromedio: float = 0.0
    conceptos: dict[str, "ConceptoResult"] = {}
    totales: "Totales" = Field(default_factory=Totales)
    salarioPendiente: float = 0.0
    comisionesPendientes: float = 0.0
    bonificacionesPendientes: float = 0.0
    horasExtrasPendientes: float = 0.0
    descuentos: float = 0.0
    montoNetoAPagar: float = 0.0

    status: SettlementStatus = SettlementStatus.BORRADOR
    version: int = 1
    calculatedBy: str = ""
    calculatedAt: str = ""
    approvedBy: str = ""
    approvedAt: str = ""
    approvalComment: str = ""
    createdAt: str = ""
    updatedAt: str = ""
    previousVersionId: Optional[str] = None


class TerminationChecklist(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestId: str = ""
    employeeId: str = ""
    items: list[ChecklistItem] = []
    totalItems: int = 0
    completedItems: int = 0
    allCompleted: bool = False
    completedAt: Optional[str] = None
    completedBy: Optional[str] = None
    notes: str = ""


class TerminationInterview(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestId: str = ""
    employeeId: str = ""
    interviewDate: str = ""
    interviewerName: str = ""
    interviewerEmail: str = ""
    primaryReason: str = ""
    secondaryReasons: list[str] = []
    workEnvironment: int = 3
    compensation: int = 3
    management: int = 3
    growth: int = 3
    workLifeBalance: int = 3
    whatWentWell: str = ""
    whatCouldImprove: str = ""
    wouldReturn: bool = True
    wouldRecommend: bool = True
    recommendations: str = ""
    documentFile: Optional[str] = None
    createdBy: str = ""
    createdAt: str = ""
    updatedAt: str = ""


class TerminationDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestId: str = ""
    documentType: DocumentType = DocumentType.TERMINATION_LETTER
    documentNumber: str = ""
    title: str = ""
    fileUrl: Optional[str] = None
    fileSize: int = 0
    mimeType: str = "application/pdf"
    signedByEmployer: bool = False
    signedByEmployerAt: Optional[str] = None
    signedByEmployee: bool = False
    signedByEmployeeAt: Optional[str] = None
    signatureMethod: str = ""
    qrCode: Optional[str] = None
    verificationUrl: Optional[str] = None
    verificationCode: str = Field(default_factory=lambda: str(uuid4())[:12].upper())
    generatedBy: str = ""
    generatedAt: str = ""
    templateVersion: str = "1.0"
    language: str = "es"


class TerminationPayment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestId: str = ""
    settlementVersion: int = 1
    paymentMethod: PaymentMethod = PaymentMethod.PAYROLL
    paymentDate: str = ""
    paymentReference: str = ""
    totalAmount: float = 0.0
    conceptBreakdown: dict = {}
    payrollPeriodId: Optional[str] = None
    payrollPeriodKey: Optional[str] = None
    bankName: Optional[str] = None
    accountNumber: Optional[str] = None
    transferReference: Optional[str] = None
    receiptUrl: Optional[str] = None
    receiptNumber: Optional[str] = None
    accountingEntryId: Optional[str] = None
    paidBy: str = ""
    paidAt: str = ""
    approvedBy: str = ""
    approvedAt: str = ""
    notes: str = ""


class TerminationRiskAssessment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestId: str = ""
    riskLevel: LegalRiskLevel = LegalRiskLevel.LOW
    riskScore: int = 0
    riskFactors: list[RiskFactor] = []
    recommendedActions: list[str] = []
    reviewedBy: Optional[str] = None
    reviewedAt: Optional[str] = None
    reviewNotes: str = ""
    assessedBy: str = ""
    assessedAt: str = ""
    updatedAt: str = ""


class TerminationLegalCase(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestId: str = ""
    employeeId: str = ""
    riskAssessmentId: Optional[str] = None
    hasLawsuit: bool = False
    lawsuitDetails: Optional[str] = None
    lawsuitNumber: Optional[str] = None
    lawsuitCourt: Optional[str] = None
    lawsuitDate: Optional[str] = None
    lawsuitStatus: str = ""
    disciplinaryActionIds: list[str] = []
    agreementIds: list[str] = []
    evidenceFiles: list[EvidenceFile] = []
    legalCounselName: Optional[str] = None
    legalCounselEmail: Optional[str] = None
    resolutionDate: Optional[str] = None
    resolutionAmount: float = 0.0
    resolutionNotes: str = ""
    createdBy: str = ""
    createdAt: str = ""
    updatedAt: str = ""
    closedAt: Optional[str] = None


class RehireRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    originalRequestId: str = ""
    originalEmployeeId: str = ""
    newEmployeeId: str = ""
    newHireDate: str = ""
    newPosition: str = ""
    newDepartment: str = ""
    newSalary: float = 0.0
    newContractType: str = ""
    preservesSeniority: bool = False
    previousSeniorityDays: int = 0
    resetBenefits: bool = True
    continuousSeniorityDate: str = ""
    status: str = "draft"
    approvedBy: Optional[str] = None
    approvedAt: Optional[str] = None
    approvalComment: str = ""
    createdBy: str = ""
    createdAt: str = ""
    executedAt: Optional[str] = None


class TerminationRequestVersion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestId: str = ""
    version: int = 1
    snapshot: dict = {}
    diff: dict = {}
    changedBy: str = ""
    changedAt: str = ""
    changeReason: str = ""
    changeSource: str = ""
    sha256: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTES DE CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════

TERMINATION_TYPE_RISK_MAP = {
    TerminationType.RENUNCIA_VOLUNTARIA:      (LegalRiskLevel.LOW, "Renuncia voluntaria del empleado"),
    TerminationType.DESAHUCIO_EMPLEADOR:      (LegalRiskLevel.MEDIUM, "Desahucio ejercido por el empleador"),
    TerminationType.DIMISION_JUSTIFICADA:     (LegalRiskLevel.MEDIUM, "Dimisión justificada del empleado"),
    TerminationType.DESPIDO_JUSTIFICADO:      (LegalRiskLevel.HIGH, "Despido por falta grave comprobada"),
    TerminationType.DESPIDO_INJUSTIFICADO:    (LegalRiskLevel.HIGH, "Despido sin causa justificada"),
    TerminationType.MUTUO_ACUERDO:            (LegalRiskLevel.MEDIUM, "Terminación por mutuo acuerdo"),
    TerminationType.JUBILACION:               (LegalRiskLevel.LOW, "Jubilación del empleado"),
    TerminationType.FALLECIMIENTO:            (LegalRiskLevel.LOW, "Fallecimiento del empleado"),
    TerminationType.FIN_CONTRATO_TEMPORAL:    (LegalRiskLevel.LOW, "Fin de contrato por plazo acordado"),
    TerminationType.ABANDONO:                 (LegalRiskLevel.HIGH, "Abandono voluntario del puesto"),
    TerminationType.OTRO:                     (LegalRiskLevel.MEDIUM, "Otra causa especificada en detalle"),
}

DEFAULT_CHECKLIST_TASKS = [
    {"task": "Devolver laptop/equipo asignado",                     "category": ChecklistCategory.ASSETS,  "isMandatory": True},
    {"task": "Devolver teléfono/celular",                           "category": ChecklistCategory.ASSETS,  "isMandatory": True},
    {"task": "Devolver vehículo asignado",                          "category": ChecklistCategory.ASSETS,  "isMandatory": True},
    {"task": "Devolver herramientas de trabajo",                    "category": ChecklistCategory.ASSETS,  "isMandatory": True},
    {"task": "Devolver uniformes y EPP",                            "category": ChecklistCategory.UNIFORM, "isMandatory": False},
    {"task": "Devolver carnet de identificación",                   "category": ChecklistCategory.HR,      "isMandatory": True},
    {"task": "Devolver llaves de oficina/instalaciones",            "category": ChecklistCategory.ACCESS,  "isMandatory": True},
    {"task": "Entregar credenciales de sistemas",                   "category": ChecklistCategory.ACCESS,  "isMandatory": True},
    {"task": "Liquidar adelantos de sueldo pendientes",             "category": ChecklistCategory.FINANCE, "isMandatory": True},
    {"task": "Firmar acta de devolución de activos",                "category": ChecklistCategory.DOCS,    "isMandatory": True},
    {"task": "Firmar carta de desvinculación",                      "category": ChecklistCategory.DOCS,    "isMandatory": True},
    {"task": "Firmar liquidación y finiquito",                      "category": ChecklistCategory.DOCS,    "isMandatory": True},
]

OFFBOARDING_STATES = {
    "draft": {
        "label": "Borrador",
        "transitions": ["pending_supervisor_approval", "cancelled"],
        "color": "secondary",
        "description": "Inicia el proceso de offboarding. Complete los datos preliminares antes de enviar a revisión.",
    },
    "pending_supervisor_approval": {
        "label": "Pendiente aprobación supervisor",
        "transitions": ["pending_hr_approval", "rejected", "cancelled"],
        "color": "info",
        "description": "Enviar al supervisor inmediato para que revise y apruebe la solicitud de desvinculación.",
    },
    "pending_hr_approval": {
        "label": "Pendiente aprobación RRHH",
        "transitions": ["pending_settlement", "rejected", "cancelled"],
        "color": "warning",
        "description": "El supervisor aprobó. Ahora RRHH debe revisar y validar la solicitud.",
    },
    "approved": {
        "label": "Aprobada",
        "transitions": ["pending_settlement", "cancelled"],
        "color": "primary",
        "description": "Solicitud aprobada por RRHH. Estado histórico — la transición a Pendiente liquidación es automática.",
    },
    "pending_settlement": {
        "label": "Pendiente liquidación",
        "transitions": ["pending_assets", "pending_payment", "cancelled"],
        "color": "info",
        "description": "Calcular liquidación: cesantía, preaviso, vacaciones proporcionales y salarios adeudados.",
    },
    "pending_assets": {
        "label": "Pendiente activos",
        "transitions": ["pending_payment", "cancelled"],
        "color": "warning",
        "description": "Gestionar devolución de activos asignados: laptop, teléfono, uniformes, accesos, etc.",
    },
    "pending_payment": {
        "label": "Pendiente pago",
        "transitions": ["pending_documents", "cancelled"],
        "color": "warning",
        "description": "Procesar el pago de la liquidación y cualquier monto pendiente con el empleado.",
    },
    "pending_documents": {
        "label": "Pendiente documentos",
        "transitions": ["pending_tss", "cancelled"],
        "color": "info",
        "description": "Preparar y gestionar la firma de documentos legales de desvinculación (finiquito, carta de renuncia, etc.).",
    },
    "pending_tss": {
        "label": "Pendiente baja TSS",
        "transitions": ["completed", "cancelled"],
        "color": "info",
        "description": "Realizar la baja del empleado en TSS (AFP, SFS, ARL) y notificar a las entidades correspondientes.",
    },
    "completed": {
        "label": "Completada",
        "transitions": [],
        "color": "success",
        "description": "Proceso de offboarding finalizado. El empleado queda marcado como inactivo en el sistema.",
    },
    "cancelled": {
        "label": "Cancelada",
        "transitions": [],
        "color": "danger",
        "description": "Cancela la solicitud. El empleado permanece activo y el proceso se descarta.",
    },
    "rejected": {
        "label": "Rechazada",
        "transitions": [],
        "color": "danger",
        "description": "Solicitud rechazada. El empleado continúa activo y no se realiza ninguna acción adicional.",
    },
}
