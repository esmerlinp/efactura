"""Read-only operational health summary for controlled rollout."""

from __future__ import annotations


class RecurringContractObservabilityService:
    """Builds alert candidates without changing billing behavior."""

    @staticmethod
    def summarize(*, attempts, outbox_commands, occurrences):
        return {
            "unknown_attempts": sum(1 for item in attempts if str(item.status) in {"UNKNOWN", "TIMEOUT", "QUERY_ERROR"}),
            "pending_reconciliation": sum(1 for item in attempts if str(item.status) == "PENDING"),
            "outbox_retry_wait": sum(1 for item in outbox_commands if str(item.status) == "retry_wait"),
            "outbox_failed": sum(1 for item in outbox_commands if str(item.status) == "failed"),
            "expired_leases": sum(1 for item in [*outbox_commands, *occurrences] if getattr(item, "lease_expires_at", None) is not None),
            "pending_effects": 0,
        }

    @staticmethod
    def alert_candidates(summary):
        return [key for key, value in summary.items() if value]
