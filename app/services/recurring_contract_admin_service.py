"""Administrative mutations for the recurring-contract domain."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable

from app.models.recurring_contract import (
    BillingMode,
    ContractTermsVersion,
    RecurringContract,
    RecurringContractLine,
    RecurringContractStatus,
)
from app.services.recurring_contract_fiscal_service import RecurringContractFiscalService


class RecurringContractAdminService:
    def __init__(self, repository, *, clock: Callable[[], datetime] | None = None):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def create(self, contract: RecurringContract):
        self.repository.create(contract)
        return contract

    def update_terms(self, contract: RecurringContract, *, effective_from: date, ecf_type: str | None, currency: str, payment_type: str, payment_method: str, credit_days: int, billing_mode: BillingMode, lines: tuple[RecurringContractLine, ...], notes: str = ""):
        normalized = None
        if ecf_type:
            normalized = RecurringContractFiscalService.normalize_for_contract(ecf_type, allow_conditional=True)
        terms = ContractTermsVersion(
            version=len(contract.terms_versions) + 1,
            effective_from=effective_from,
            ecf_type=normalized,
            currency=currency,
            payment_type=payment_type,
            payment_method=payment_method,
            credit_days=credit_days,
            billing_mode=billing_mode,
            lines=lines,
            notes=notes,
        )
        updated = contract.add_terms_version(terms)
        if not normalized:
            updated = updated.model_copy(update={"needs_fiscal_review": True})
        return self.repository.update(updated)

    def transition(self, contract: RecurringContract, target: RecurringContractStatus):
        return self.repository.update(contract.transition_to(target))

    def request_cancellation(self, contract: RecurringContract, reason: str):
        if contract.status == RecurringContractStatus.CANCELLED:
            return contract
        updated = contract.model_copy(update={
            "updated_at": self.clock(),
            "cancellation_requested": True,
            "cancellation_reason": reason,
            "cancellation_requested_at": self.clock(),
        })
        return self.repository.update(updated)

    def renew(self, contract: RecurringContract, *, new_end_date: date):
        if contract.end_date and new_end_date <= contract.end_date:
            raise ValueError("La nueva fecha de renovación debe ser posterior a la vigencia actual")
        if not contract.auto_renew:
            raise ValueError("El contrato no tiene renovación automática habilitada")
        return self.repository.update(contract.model_copy(update={
            "end_date": new_end_date,
            "status": RecurringContractStatus.ACTIVE,
            "renewed_from_end_date": contract.end_date,
            "renewed_at": self.clock(),
            "updated_at": self.clock(),
        }))

    def resolve_fiscal_review(self, contract: RecurringContract, *, ecf_type: str):
        normalized = RecurringContractFiscalService.normalize_for_contract(ecf_type, allow_conditional=True)
        # Las versiones de condiciones sin tipo fiscal nunca fueron emitibles:
        # se completan para que el snapshot de facturación tenga e-CF válido.
        versions = tuple(
            version if version.ecf_type else version.model_copy(update={"ecf_type": normalized})
            for version in contract.terms_versions
        )
        return self.repository.update(contract.model_copy(update={
            "ecf_type": normalized,
            "needs_fiscal_review": False,
            "terms_versions": versions,
            "updated_at": self.clock(),
        }))
