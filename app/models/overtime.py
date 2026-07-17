"""Modelos Pydantic para Horas Extras."""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class OvertimeType(BaseModel):
    code: str = ""
    name: str = ""
    factor: float = 1.35
    conceptCode: str = ""
    active: bool = True


class OvertimeDetail(BaseModel):
    date: Optional[date] = None
    fromTime: str = ""
    toTime: str = ""
    minutes: int = 0


class OvertimeRecord(BaseModel):
    id: str = ""
    number: str = ""
    employeeId: str = ""
    employeeSnapshot: dict = Field(default_factory=lambda: {"code": "", "name": ""})
    companyCode: str = ""
    departmentCode: str = ""
    payrollCode: str = ""
    date: Optional[date] = None
    overtimeTypeCode: str = ""
    totalMinutes: int = 0
    comment: str = ""
    source: str = "manual"
    sourceReference: str = ""
    status: str = "draft"
    authorizationId: str = ""
    registeredBy: str = ""
    registeredAt: Optional[datetime] = None
    approvedBy: str = ""
    approvedAt: Optional[datetime] = None
    hourlyRateAtApproval: float = 0.0
    factorAtApproval: float = 0.0
    processedPayrollId: str = ""
    processedAt: Optional[datetime] = None
    statusHistory: list = Field(default_factory=list)
    details: list = Field(default_factory=list)


class OvertimePayrollLink(BaseModel):
    overtimeId: str = ""
    payrollId: str = ""
    periodKey: str = ""
    transactionId: str = ""
    conceptCode: str = ""
    amount: float = 0.0
    createdAt: Optional[datetime] = None
