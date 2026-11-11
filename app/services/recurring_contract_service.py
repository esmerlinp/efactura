"""Single coordination point for manual and scheduled contract billing."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from app.models.recurring_contract import RecurringContract
from app.models.recurring_contract_occurrence import BillingOccurrenceStatus
from app.services.recurring_contract_billing_service import RecurringContractBillingService
from app.services.recurring_contract_occurrence_service import RecurringContractOccurrenceService
from app.services.recurring_contract_outbox_service import OutboxCommandService


class RecurringContractCoordinationError(RuntimeError):
    pass


class RecurringContractFeatureFlags:
    """Explicit per-company/environment rollout gate, disabled by default."""

    KEY = "recurring_contract_engine_v2"

    def __init__(self, flag_loader: Callable[[str, bool], bool] | None = None):
        self.flag_loader = flag_loader or self._config_default

    @staticmethod
    def _config_default(_company_id: str, _sandbox: bool) -> bool:
        try:
            from config import Config
            return bool(getattr(Config, "RECURRING_CONTRACT_ENGINE_V2_DEFAULT", False))
        except Exception:
            return False

    def enabled(self, company_id: str, sandbox: bool) -> bool:
        return bool(company_id and self.flag_loader(company_id, sandbox))


class RecurringContractService:
    """Coordinates preparation, draft persistence, occurrence and outbox creation.

    It persists a linked draft invoice but intentionally does not emit e-CF.
    The outbox worker remains a separate explicit operation from Phase 5.
    """

    def __init__(
        self,
        *,
        occurrence_service: RecurringContractOccurrenceService,
        outbox_service: OutboxCommandService,
        flags: RecurringContractFeatureFlags | None = None,
        invoice_store: Callable[..., Any] | None = None,
        invoice_loader: Callable[..., Any] | None = None,
    ):
        self.occurrences = occurrence_service
        self.outbox = outbox_service
        self.flags = flags or RecurringContractFeatureFlags()
        self.invoice_store = invoice_store or self._default_invoice_store
        self.invoice_loader = invoice_loader or self._default_invoice_loader

    @staticmethod
    def _default_invoice_loader(*, owner_uid, invoice_id, sandbox=True, company_id=None):
        from app.services.db_service import DatabaseService
        return DatabaseService.get_invoice(
            owner_uid, invoice_id, sandbox=sandbox, company_id=company_id
        )

    @staticmethod
    def _default_invoice_store(*, owner_uid, invoice_id, invoice_dict, sandbox=True, company_id=None):
        from app.services.db_service import DatabaseService
        return DatabaseService.save_invoice(
            owner_uid, invoice_id, invoice_dict, sandbox=sandbox, company_id=company_id
        )

    def prepare_and_enqueue(self, *, contract: RecurringContract, owner_uid: str, company_id: str, sandbox: bool, trigger: str, occurrence_date: date | None = None, worker_id: str | None = None):
        self._assert_scope(contract, owner_uid, company_id)
        if not self.flags.enabled(company_id, sandbox):
            return {"enabled": False, "status": "legacy_required", "trigger": trigger}
        prepared = RecurringContractBillingService.prepare_invoice(contract, occurrence_date=occurrence_date)
        occurrence = self.occurrences.create_idempotent(
            owner_uid=owner_uid,
            company_id=company_id,
            contract_id=contract.id,
            billing_period_key=prepared.period.key,
            period_start=prepared.period.period_start.isoformat(),
            period_end=prepared.period.period_end.isoformat(),
            occurrence_date=prepared.period.occurrence_date.isoformat(),
            sandbox=sandbox,
        )
        occurrence, prepared = self.occurrences.prepare_once(occurrence=occurrence, contract=contract, sandbox=sandbox)
        invoice_dict = prepared.invoice.model_dump(mode="json")
        invoice_dict.update({
            "contractId": contract.id,
            "contractNumber": contract.contract_number or contract.id,
            "occurrenceId": occurrence.id,
        })
        existing_number = self._existing_invoice_number(
            owner_uid=owner_uid, invoice_id=prepared.invoice.id, sandbox=sandbox, company_id=company_id
        )
        if existing_number:
            invoice_dict["invoiceNumber"] = existing_number
        if occurrence.status != BillingOccurrenceStatus.COMPLETED:
            self.invoice_store(
                owner_uid=owner_uid,
                invoice_id=prepared.invoice.id,
                invoice_dict=invoice_dict,
                sandbox=sandbox,
                company_id=company_id,
            )
        command = self.outbox.create_idempotent(
            owner_uid=owner_uid,
            company_id=company_id,
            contract_id=contract.id,
            occurrence_id=occurrence.id,
            attempt_id=occurrence.invoice_id or occurrence.id,
            sandbox=sandbox,
        )
        return {
            "enabled": True,
            "status": "outbox_created",
            "trigger": trigger,
            "occurrence": occurrence,
            "command": command,
            "prepared": prepared,
            "invoice": invoice_dict,
            "invoice_id": prepared.invoice.id,
        }

    def _existing_invoice_number(self, *, owner_uid, invoice_id, sandbox, company_id):
        """Reuse the number assigned to an already prepared occurrence."""
        try:
            existing = self.invoice_loader(
                owner_uid=owner_uid, invoice_id=invoice_id, sandbox=sandbox, company_id=company_id
            )
        except Exception:
            return None
        if not existing:
            return None
        return existing.get("invoiceNumber") or None

    @staticmethod
    def _assert_scope(contract, owner_uid, company_id):
        if contract.owner_uid != owner_uid or contract.company_id != company_id:
            raise PermissionError("El contrato no pertenece al ámbito solicitado")
