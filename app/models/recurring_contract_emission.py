"""Fiscal attempt and post-acceptance domain models for recurring contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class FiscalAttemptStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"
    QUERY_ERROR = "QUERY_ERROR"


class FiscalErrorClass(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    AMBIGUOUS = "ambiguous"


class PostAcceptanceEffectType(str, Enum):
    ACCOUNTING = "accounting"
    INVENTORY = "inventory"
    NOTIFICATION = "notification"


class RecurringContractEmissionAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_uid: str
    company_id: str
    occurrence_id: str
    contract_id: str
    request_hash: str
    ecf_type: str
    encf: Optional[str] = None
    sequence_log_id: Optional[str] = None
    sequence_number: Optional[int] = None
    track_id: Optional[str] = None
    status: FiscalAttemptStatus = FiscalAttemptStatus.UNKNOWN
    error_class: Optional[FiscalErrorClass] = None
    error_message: Optional[str] = None
    response_body: Optional[dict | str] = None
    response_timestamp: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PostAcceptanceEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_uid: str
    company_id: str
    invoice_id: str
    event_type: PostAcceptanceEffectType
    status: str = "PENDING"
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
