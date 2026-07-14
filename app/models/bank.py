from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class BankAccount(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    name: str = ""
    type: str = "banco"
    accountNumber: str = ""
    initialBalance: float = 0.0
    balanceDate: str = ""
    currentBalance: float = 0.0
    creditLimit: float = 0.0
    description: str = ""
    accountingAccountId: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BankReconciliationTransaction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str = ""
    description: str = ""
    amount: float = 0.0
    date: str = ""
    source: str = ""
    referenceId: str = ""
    referenceNumber: str = ""
    reconciled: bool = False


class BankReconciliation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ownerUID: str = ""
    accountId: str = ""
    accountName: str = ""
    accountType: str = ""
    startDate: str = ""
    endDate: str = ""
    startBalance: float = 0.0
    endBalance: float = 0.0
    calculatedBalance: float = 0.0
    difference: float = 0.0
    status: str = "en_curso"
    transactions: list[BankReconciliationTransaction] = Field(default_factory=list)
    transactionCount: int = 0
    reconciledCount: int = 0
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
