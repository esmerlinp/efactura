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