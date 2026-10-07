from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


CRM_OPPORTUNITY_STAGES = [
    "Prospecto",
    "Contactado",
    "Calificado",
    "Propuesta",
    "Negociación",
    "Ganada",
    "Perdida",
]

CRM_STAGE_PROBABILITY = {
    "Prospecto": 10,
    "Contactado": 20,
    "Calificado": 35,
    "Propuesta": 55,
    "Negociación": 75,
    "Ganada": 100,
    "Perdida": 0,
}

CRM_ACTIVITY_TYPES = [
    "Llamada",
    "Email",
    "Reunión",
    "Tarea",
    "WhatsApp",
    "Seguimiento",
    "Cobranza",
    "Nota",
]

CRM_ACTIVITY_PRIORITIES = ["baja", "media", "alta", "urgente"]
CRM_ACTIVITY_STATUSES = ["pendiente", "completada", "cancelada"]
CRM_OPPORTUNITY_STATUSES = ["abierta", "ganada", "perdida"]

VALID_OPPORTUNITY_TRANSITIONS = {
    "Prospecto": ["Contactado", "Perdida"],
    "Contactado": ["Calificado", "Perdida"],
    "Calificado": ["Propuesta", "Perdida"],
    "Propuesta": ["Negociación", "Ganada", "Perdida"],
    "Negociación": ["Ganada", "Perdida"],
    "Ganada": ["Propuesta", "Negociación"],  # Reapertura controlada
    "Perdida": ["Prospecto", "Contactado", "Calificado", "Propuesta", "Negociación"],  # Reapertura controlada
}

CONTACT_PIPELINE_MAP = {
    "Prospecto": "Prospecto",
    "Contactado": "Contactado",
    "Calificado": "Calificado",
    "Propuesta": "Propuesta",
    "Negociación": "En Negociación",
    "Ganada": "Cliente Activo",
    "Perdida": "Expirado",
}


class CRMOpportunity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    companyId: str = ""
    branchId: str = "default-sucursal-principal"
    projectId: str | None = None
    contactId: str = ""
    contactName: str = ""
    title: str = ""
    stage: str = "Prospecto"
    status: str = "abierta"
    amount: float = 0.0
    probability: int = 10
    expectedCloseDate: str = ""
    source: str = "Manual"
    assignedTo: str = ""
    assignedToName: str = ""
    quotationId: str = ""
    quotationNumber: str = ""
    invoiceId: str = ""
    invoiceNumber: str = ""
    invoices: list[dict] = Field(default_factory=list)
    lostReason: str = ""
    stageHistory: list[dict] = Field(default_factory=list)
    notes: str = ""
    isDeleted: bool = False
    deletedAt: str = ""
    deletedBy: str = ""
    createdBy: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    closedAt: str = ""


class CRMActivity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    companyId: str = ""
    branchId: str = "default-sucursal-principal"
    projectId: str | None = None
    contactId: str = ""
    contactName: str = ""
    opportunityId: str = ""
    opportunityTitle: str = ""
    type: str = "Tarea"
    title: str = ""
    description: str = ""
    dueDate: str = ""
    priority: str = "media"
    status: str = "pendiente"
    assignedTo: str = ""
    assignedToName: str = ""
    completedAt: str = ""
    isDeleted: bool = False
    deletedAt: str = ""
    deletedBy: str = ""
    createdBy: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CRMAutomationRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    name: str = ""
    trigger: str = "stage_change"
    fromStage: str = ""
    toStage: str = ""
    action: str = "create_activity"
    activityType: str = "Seguimiento"
    activityTitle: str = ""
    daysOffset: int = 1
    enabled: bool = True
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CRMMetricSnapshot(BaseModel):
    openOpportunities: int = 0
    wonOpportunities: int = 0
    lostOpportunities: int = 0
    pipelineValue: float = 0.0
    weightedPipelineValue: float = 0.0
    overdueActivities: int = 0
    todayActivities: int = 0
    leadCount: int = 0
    winRate: float = 0.0
