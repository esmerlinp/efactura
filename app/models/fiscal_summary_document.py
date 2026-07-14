from datetime import datetime, timezone
from uuid import uuid4
from pydantic import BaseModel, Field


class FiscalSummaryDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    documentType: str = "RUI"
    businessDate: str = ""
    ncf: str = ""
    sequenceLogId: str = ""
    sequenceType: str = "B12"
    estado: str = "ACTIVO"
    cancelledBy: str = ""
    cancelledAt: str = ""
    cancelReason: str = ""
    replacementRuiId: str = ""
    totalGravado18: float = 0.0
    totalGravado16: float = 0.0
    totalExento: float = 0.0
    totalItbis18: float = 0.0
    totalItbis16: float = 0.0
    totalVentas: float = 0.0
    cantidadTransacciones: int = 0
    taxSnapshot: dict = Field(default_factory=lambda: {
        "gravado18": 0.0,
        "itbis18": 0.0,
        "gravado16": 0.0,
        "itbis16": 0.0,
        "exento": 0.0,
        "total": 0.0,
    })
    posShiftIds: list[str] = Field(default_factory=list)
    cashRegisterIds: list[str] = Field(default_factory=list)
    generatedBy: str = ""
    generatedByEmail: str = ""
    generatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
