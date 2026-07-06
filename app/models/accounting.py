from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class JournalEntryLine(BaseModel):
    accountId: str = ""
    accountCode: str = ""
    accountName: str = ""
    debit: float = 0.0
    credit: float = 0.0
    description: str = ""
    contactId: Optional[str] = None
    contactName: Optional[str] = None


class JournalEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    number: str = ""
    entryType: str = "standard"
    typeId: Optional[str] = None
    date: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    concept: str = ""
    referenceType: Optional[str] = None
    referenceId: Optional[str] = None
    referenceNumber: Optional[str] = None
    lines: list[JournalEntryLine] = Field(default_factory=list)
    totalDebit: float = 0.0
    totalCredit: float = 0.0
    isBalanced: bool = True
    status: str = "active"
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    createdBy: str = ""
    voidedAt: Optional[str] = None
    voidedBy: Optional[str] = None
    voidReason: Optional[str] = None


class ChartAccount(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    code: str = ""
    name: str = ""
    type: str = "movimiento"
    nature: str = "deudora"
    group: str = ""
    parentId: Optional[str] = None
    level: int = 0
    description: str = ""
    usage: Optional[str] = None
    showByThirdParty: bool = False
    isActive: bool = True
    isSystem: bool = False
    orderIdx: int = 0
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: Optional[str] = None


class FixedAsset(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    code: str = ""
    name: str = ""
    assetType: str = "tangible"
    category: str = "equipos_computo"
    accountId: Optional[str] = None
    depreciationAccountId: Optional[str] = None
    depreciationExpenseAccountId: Optional[str] = None
    description: str = ""
    purchaseDate: str = ""
    purchaseAmount: float = 0.0
    supplierId: Optional[str] = None
    supplierName: str = ""
    location: str = ""
    responsible: str = ""
    usefulLife: int = 36
    usefulLifeUnit: str = "meses"
    depreciationMethod: str = "lineal"
    depreciationRate: float = 0.0
    residualValue: float = 0.0
    currentValue: float = 0.0
    accumulatedDepreciation: float = 0.0
    depreciationPeriod: str = "mensual"
    lastDepreciationDate: Optional[str] = None
    nextDepreciationDate: Optional[str] = None
    status: str = "active"
    disposalDate: Optional[str] = None
    disposalAmount: Optional[float] = None
    disposalReason: Optional[str] = None
    images: list = Field(default_factory=list)
    attachments: list = Field(default_factory=list)
    notes: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FiscalPeriod(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    year: int = datetime.now(timezone.utc).year
    month: int = datetime.now(timezone.utc).month
    status: str = "open"
    closedAt: Optional[str] = None
    closedBy: Optional[str] = None
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
