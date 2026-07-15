from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class CxPPayment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    amount: float = 0.0
    paymentDate: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    registeredBy: str = ""


class Expense(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    concept: str = ""
    category: str = ""
    amount: float = 0.0
    amountOriginal: Optional[float] = None
    itbisAmount: float = 0.0
    itbisAmountOriginal: Optional[float] = None
    exchangeRate: float = 1.0
    date: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dueDate: str = ""
    rncEmisor: str = ""
    ncf: str = ""
    isMinorExpense: bool = False
    isSyncedWithDGII: bool = False
    qrCodeURL: str = ""
    xmlSignature: str = ""
    notes: str = ""
    isRecurring: bool = False
    recurrenceInterval: str = "mensual"
    nextOccurrenceDate: str = ""
    recurrenceEndDate: str = ""
    associatedInvoiceId: str = ""
    isITBISDeductible: bool = True
    isDeductible: bool = True
    attachments: list = Field(default_factory=list)
    firebaseAttachmentURLs: list[str] = Field(default_factory=list)
    currency: str = "DOP"
    supplierType: str = "formal"
    providerName: str = ""
    ecfType: str = ""
    ecfNumber: str = ""
    cne: str = ""
    tipoGastoDGII: str = "02"
    paymentType: str = "Contado"
    cxpStatus: str = "Pagado"
    cxpRemainingBalance: float = 0.0
    approvalStatus: str = "Aprobado"
    requestedBy: str = ""
    approvedBy: str = ""
    assignedApproverId: str = ""
    assignedApproverName: str = ""
    assignedApproverEmail: str = ""
    encf: str = ""
    emisionMode: str = ""
    trackId: str = ""
    xmlContent: str = ""
    supplierId: str = ""
    dgiiStatus: str = ""
    includeIn606: bool = True
    isCost: bool = False
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
