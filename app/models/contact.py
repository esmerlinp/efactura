from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class CustomerCategory(str, Enum):
    NORMAL = "NORMAL"
    GOVERNMENT = "GOVERNMENT"
    SPECIAL_REGIME = "SPECIAL_REGIME"
    FOREIGN = "FOREIGN"


class Contact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    types: list[str] = Field(default_factory=list)
    rnc: str = ""
    razonSocial: str = ""
    email: str = ""
    telefono: str = ""
    telefono2: str = ""
    celular: str = ""
    direccion: str = ""
    municipio: str = ""
    provincia: str = ""
    pais: str = "República Dominicana"
    imageUrl: str = ""
    pipelineStage: str = "Prospecto"
    priceListId: str = ""
    nextContactDate: str = ""
    responsibleId: str = ""
    accessPin: str = ""
    disableAutoReminders: bool = False
    tipoPersona: str = "fisica"
    supplierType: str = "formal"
    creditDays: int = 0
    creditLimit: float = 0.0
    paymentMethod: str = "Efectivo"
    currency: str = "DOP"
    itbisWithholding: bool = False
    isrWithholding: bool = False
    tipoGastoDGII: str = "02"
    ecfTypeEmits: str = "E31"
    customer_category: CustomerCategory = CustomerCategory.NORMAL
    estado: str = "Activo"
    associatedPeople: list = Field(default_factory=list)
    notes: str = ""
    interactions: list = Field(default_factory=list)
    documents: list = Field(default_factory=list)
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
