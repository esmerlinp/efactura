"""PayrollPosting — Desacopla la nómina de la contabilidad.

Cada PayrollPosting vincula un PayrollPeriod con uno o más JournalEntry.
Permite revertir, reversionar y auditar la contabilización de nóminas
sin afectar los períodos calculados.
"""

from pydantic import BaseModel, Field
from typing import Optional


class PayrollPosting(BaseModel):
    """Vincula un PayrollPeriod con uno o más JournalEntry.

    Una nómina puede generar múltiples asientos (sueldos, TSS, ISR, otros),
    y un asiento puede revertirse independientemente.
    """
    id: str = ""
    periodId: str = ""
    periodKey: str = ""
    legalEntityId: str = ""

    # Asientos contables generados
    journalEntryIds: list = []

    # Estado del posting
    status: str = "pending"            # pending | posted | reversed | reposted

    # Snapshot de las líneas contables al momento de postear
    accountingLines: list = []

    # Trazabilidad
    postedBy: str = ""
    postedAt: str = ""
    reversedBy: str = ""
    reversedAt: str = ""
    reversalReason: str = ""
    repostedAt: str = ""

    # Metadatos
    notes: str = ""
    version: int = 1                    # Incrementa con cada repost
    prevPostingId: str = ""             # Para reversiones encadenadas
    createdBy: str = ""
    createdAt: str = ""
    updatedAt: str = ""


class InventoryPosting(BaseModel):
    """Vincula una InventoryTransaction con su JournalEntry contable.

    Garantiza idempotencia, trazabilidad bidireccional y manejo de fallos
    desacoplado del movimiento físico de inventario.
    """
    id: str = ""
    idempotencyKey: str = ""                # {companyId}|INVENTORY|{inventoryTransactionId}
    companyId: str = ""
    inventoryTransactionId: str = ""
    inventoryTransactionType: str = ""      # ENTRADA | SALIDA | AJUSTE | TRANSFERENCIA
    reason: str = ""                        # VENTA | DEVOLUCION_CLIENTE | COMPRA | RECUENTO_FISICO | MERMA | etc.
    entryDate: str = ""                     # YYYY-MM-DD (fecha económica para el período fiscal)
    inventoryTransactionDate: str = ""      # ISO8601 del movimiento
    referenceType: Optional[str] = None     # invoice | credit_note | goods_receipt | physical_count | etc.
    referenceId: Optional[str] = None       # ID de referencia
    referenceNumber: Optional[str] = None   # Número de documento (eNCF, RC, CF, TR)
    journalEntryId: Optional[str] = None    # ID del JournalEntry generado
    journalEntryNumber: Optional[str] = None # Número del asiento (ej. A-2026-0001)
    reversalEntryId: Optional[str] = None   # ID del asiento de reversión si aplica
    reversalEntryNumber: Optional[str] = None
    amount: float = 0.0                     # Importe total contabilizado (inventory_transactions.totalValue)
    costLayers: list = []                   # Snapshot de las capas FIFO contabilizadas
    status: str = "PENDING"                 # PENDING | POSTING | POSTED | FAILED | REVERSED | SKIPPED_NEUTRAL
    errorDetails: Optional[str] = None
    retryCount: int = 0
    createdAt: str = ""
    updatedAt: str = ""
    postedAt: Optional[str] = None
    postedBy: str = ""
    reversedAt: Optional[str] = None
    reversedBy: Optional[str] = None
    reversalReason: Optional[str] = None