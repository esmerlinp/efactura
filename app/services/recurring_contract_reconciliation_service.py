"""Reconciliation of ambiguous recurring-contract fiscal attempts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.models.recurring_contract_emission import FiscalAttemptStatus


class RecurringContractReconciliationService:
    def __init__(self, *, attempts_store: Any, status_checker: Callable[..., dict], now: Callable[[], datetime] | None = None):
        self.attempts_store = attempts_store
        self.status_checker = status_checker
        self.now = now or (lambda: datetime.now(timezone.utc))

    def reconcile(self, attempt, *, company: dict, sandbox: bool = True):
        if attempt.status == FiscalAttemptStatus.ACCEPTED:
            return attempt
        if attempt.status == FiscalAttemptStatus.REJECTED:
            return attempt
        if not attempt.track_id:
            updated = attempt.model_copy(update={
                "status": FiscalAttemptStatus.UNKNOWN,
                "updated_at": self.now(),
            })
            self._save(updated, sandbox)
            return updated
        response = self.status_checker(company, attempt.track_id, sandbox=sandbox)
        status = self._classify(response)
        updated = attempt.model_copy(update={
            "status": status,
            "response_body": response.get("responseBody") or response,
            "response_timestamp": self.now(),
            "updated_at": self.now(),
            "error_message": response.get("message") if status != FiscalAttemptStatus.ACCEPTED else None,
        })
        self._save(updated, sandbox)
        return updated

    def _save(self, attempt, sandbox):
        if hasattr(self.attempts_store, "save"):
            self.attempts_store.save(attempt, sandbox=sandbox)

    @staticmethod
    def _classify(response):
        if not isinstance(response, dict):
            return FiscalAttemptStatus.QUERY_ERROR
        status = str(response.get("dgiiStatus") or "").upper()
        if status == "ACCEPTED":
            return FiscalAttemptStatus.ACCEPTED
        if status == "REJECTED":
            return FiscalAttemptStatus.REJECTED
        if status == "TIMEOUT":
            return FiscalAttemptStatus.TIMEOUT
        if not response.get("success"):
            return FiscalAttemptStatus.QUERY_ERROR
        return FiscalAttemptStatus.PENDING
