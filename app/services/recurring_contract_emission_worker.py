"""Controlled fiscal worker for recurring-contract outbox commands.

The worker is not registered with the scheduler in this phase. It only runs
when explicitly invoked by an integration caller or a test.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from app.models.recurring_contract_emission import (
    FiscalAttemptStatus,
    FiscalErrorClass,
    RecurringContractEmissionAttempt,
)
from app.services.db_service import DatabaseService
from app.services.ecf_emission import EcfEmissionService
from app.services.recurring_contract_billing_service import PreparedRecurringInvoice
from app.services.recurring_contract_outbox_service import OutboxCommandService
from app.services.recurring_contract_fiscal_service import RecurringContractFiscalService


class EmissionWorkerError(RuntimeError):
    pass


class RecurringContractEmissionWorker:
    """Processes one outbox command without owning scheduling or persistence policy."""

    def __init__(
        self,
        *,
        outbox: OutboxCommandService,
        attempts_store: Any,
        company_loader: Callable[[str, str], dict],
        sequence_consumer: Callable[..., tuple[str, str]] | None = None,
        emitter: Callable[..., dict] | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.outbox = outbox
        self.attempts_store = attempts_store
        self.company_loader = company_loader
        self.sequence_consumer = sequence_consumer or DatabaseService.consume_next_sequence
        self.emitter = emitter or EcfEmissionService.emit_electronic_comprobante
        self.now = now or (lambda: datetime.now(timezone.utc))

    def process(
        self,
        *,
        command_id: str,
        owner_uid: str,
        company_id: str,
        worker_id: str,
        prepared: PreparedRecurringInvoice,
        sandbox: bool = True,
        user_email: str = "sistema@vykcore.com",
    ) -> dict:
        command = self.outbox.claim(
            owner_uid=owner_uid,
            company_id=company_id,
            command_id=command_id,
            worker_id=worker_id,
            sandbox=sandbox,
        )
        invoice = prepared.invoice.model_dump(mode="json")
        ecf_type = invoice["ecfType"]
        request_hash = self._request_hash(invoice)
        fiscal = RecurringContractFiscalService.validate(ecf_type)
        if not fiscal.allowed:
            raise EmissionWorkerError(fiscal.reason or "Tipo e-CF no elegible")
        existing = []
        if hasattr(self.attempts_store, "get_for_occurrence"):
            existing = self.attempts_store.get_for_occurrence(
                company_id=company_id, occurrence_id=command.occurrence_id,
                owner_uid=owner_uid, sandbox=sandbox,
            )
        accepted = next((item for item in existing if item.status == FiscalAttemptStatus.ACCEPTED), None)
        if accepted:
            result = self.outbox.finish(
                owner_uid=owner_uid, company_id=company_id, command_id=command_id,
                worker_id=worker_id, fencing_token=command.fencing_token,
                success=True, sandbox=sandbox,
            )
            return {"status": FiscalAttemptStatus.ACCEPTED.value, "attempt": accepted, "outbox": result, "invoice": invoice, "recovered": True}
        ambiguous = next((item for item in existing if item.status in {
            FiscalAttemptStatus.UNKNOWN, FiscalAttemptStatus.TIMEOUT,
            FiscalAttemptStatus.QUERY_ERROR, FiscalAttemptStatus.PENDING,
        }), None)
        if ambiguous:
            return {"status": ambiguous.status.value, "attempt": ambiguous, "outbox": command, "invoice": invoice, "recovered": True, "requires_reconciliation": True}
        attempt = self._create_attempt(command, owner_uid, company_id, request_hash, ecf_type, sandbox)

        try:
            encf, sequence_log_id = self.sequence_consumer(
                owner_uid,
                self._ecf_short_code(ecf_type),
                user_email,
                sandbox=sandbox,
                company_id=company_id,
            )
            attempt = self._update_attempt(attempt, encf=encf, sequence_log_id=sequence_log_id)
            invoice["encf"] = encf
            company = self.company_loader(owner_uid, company_id)
            response = self.emitter(company, invoice, sandbox=sandbox)
            status = self._classify_response(response)
            attempt = self._update_attempt_from_response(attempt, response, status)
            self._save_attempt(attempt, sandbox)

            if status == FiscalAttemptStatus.ACCEPTED:
                result = self.outbox.finish(
                    owner_uid=owner_uid, company_id=company_id, command_id=command_id,
                    worker_id=worker_id, fencing_token=command.fencing_token,
                    success=True, sandbox=sandbox,
                )
                return {"status": status.value, "attempt": attempt, "outbox": result, "invoice": invoice}

            retryable = status in {
                FiscalAttemptStatus.PENDING,
                FiscalAttemptStatus.TIMEOUT,
                FiscalAttemptStatus.UNKNOWN,
                FiscalAttemptStatus.QUERY_ERROR,
            }
            result = self.outbox.finish(
                owner_uid=owner_uid, company_id=company_id, command_id=command_id,
                worker_id=worker_id, fencing_token=command.fencing_token,
                success=False, retryable=retryable,
                error=attempt.error_message, error_class=attempt.error_class.value if attempt.error_class else None,
                sandbox=sandbox,
            )
            return {"status": status.value, "attempt": attempt, "outbox": result, "invoice": invoice}
        except Exception as exc:
            attempt = self._update_attempt(
                attempt,
                status=FiscalAttemptStatus.UNKNOWN,
                error_class=FiscalErrorClass.AMBIGUOUS,
                error_message=str(exc),
            )
            self._save_attempt(attempt, sandbox)
            self.outbox.finish(
                owner_uid=owner_uid, company_id=company_id, command_id=command_id,
                worker_id=worker_id, fencing_token=command.fencing_token,
                success=False, retryable=True, error=str(exc), error_class=FiscalErrorClass.AMBIGUOUS.value,
                sandbox=sandbox,
            )
            return {"status": FiscalAttemptStatus.UNKNOWN.value, "attempt": attempt}

    @staticmethod
    def _classify_response(response: dict | None) -> FiscalAttemptStatus:
        if not isinstance(response, dict):
            return FiscalAttemptStatus.UNKNOWN
        status = str(response.get("dgiiStatus") or response.get("status") or "").upper()
        if response.get("success") and status == "ACCEPTED":
            return FiscalAttemptStatus.ACCEPTED
        if status in {"PENDING", "PENDIENTE"}:
            return FiscalAttemptStatus.PENDING
        if status in {"REJECTED", "RECHAZADO", "RECHAZADA"}:
            return FiscalAttemptStatus.REJECTED
        if status == "TIMEOUT":
            return FiscalAttemptStatus.TIMEOUT
        if response.get("queryError") or response.get("pollError"):
            return FiscalAttemptStatus.QUERY_ERROR
        return FiscalAttemptStatus.UNKNOWN

    @staticmethod
    def _ecf_short_code(ecf_type: str) -> str:
        from app.utils.ecf_utils import get_ecf_type_short_code
        return get_ecf_type_short_code(ecf_type)

    @staticmethod
    def _request_hash(invoice: dict) -> str:
        payload = dict(invoice)
        for key in ("id", "invoiceNumber", "encf", "xmlSignature", "xmlContent", "createdAt", "updatedAt"):
            payload.pop(key, None)
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def _create_attempt(self, command, owner_uid, company_id, request_hash, ecf_type, sandbox):
        attempt = RecurringContractEmissionAttempt(
            attempt_id=command.attempt_id,
            owner_uid=owner_uid,
            company_id=company_id,
            occurrence_id=command.occurrence_id,
            contract_id=command.contract_id,
            request_hash=request_hash,
            ecf_type=ecf_type,
        )
        self._save_attempt(attempt, sandbox)
        return attempt

    def _save_attempt(self, attempt, sandbox):
        if hasattr(self.attempts_store, "save"):
            self.attempts_store.save(attempt, sandbox=sandbox)

    @staticmethod
    def _update_attempt(attempt, **updates):
        return attempt.model_copy(update={**updates, "updated_at": datetime.now(timezone.utc)})

    def _update_attempt_from_response(self, attempt, response, status):
        return self._update_attempt(
            attempt,
            status=status,
            encf=response.get("encf", attempt.encf),
            track_id=response.get("trackId"),
            response_body=response.get("responseBody") or response,
            response_timestamp=self.now(),
            error_message=response.get("error") or response.get("message"),
            error_class=(FiscalErrorClass.PERMANENT if status == FiscalAttemptStatus.REJECTED else FiscalErrorClass.AMBIGUOUS if status != FiscalAttemptStatus.ACCEPTED else None),
        )
