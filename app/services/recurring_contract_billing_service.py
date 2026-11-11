"""Pure invoice preparation for commercial recurring contracts.

This phase deliberately stops before persistence, sequence consumption, DGII
emission, outbox creation, or scheduler integration.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import uuid4

from app.models.invoice import Invoice, InvoiceItem
from app.models.recurring_contract import (
    ContractPeriodSnapshot,
    RecurringContract,
    RecurringContractStatus,
)
from app.services.recurring_contract_fiscal_service import RecurringContractFiscalService
from app.services.recurring_contract_schedule_service import BillingPeriod, RecurringContractScheduleService
from app.models.fiscal_document_type import by_code


class RecurringContractBillingError(ValueError):
    """Raised when a contract cannot produce a valid billing representation."""


@dataclass(frozen=True)
class PreparedRecurringInvoice:
    invoice: Invoice
    snapshot: ContractPeriodSnapshot
    period: BillingPeriod


class RecurringContractBillingService:
    """Builds a deterministic invoice representation without side effects."""

    BILLABLE_STATUSES = frozenset({RecurringContractStatus.ACTIVE})

    @classmethod
    def prepare_invoice(
        cls,
        contract: RecurringContract,
        *,
        occurrence_date: date | None = None,
        now: datetime | None = None,
    ) -> PreparedRecurringInvoice:
        cls._validate_contract(contract)
        period = RecurringContractScheduleService.calculate_period(contract, occurrence_date)
        cls._validate_period(contract, period)
        try:
            snapshot = contract.snapshot_for(period, RecurringContractScheduleService)
        except ValueError as exc:
            raise RecurringContractBillingError(str(exc)) from exc
        cls._validate_snapshot(snapshot)

        issued_at = now or datetime.now(timezone.utc)
        invoice_id = str(uuid4())
        invoice = cls._build_invoice(contract, snapshot, invoice_id, issued_at)
        return PreparedRecurringInvoice(invoice=invoice, snapshot=snapshot, period=period)

    @classmethod
    def _validate_contract(cls, contract: RecurringContract) -> None:
        if contract.status not in cls.BILLABLE_STATUSES:
            raise RecurringContractBillingError(
                f"El contrato {contract.id} no está activo: {contract.status.value}"
            )
        if contract.needs_fiscal_review:
            raise RecurringContractBillingError(
                f"El contrato {contract.id} requiere revisión fiscal"
            )
        if not contract.lines:
            raise RecurringContractBillingError(
                f"El contrato {contract.id} no tiene líneas facturables"
            )
        if contract.end_date and contract.end_date < contract.start_date:
            raise RecurringContractBillingError("La vigencia contractual es inválida")

    @staticmethod
    def _validate_period(contract: RecurringContract, period: BillingPeriod) -> None:
        if period.period_start < contract.start_date:
            raise RecurringContractBillingError("El período inicia antes de la vigencia contractual")
        if contract.end_date and period.period_start > contract.end_date:
            raise RecurringContractBillingError("El período está fuera de la vigencia contractual")
        if contract.end_date and period.period_end > contract.end_date and not contract.auto_renew:
            raise RecurringContractBillingError("El período excede la vigencia contractual")

    @staticmethod
    def _validate_snapshot(snapshot: ContractPeriodSnapshot) -> None:
        fiscal = RecurringContractFiscalService.validate(snapshot.ecf_type)
        if not fiscal.allowed:
            reason = fiscal.reason or "Tipo de e-CF no elegible"
            raise RecurringContractBillingError(reason)
        if snapshot.currency not in {"DOP", "USD", "EUR"}:
            raise RecurringContractBillingError(f"Moneda no soportada: {snapshot.currency}")
        if snapshot.period_end < snapshot.period_start:
            raise RecurringContractBillingError("El período facturado es inválido")
        if not snapshot.lines:
            raise RecurringContractBillingError("El snapshot no tiene líneas facturables")

    @classmethod
    def _build_invoice(
        cls,
        contract: RecurringContract,
        snapshot: ContractPeriodSnapshot,
        invoice_id: str,
        issued_at: datetime,
    ) -> Invoice:
        items: list[InvoiceItem] = []
        subtotal = 0.0
        total_itbis = 0.0
        total = 0.0
        for line in snapshot.lines:
            item = InvoiceItem(
                code=line.code,
                type=line.item_type,
                name=line.name,
                price=line.unit_price,
                quantity=line.quantity,
                itbisRate=line.itbis_rate,
                discountRate=line.discount_rate,
                subtotal=line.subtotal,
                itbisAmount=line.itbis_amount,
                total=line.total,
            )
            items.append(item)
            subtotal += line.subtotal
            total_itbis += line.itbis_amount
            total += line.total

        ecf_type = by_code(snapshot.ecf_type or "")
        return Invoice(
            id=invoice_id,
            ownerUID=contract.owner_uid,
            invoiceNumber=f"FAC-{random.randint(1, 999999):06d}",
            date=snapshot.occurrence_date.isoformat(),
            dueDate=snapshot.due_date.isoformat(),
            clientId=contract.client_id,
            clientName=contract.client_name_snapshot,
            clientRNC=contract.client_rnc_snapshot,
            status="Borrador",
            contractId=contract.id,
            contractNumber=contract.contract_number or contract.id,
            ecfType=ecf_type.label_with_code,
            encf="",
            isSyncedWithDGII=False,
            netPayable=round(total, 2),
            subtotal=round(subtotal, 2),
            totalITBIS=round(total_itbis, 2),
            total=round(total, 2),
            notes=f"Preparada desde Contrato {contract.contract_number or contract.id}",
            comentario=snapshot.lines[0].name,
            currency=snapshot.currency,
            paymentType=snapshot.payment_type,
            paymentMethod=snapshot.payment_method,
            registeredBy="RecurringContractBillingService",
            createdAt=issued_at.isoformat(),
            updatedAt=issued_at.isoformat(),
            items=items,
        )
