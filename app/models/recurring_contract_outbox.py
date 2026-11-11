"""Persistent command model for recurring-contract fiscal preparation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class OutboxCommandType(str, Enum):
    PREPARE_EMISSION = "prepare_emission"


class OutboxCommandStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutboxCommandError(ValueError):
    """Raised for invalid outbox state transitions."""


_TRANSITIONS = {
    OutboxCommandStatus.PENDING: frozenset({OutboxCommandStatus.PROCESSING, OutboxCommandStatus.CANCELLED}),
    OutboxCommandStatus.RETRY_WAIT: frozenset({OutboxCommandStatus.PROCESSING, OutboxCommandStatus.CANCELLED}),
    OutboxCommandStatus.PROCESSING: frozenset({OutboxCommandStatus.RETRY_WAIT, OutboxCommandStatus.COMPLETED, OutboxCommandStatus.FAILED}),
    OutboxCommandStatus.COMPLETED: frozenset(),
    OutboxCommandStatus.FAILED: frozenset({OutboxCommandStatus.RETRY_WAIT, OutboxCommandStatus.CANCELLED}),
    OutboxCommandStatus.CANCELLED: frozenset(),
}


class RecurringContractEmissionOutboxCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_uid: str
    company_id: str
    contract_id: str
    occurrence_id: str
    attempt_id: str
    command_type: OutboxCommandType = OutboxCommandType.PREPARE_EMISSION
    status: OutboxCommandStatus = OutboxCommandStatus.PENDING
    available_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    fencing_token: int = Field(default=0, ge=0)
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=5, ge=1, le=100)
    last_error: Optional[str] = None
    error_class: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def can_transition_to(self, target: OutboxCommandStatus) -> bool:
        return OutboxCommandStatus(target) in _TRANSITIONS[self.status]

    def transition_to(self, target: OutboxCommandStatus) -> "RecurringContractEmissionOutboxCommand":
        target = OutboxCommandStatus(target)
        if not self.can_transition_to(target):
            raise OutboxCommandError(f"Transición no permitida: {self.status.value} -> {target.value}")
        return self.model_copy(update={"status": target, "updated_at": datetime.now(timezone.utc)})
