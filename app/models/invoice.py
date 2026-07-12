from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class InvoiceItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    code: str = ""
    type: str = "Bien"
    name: str = ""
    price: float = 0.0
    quantity: float = 1.0
    itbisRate: float = 0.18
    discountRate: float = 0.0
    subtotal: float = 0.0
    itbisAmount: float = 0.0
    total: float = 0.0
    codigoImpuesto: str = ""
    tasaImpuestoAdicional: float = 0.0
    gradosAlcohol: float = 0.0
    cantidadReferencia: float = 0.0
    subcantidad: float = 1.0
    precioReferencia: float = 0.0
    isc_especifico_amount: float = 0.0
    isc_advalorem_amount: float = 0.0
    otros_impuestos_amount: float = 0.0


class InvoiceInstallment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    installmentNumber: int = 1
    amount: float = 0.0
    dueDate: str = ""
    status: str = "Pendiente"
    paidAmount: float = 0.0
    remainingBalance: float = 0.0


class InvoicePayment(BaseModel):
    id: str = ""
    amount: float = 0.0
    paymentMethod: str = ""
    bank: str = ""
    referenceNumber: str = ""
    paymentDate: str = ""
    registeredBy: str = ""
    bankAccountId: str = ""


class Invoice(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    invoiceNumber: str = ""
    date: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dueDate: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    clientId: str = ""
    clientName: str = ""
    clientRNC: str = ""
    status: str = "Borrador"
    ecfType: str = "Factura de Consumo (E32)"
    encf: str = ""
    xmlSignature: str = ""
    qrCodeURL: str = ""
    isSyncedWithDGII: bool = False
    emisionMode: str = ""
    dgiiStatus: str = ""
    contingencyEmittedAt: str = ""
    creditedAmount: float = 0.0
    retainedISR: float = 0.0
    retainedITBIS: float = 0.0
    netPayable: float = 0.0
    subtotal: float = 0.0
    totalITBIS: float = 0.0
    total: float = 0.0
    isQuotation: bool = False
    isConvertedToInvoice: bool = False
    appliedAdvances: list[dict] = Field(default_factory=list)
    notes: str = ""
    comentario: str = ""
    footer: str = ""
    isRecurring: bool = False
    recurrenceInterval: str = "mensual"
    nextOccurrenceDate: str = ""
    firebasePDFURL: str = ""
    firebaseXMLURL: str = ""
    currency: str = "DOP"
    paymentType: str = "Contado"
    paymentMethod: str = "Efectivo"
    incomeType: str = "01 - Ingresos por operaciones"
    customFields: list[dict] = Field(default_factory=list)
    exchangeRate: float = 1.0
    bank: str = ""
    referenceNumber: str = ""
    paymentDate: str = ""
    totalPaid: float = 0.0
    remainingBalance: float = 0.0
    paymentAgreement: dict = Field(default_factory=lambda: {"enabled": False, "installmentsCount": 1, "frequency": "mensual", "lateFeePercentage": 5.0})
    installments: list[InvoiceInstallment] = Field(default_factory=list)
    branchId: str = "default-sucursal-principal"
    warehouseId: str = ""
    stockReduced: bool = False
    stockReverted: bool = False
    isConsolidado: bool = False
    consolidatedInvoiceIds: list[str] = Field(default_factory=list)
    invoiceNumberConsolidado: str = ""
    encfConsolidado: str = ""
    items: list[InvoiceItem] = Field(default_factory=list)
    pendingPaymentProof: Optional[Any] = None
    isProfessional: bool = False
    professionalData: dict = Field(default_factory=dict)
    registeredBy: str = ""
    signatureInfo: Optional[Any] = None
    isDeleted: bool = False
    deletedAt: Optional[str] = None
    cancellationType: str = ""
    cancellationReason: str = ""
    cancelledAt: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: Optional[Any] = None


class ClientAdvance(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    clientId: str = ""
    clientName: str = ""
    clientRNC: str = ""
    amount: float = 0.0
    paymentMethod: str = "Efectivo"
    bank: str = ""
    bankAccountId: str = ""
    referenceNumber: str = ""
    paymentDate: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    registeredBy: str = ""
    notes: str = ""
    quotationId: str = ""
    quotationNumber: str = ""
    status: str = "Activo"
    appliedToInvoiceId: str = ""
    appliedToInvoiceNumber: str = ""
    appliedAmount: float = 0.0
    appliedAt: str = ""
    branchId: str = "default-sucursal-principal"
    projectId: Optional[str] = None
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: Optional[str] = None
    isDeleted: bool = False
