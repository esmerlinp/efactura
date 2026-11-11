"""Migration records and reports for commercial recurring contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class MigrationDisposition(str, Enum):
    MIGRATABLE = "migratable"
    NEEDS_REVIEW = "needs_review"
    INCOMPATIBLE = "incompatible"
    ALREADY_MIGRATED = "already_migrated"


class RecurringContractMigrationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    migration_id: str
    source_id: str
    owner_uid: str
    company_id: str
    sandbox: bool
    target_id: str
    disposition: MigrationDisposition
    source_fingerprint: str
    source_document: dict[str, Any]
    target_document: Optional[dict[str, Any]] = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MigrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_uid: str
    company_id: str
    sandbox: bool
    dry_run: bool
    total: int = 0
    migratable: int = 0
    needs_review: int = 0
    incompatible: int = 0
    already_migrated: int = 0
    records: tuple[RecurringContractMigrationRecord, ...] = ()
