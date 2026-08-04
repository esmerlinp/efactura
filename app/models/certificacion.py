from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class CaseResult(BaseModel):
    encf: str = ""
    tipo: str = ""
    total: float = 0.0
    grupo: int = 0
    tag: str = ""
    success: bool = False
    dry_run: bool = False
    track_id: Optional[str] = None
    dgii_status: Optional[str] = None
    error_message: Optional[str] = None
    signed_xml_path: str = ""
    raw_xml_path: str = ""
    codigo_seguridad: Optional[str] = None
    status_check: dict = Field(default_factory=dict)
    response_data: dict = Field(default_factory=dict)
    nota: str = ""


class CertRun(BaseModel):
    run_number: int = 1
    step: int = 0
    status: str = "in_progress"
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    total_cases: int = 0
    accepted: int = 0
    rejected: int = 0
    pending: int = 0
    manual_uploaded: int = 0
    cases: list[dict] = Field(default_factory=list)
    evidencias_dir: str = ""
    error_summary: Optional[str] = None


class CertStep(BaseModel):
    status: str = "pending"
    current_run: int = 0
    runs: list[dict] = Field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CertificacionProcess(BaseModel):
    id: str = ""
    current_step: int = 1
    steps: dict[str, dict] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    class Config:
        extra = "allow"
