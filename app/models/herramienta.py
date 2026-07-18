"""Modelos Pydantic para Gestión de Activos/Herramientas."""

from typing import Optional
from pydantic import BaseModel


class Herramienta(BaseModel):
    id: str = ""
    ownerUID: str = ""
    code: str = ""
    assetTag: str = ""
    name: str = ""
    description: str = ""
    category: str = ""
    type: str = ""
    brand: str = ""
    model: str = ""
    serialNumber: str = ""
    purchasePrice: float = 0.0
    purchasePriceCurrency: str = "DOP"
    purchaseDate: str = ""
    supplier: str = ""
    usefulLife: int = 0
    location: str = ""
    costCenterId: str = ""
    operationalStatus: str = "activo"
    assignmentStatus: str = "disponible"
    notes: str = ""
    encryptedLicenseKey: str = ""
    licenseCount: int = 1
    assignedLicenses: int = 0
    expirationDate: str = ""
    nextMaintenanceDate: str = ""
    usageReading: float = 0.0
    createdAt: str = ""
    updatedAt: str = ""


class AsignacionHerramienta(BaseModel):
    id: str = ""
    ownerUID: str = ""
    herramientaId: str = ""
    herramientaCode: str = ""
    herramientaName: str = ""
    empleadoId: str = ""
    empleadoName: str = ""
    assignedDate: str = ""
    returnedDate: str = ""
    status: str = "activa"
    conditionOnAssignment: str = ""
    conditionOnReturn: str = ""
    deliveryNotes: str = ""
    signedDocumentId: str = ""
    requiresApproval: bool = False
    approvedBy: str = ""
    approvedAt: str = ""
    assignedBy: str = ""
    createdAt: str = ""


class MantenimientoHerramienta(BaseModel):
    id: str = ""
    ownerUID: str = ""
    herramientaId: str = ""
    type: str = ""
    date: str = ""
    cost: float = 0.0
    description: str = ""
    provider: str = ""
    usageReading: float = 0.0
    nextMaintenanceDate: str = ""
    notes: str = ""
    createdAt: str = ""


class HerramientaMovimiento(BaseModel):
    id: str = ""
    ownerUID: str = ""
    herramientaId: str = ""
    herramientaCode: str = ""
    eventType: str = ""
    previousValue: str = ""
    newValue: str = ""
    performedBy: str = ""
    notes: str = ""
    createdAt: str = ""
