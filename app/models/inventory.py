"""Modelos Pydantic para Inventario Avanzado: Lotes, Series, Transferencias, Conteos Físicos."""

from datetime import datetime, timezone, date
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class LotBatch(BaseModel):
    """Lote de inventario con trazabilidad y vencimiento."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    itemId: str = ""
    itemName: str = ""
    warehouseId: str = ""
    lotNumber: str = ""
    productionDate: str = ""
    expirationDate: str = ""
    initialQuantity: float = 0.0
    quantity: float = 0.0
    unitCost: float = 0.0
    notes: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SerialNumber(BaseModel):
    """Número de serie individual para productos trazables."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    itemId: str = ""
    itemName: str = ""
    serial: str = ""
    lotId: str = ""
    lotNumber: str = ""
    status: str = "en_stock"  # en_stock | vendido | transferido | dado_de_baja
    warehouseId: str = ""
    referenceId: str = ""  # ID del documento que consumió el serial
    referenceType: str = ""  # invoice | transfer
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WarehouseTransfer(BaseModel):
    """Solicitud de transferencia de stock entre almacenes."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    originWarehouseId: str = ""
    originWarehouseName: str = ""
    destinationWarehouseId: str = ""
    destinationWarehouseName: str = ""
    status: str = "pendiente"  # pendiente | en_transito | completada | rechazada
    requestedBy: str = ""
    approvedBy: str = ""
    notes: str = ""
    lines: list[dict] = Field(default_factory=list)
    # Cada línea: {itemId, itemName, quantity, lotId (opcional)}
    requestedDate: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    approvedDate: str = ""
    completedDate: str = ""
    rejectionReason: str = ""


class PhysicalCountLine(BaseModel):
    """Línea de conteo físico con cantidad esperada y contada."""
    itemId: str = ""
    itemName: str = ""
    lotId: str = ""
    lotNumber: str = ""
    expectedQty: float = 0.0
    countedQty: float = 0.0
    difference: float = 0.0
    notes: str = ""


class PhysicalCount(BaseModel):
    """Sesión de conteo físico de inventario."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    warehouseId: str = ""
    warehouseName: str = ""
    status: str = "en_progreso"  # en_progreso | finalizado | ajustado
    startedBy: str = ""
    finalizedBy: str = ""
    startedDate: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finalizedDate: str = ""
    notes: str = ""
    lines: list[dict] = Field(default_factory=list)
    # Resumen post-finalización
    totalLines: int = 0
    linesWithDifference: int = 0
    totalSurplus: float = 0.0
    totalShortage: float = 0.0
