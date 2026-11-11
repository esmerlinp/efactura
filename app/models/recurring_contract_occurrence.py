"""Persistence-independent model for one contract billing occurrence."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class BillingOccurrenceStatus(str, Enum):
    RESERVED = "reserved"
    PREPARED = "prepared"
    PROCESSING = "processing"
    PENDING_RECONCILIATION = "pending_reconciliation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BillingOccurrenceError(ValueError):
    """Raised for invalid occurrence state or fencing operations."""


_TRANSITIONS = {
    BillingOccurrenceStatus.RESERVED: frozenset({BillingOccurrenceStatus.PREPARED, BillingOccurrenceStatus.PROCESSING, BillingOccurrenceStatus.CANCELLED}),
    BillingOccurrenceStatus.PREPARED: frozenset({BillingOccurrenceStatus.PROCESSING, BillingOccurrenceStatus.CANCELLED}),
    BillingOccurrenceStatus.PROCESSING: frozenset({BillingOccurrenceStatus.PENDING_RECONCILIATION, BillingOccurrenceStatus.COMPLETED, BillingOccurrenceStatus.FAILED}),
    BillingOccurrenceStatus.PENDING_RECONCILIATION: frozenset({BillingOccurrenceStatus.PROCESSING, BillingOccurrenceStatus.FAILED, BillingOccurrenceStatus.COMPLETED}),
    BillingOccurrenceStatus.COMPLETED: frozenset(),
    BillingOccurrenceStatus.FAILED: frozenset({BillingOccurrenceStatus.PROCESSING, BillingOccurrenceStatus.CANCELLED}),
    BillingOccurrenceStatus.CANCELLED: frozenset(),
}


class RecurringContractBillingOccurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    owner_uid: str
    company_id: str
    contract_id: str
    billing_period_key: str
    period_start: str
    period_end: str
    occurrence_date: str
    status: BillingOccurrenceStatus = BillingOccurrenceStatus.RESERVED
    invoice_id: Optional[str] = None
    prepared_invoice_hash: Optional[str] = None
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    fencing_token: int = Field(default=0, ge=0)
    attempt_count: int = Field(default=0, ge=0)
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def can_transition_to(self, target: BillingOccurrenceStatus) -> bool:
        return BillingOccurrenceStatus(target) in _TRANSITIONS[self.status]

    def transition_to(self, target: BillingOccurrenceStatus) -> "RecurringContractBillingOccurrence":
        target = BillingOccurrenceStatus(target)
        if not self.can_transition_to(target):
            raise BillingOccurrenceError(f"Transición no permitida: {self.status.value} -> {target.value}")
        return self.model_copy(update={"status": target, "updated_at": datetime.now(timezone.utc)})
