"""Deterministic calendar rules for commercial recurring contracts."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from app.models.recurring_contract import (
    BillingFrequency,
    BillingMode,
    DueDatePolicy,
    PeriodEndPolicy,
    ProrationPolicy,
    RecurringContract,
)


@dataclass(frozen=True)
class BillingPeriod:
    key: str
    period_start: date
    period_end: date
    occurrence_date: date


class RecurringContractScheduleService:
    """Pure date calculations; no persistence, scheduler, or fiscal side effects."""

    @staticmethod
    def add_frequency(value: date, frequency: BillingFrequency, count: int = 1) -> date:
        if frequency == BillingFrequency.WEEKLY:
            return value + timedelta(days=7 * count)
        if frequency == BillingFrequency.BIWEEKLY:
            return value + timedelta(days=14 * count)
        months = {
            BillingFrequency.MONTHLY: 1,
            BillingFrequency.QUARTERLY: 3,
            BillingFrequency.SEMIANNUAL: 6,
            BillingFrequency.ANNUAL: 12,
        }.get(frequency)
        if months is None:
            raise ValueError(f"Frecuencia no soportada: {frequency}")
        month_index = value.month - 1 + months * count
        year = value.year + month_index // 12
        month = month_index % 12 + 1
        return value.replace(day=min(value.day, calendar.monthrange(year, month)[1]), year=year, month=month)

    @staticmethod
    def anchor_date(contract: RecurringContract, year: int, month: int) -> date:
        day = contract.billing_day or contract.billing_anchor_date.day
        if contract.period_end_policy == PeriodEndPolicy.LAST_DAY_OF_MONTH:
            day = calendar.monthrange(year, month)[1]
        else:
            day = min(day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    @classmethod
    def next_billing_date(cls, contract: RecurringContract, current: date) -> date:
        if contract.frequency in (BillingFrequency.WEEKLY, BillingFrequency.BIWEEKLY):
            return cls.add_frequency(current, contract.frequency)
        next_date = cls.add_frequency(current, contract.frequency)
        return cls.anchor_date(contract, next_date.year, next_date.month)

    @classmethod
    def calculate_period(cls, contract: RecurringContract, occurrence_date: date | None = None) -> BillingPeriod:
        occurrence = occurrence_date or contract.billing_anchor_date
        if contract.billing_mode == BillingMode.ADVANCE:
            period_start = occurrence
            period_end = cls.next_billing_date(contract, occurrence) - timedelta(days=1)
        else:
            period_end = occurrence
            period_start = cls.add_frequency(period_end, contract.frequency, -1) + timedelta(days=1)
        return BillingPeriod(
            key=f"{contract.id}:{period_start.isoformat()}:{period_end.isoformat()}",
            period_start=period_start,
            period_end=period_end,
            occurrence_date=occurrence,
        )

    @staticmethod
    def calculate_due_date(period: BillingPeriod, credit_days: int, policy: DueDatePolicy) -> date:
        if policy == DueDatePolicy.SAME_DAY:
            return period.occurrence_date
        base = period.period_end if policy == DueDatePolicy.PERIOD_END_PLUS_CREDIT_DAYS else period.occurrence_date
        return base + timedelta(days=credit_days)

    @staticmethod
    def prorated_amount(amount: float, period: BillingPeriod, start_date: date, policy: ProrationPolicy) -> float:
        if policy == ProrationPolicy.NONE or start_date <= period.period_start:
            return round(amount, 2)
        if start_date > period.period_end:
            return 0.0
        total_days = (period.period_end - period.period_start).days + 1
        billable_days = (period.period_end - start_date).days + 1
        return round(float(amount) * billable_days / total_days, 2)

    @staticmethod
    def renewal_end_date(contract: RecurringContract, current_end: date) -> date:
        frequency = contract.renewal_period or contract.frequency
        return RecurringContractScheduleService.add_frequency(current_end, frequency)
