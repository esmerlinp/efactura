"""Commercial recurring-contract domain model.

This model is intentionally separate from ``EmploymentContract``.  It is a
pure domain model for the first recurring-contract phase and does not persist
data or emit fiscal documents.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.fiscal_document_type import by_code


class RecurringContractStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BillingFrequency(str, Enum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"


class BillingMode(str, Enum):
    ADVANCE = "advance"
    ARREARS = "arrears"


class FirstBillingPolicy(str, Enum):
    ON_START = "on_start"
    NEXT_ANCHOR = "next_anchor"


class ProrationPolicy(str, Enum):
    NONE = "none"
    DAILY = "daily"


class PeriodEndPolicy(str, Enum):
    ANCHOR_DAY = "anchor_day"
    LAST_DAY_OF_MONTH = "last_day_of_month"


class DueDatePolicy(str, Enum):
    OCCURRENCE_PLUS_CREDIT_DAYS = "occurrence_plus_credit_days"
    PERIOD_END_PLUS_CREDIT_DAYS = "period_end_plus_credit_days"
    SAME_DAY = "same_day"


class RecurringContractLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = ""
    code: str = ""
    name: str
    item_type: str = "Servicio"
    quantity: float = Field(default=1.0, gt=0)
    unit_price: float = Field(default=0.0, ge=0)
    itbis_rate: float = Field(default=0.18, ge=0, le=1)
    discount_rate: float = Field(default=0.0, ge=0, le=1)

    @property
    def subtotal(self) -> float:
        return round(self.quantity * self.unit_price * (1 - self.discount_rate), 2)

    @property
    def itbis_amount(self) -> float:
        return round(self.subtotal * self.itbis_rate, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.itbis_amount, 2)


class ContractTermsVersion(BaseModel):
    """Immutable-in-use version of commercial terms for future periods."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(gt=0)
    effective_from: date
    effective_to: Optional[date] = None
    ecf_type: Optional[str] = None
    currency: str = "DOP"
    payment_type: str = "Contado"
    payment_method: str = "Efectivo"
    credit_days: int = Field(default=0, ge=0, le=3650)
    due_date_policy: DueDatePolicy = DueDatePolicy.OCCURRENCE_PLUS_CREDIT_DAYS
    billing_mode: BillingMode = BillingMode.ADVANCE
    tax_policy: str = "prices_exclude_itbis"
    lines: tuple[RecurringContractLine, ...] = ()
    notes: str = ""

    @model_validator(mode="after")
    def validate_range(self) -> "ContractTermsVersion":
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to no puede ser anterior a effective_from")
        return self

    def applies_to(self, target: date) -> bool:
        return self.effective_from <= target and (
            self.effective_to is None or target <= self.effective_to
        )


class ContractPeriodSnapshot(BaseModel):
    """Frozen terms used to calculate one billing period."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_id: str
    contract_version: int
    billing_period_key: str
    period_start: date
    period_end: date
    occurrence_date: date
    due_date: date
    ecf_type: Optional[str]
    currency: str
    payment_type: str
    payment_method: str
    credit_days: int
    due_date_policy: DueDatePolicy
    billing_mode: BillingMode
    tax_policy: str
    lines: tuple[RecurringContractLine, ...]


_ALLOWED_TRANSITIONS: dict[RecurringContractStatus, frozenset[RecurringContractStatus]] = {
    RecurringContractStatus.DRAFT: frozenset({RecurringContractStatus.PENDING_APPROVAL, RecurringContractStatus.ACTIVE, RecurringContractStatus.CANCELLED}),
    RecurringContractStatus.PENDING_APPROVAL: frozenset({RecurringContractStatus.ACTIVE, RecurringContractStatus.DRAFT, RecurringContractStatus.CANCELLED}),
    RecurringContractStatus.ACTIVE: frozenset({RecurringContractStatus.SUSPENDED, RecurringContractStatus.CANCELLED, RecurringContractStatus.EXPIRED}),
    RecurringContractStatus.SUSPENDED: frozenset({RecurringContractStatus.ACTIVE, RecurringContractStatus.CANCELLED, RecurringContractStatus.EXPIRED}),
    RecurringContractStatus.CANCELLED: frozenset(),
    RecurringContractStatus.EXPIRED: frozenset({RecurringContractStatus.ACTIVE, RecurringContractStatus.CANCELLED}),
}


class RecurringContract(BaseModel):
    """Commercial recurring contract, independent from employment contracts."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    owner_uid: str
    company_id: str
    contract_number: str = ""
    client_id: str
    client_name_snapshot: str = ""
    client_rnc_snapshot: str = ""
    quotation_id: str = ""

    status: RecurringContractStatus = RecurringContractStatus.DRAFT
    start_date: date
    end_date: Optional[date] = None
    auto_renew: bool = False
    renewal_period: Optional[BillingFrequency] = None
    cancellation_requested: bool = False
    cancellation_reason: str = ""
    cancellation_requested_at: Optional[datetime] = None
    renewed_from_end_date: Optional[date] = None
    renewed_at: Optional[datetime] = None

    frequency: BillingFrequency = BillingFrequency.MONTHLY
    billing_mode: BillingMode = BillingMode.ADVANCE
    billing_day: Optional[int] = Field(default=None, ge=1, le=31)
    billing_anchor_date: date
    billing_timezone: str = "America/Santo_Domingo"
    first_billing_policy: FirstBillingPolicy = FirstBillingPolicy.NEXT_ANCHOR
    proration_policy: ProrationPolicy = ProrationPolicy.NONE
    period_end_policy: PeriodEndPolicy = PeriodEndPolicy.ANCHOR_DAY

    ecf_type: Optional[str] = None
    tax_policy: str = "prices_exclude_itbis"
    currency: str = "DOP"
    payment_type: str = "Contado"
    payment_method: str = "Efectivo"
    credit_days: int = Field(default=0, ge=0, le=3650)
    due_date_policy: DueDatePolicy = DueDatePolicy.OCCURRENCE_PLUS_CREDIT_DAYS
    needs_fiscal_review: bool = False

    lines: tuple[RecurringContractLine, ...] = ()
    terms_versions: tuple[ContractTermsVersion, ...] = ()
    schema_version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("ecf_type")
    @classmethod
    def normalize_ecf_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        return by_code(str(value).strip()).code

    @model_validator(mode="after")
    def validate_dates_and_versions(self) -> "RecurringContract":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date no puede ser anterior a start_date")
        if self.billing_anchor_date < self.start_date:
            raise ValueError("billing_anchor_date no puede ser anterior a start_date")
        versions = sorted(self.terms_versions, key=lambda version: version.version)
        if [version.version for version in versions] != list(range(1, len(versions) + 1)):
            raise ValueError("terms_versions debe tener versiones consecutivas desde 1")
        for previous, current in zip(versions, versions[1:]):
            if previous.effective_to and current.effective_from <= previous.effective_to:
                raise ValueError("Las versiones contractuales no pueden solaparse")
        return self

    @property
    def is_active(self) -> bool:
        return self.status == RecurringContractStatus.ACTIVE

    def can_transition_to(self, target: RecurringContractStatus) -> bool:
        return target in _ALLOWED_TRANSITIONS[self.status]

    def transition_to(self, target: RecurringContractStatus) -> "RecurringContract":
        target = RecurringContractStatus(target)
        if not self.can_transition_to(target):
            raise ValueError(f"Transición no permitida: {self.status.value} -> {target.value}")
        return self.model_copy(update={"status": target, "updated_at": datetime.now(timezone.utc)})

    def terms_for(self, target: date) -> ContractTermsVersion:
        applicable = [version for version in self.terms_versions if version.applies_to(target)]
        if not applicable:
            raise ValueError(f"No existe versión contractual aplicable para {target.isoformat()}")
        return max(applicable, key=lambda version: version.version)

    def add_terms_version(self, terms: ContractTermsVersion) -> "RecurringContract":
        expected = len(self.terms_versions) + 1
        if terms.version != expected:
            raise ValueError(f"La nueva versión debe ser {expected}")
        if terms.effective_from < self.start_date:
            raise ValueError("La vigencia de los términos no puede iniciar antes del contrato")
        if self.terms_versions and terms.effective_from <= self.terms_versions[-1].effective_from:
            raise ValueError("La nueva versión debe iniciar después de la anterior")
        previous = self.terms_versions[-1] if self.terms_versions else None
        if previous and previous.effective_to is None:
            previous = previous.model_copy(update={"effective_to": terms.effective_from})
            versions = self.terms_versions[:-1] + (previous,)
        else:
            versions = self.terms_versions
        return self.model_copy(update={"terms_versions": versions + (terms,), "updated_at": datetime.now(timezone.utc)})

    def snapshot_for(self, period: "BillingPeriod", schedule: Any) -> ContractPeriodSnapshot:
        terms = self.terms_for(period.period_start)
        return ContractPeriodSnapshot(
            contract_id=self.id,
            contract_version=terms.version,
            billing_period_key=period.key,
            period_start=period.period_start,
            period_end=period.period_end,
            occurrence_date=period.occurrence_date,
            due_date=schedule.calculate_due_date(period, terms.credit_days, terms.due_date_policy),
            ecf_type=terms.ecf_type,
            currency=terms.currency,
            payment_type=terms.payment_type,
            payment_method=terms.payment_method,
            credit_days=terms.credit_days,
            due_date_policy=terms.due_date_policy,
            billing_mode=terms.billing_mode,
            tax_policy=terms.tax_policy,
            lines=deepcopy(terms.lines),
        )
