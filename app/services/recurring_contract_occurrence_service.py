"""Transactional persistence and leases for recurring contract occurrences."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.models.recurring_contract import RecurringContract
from app.models.recurring_contract_occurrence import (
    BillingOccurrenceError,
    BillingOccurrenceStatus,
    RecurringContractBillingOccurrence,
)
from app.services.recurring_contract_billing_service import (
    PreparedRecurringInvoice,
    RecurringContractBillingService,
)


class OccurrenceNotFoundError(LookupError):
    pass


class OccurrenceLeaseError(RuntimeError):
    pass


class RecurringContractOccurrenceService:
    COLLECTION = "contract_billing_occurrences"

    def __init__(self, firestore_db: Any, *, clock: Callable[[], datetime] | None = None):
        self.db = firestore_db
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _collection(self, company_id: str, sandbox: bool):
        prefix = "sandbox_" if sandbox else ""
        return self.db.collection("companies").document(company_id).collection(prefix + self.COLLECTION)

    @staticmethod
    def logical_id(company_id: str, contract_id: str, billing_period_key: str) -> str:
        raw = f"{company_id}:{contract_id}:{billing_period_key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, *, owner_uid: str, company_id: str, occurrence_id: str, sandbox: bool = True) -> RecurringContractBillingOccurrence | None:
        doc = self._collection(company_id, sandbox).document(occurrence_id).get()
        if not getattr(doc, "exists", False):
            return None
        data = doc.to_dict()
        self._assert_scope(data, owner_uid, company_id)
        return RecurringContractBillingOccurrence(**data)

    def create_idempotent(
        self,
        *,
        owner_uid: str,
        company_id: str,
        contract_id: str,
        billing_period_key: str,
        period_start: str,
        period_end: str,
        occurrence_date: str,
        sandbox: bool = True,
    ) -> RecurringContractBillingOccurrence:
        occurrence_id = self.logical_id(company_id, contract_id, billing_period_key)
        ref = self._collection(company_id, sandbox).document(occurrence_id)

        def operation(transaction):
            current = self._snapshot(transaction.get(ref))
            if current and current.exists:
                data = current.to_dict()
                self._assert_scope(data, owner_uid, company_id)
                return RecurringContractBillingOccurrence(**data)
            occurrence = RecurringContractBillingOccurrence(
                id=occurrence_id,
                owner_uid=owner_uid,
                company_id=company_id,
                contract_id=contract_id,
                billing_period_key=billing_period_key,
                period_start=period_start,
                period_end=period_end,
                occurrence_date=occurrence_date,
            )
            transaction.create(ref, occurrence.model_dump(mode="json"))
            return occurrence

        return self._run_transaction(operation)

    def prepare_once(
        self,
        *,
        occurrence: RecurringContractBillingOccurrence,
        contract: RecurringContract,
        sandbox: bool = True,
    ) -> tuple[RecurringContractBillingOccurrence, PreparedRecurringInvoice]:
        self._assert_scope(occurrence.model_dump(), contract.owner_uid, contract.company_id)
        prepared = RecurringContractBillingService.prepare_invoice(
            contract,
            occurrence_date=datetime.fromisoformat(occurrence.occurrence_date).date(),
        )
        if occurrence.invoice_id:
            prepared.invoice.id = occurrence.invoice_id
        invoice_hash = self._hash_prepared(prepared)
        ref = self._collection(contract.company_id, sandbox).document(occurrence.id)

        def operation(transaction):
            current = self._required_snapshot(transaction.get(ref))
            data = current.to_dict()
            self._assert_scope(data, contract.owner_uid, contract.company_id)
            if data.get("prepared_invoice_hash") and data["prepared_invoice_hash"] != invoice_hash:
                raise BillingOccurrenceError("La ocurrencia ya fue preparada con condiciones distintas")
            if data.get("status") == BillingOccurrenceStatus.COMPLETED.value:
                return RecurringContractBillingOccurrence(**data)
            data.update({
                "status": BillingOccurrenceStatus.PREPARED.value,
                "invoice_id": prepared.invoice.id,
                "prepared_invoice_hash": invoice_hash,
                "updated_at": self.clock().isoformat(),
            })
            transaction.set(ref, data)
            return RecurringContractBillingOccurrence(**data)

        return self._run_transaction(operation), prepared

    def acquire_lease(self, *, owner_uid: str, company_id: str, occurrence_id: str, worker_id: str, ttl_seconds: int = 120, sandbox: bool = True) -> RecurringContractBillingOccurrence:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds debe ser positivo")
        ref = self._collection(company_id, sandbox).document(occurrence_id)
        now = self.clock()

        def operation(transaction):
            current = self._required_snapshot(transaction.get(ref))
            data = current.to_dict()
            self._assert_scope(data, owner_uid, company_id)
            expiry = self._parse_datetime(data.get("lease_expires_at"))
            current_owner = data.get("lease_owner")
            if current_owner and current_owner != worker_id and expiry and expiry > now:
                raise OccurrenceLeaseError("La ocurrencia tiene un lease vigente")
            token = int(data.get("fencing_token", 0)) + 1
            data.update({
                "lease_owner": worker_id,
                "lease_expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
                "fencing_token": token,
                "status": BillingOccurrenceStatus.PROCESSING.value,
                "attempt_count": int(data.get("attempt_count", 0)) + 1,
                "updated_at": now.isoformat(),
            })
            transaction.set(ref, data)
            return RecurringContractBillingOccurrence(**data)

        return self._run_transaction(operation)

    def transition_with_fencing(self, *, owner_uid: str, company_id: str, occurrence_id: str, worker_id: str, fencing_token: int, target: BillingOccurrenceStatus, sandbox: bool = True, error: str | None = None) -> RecurringContractBillingOccurrence:
        ref = self._collection(company_id, sandbox).document(occurrence_id)

        def operation(transaction):
            current = self._required_snapshot(transaction.get(ref))
            data = current.to_dict()
            self._assert_scope(data, owner_uid, company_id)
            if data.get("lease_owner") != worker_id or int(data.get("fencing_token", -1)) != fencing_token:
                raise OccurrenceLeaseError("Fencing token o propietario inválido")
            occurrence = RecurringContractBillingOccurrence(**data)
            updated = occurrence.transition_to(target)
            payload = updated.model_dump(mode="json")
            if error is not None:
                payload["last_error"] = error
            transaction.set(ref, payload)
            return updated

        return self._run_transaction(operation)

    def _run_transaction(self, operation):
        transaction = self.db.transaction()
        try:
            from google.cloud import firestore
            result = firestore.transactional(operation)(transaction)
            if hasattr(result, "__next__"):
                return next(result, None)
            return result
        except (ImportError, AttributeError):
            return operation(transaction)

    @staticmethod
    def _snapshot(value):
        if hasattr(value, "exists"):
            return value
        if hasattr(value, "__next__"):
            return next(value, None)
        return value

    def _required_snapshot(self, value):
        snapshot = self._snapshot(value)
        if not snapshot or not getattr(snapshot, "exists", False):
            raise OccurrenceNotFoundError("Ocurrencia no encontrada")
        return snapshot

    @staticmethod
    def _assert_scope(data: dict, owner_uid: str, company_id: str):
        if data.get("owner_uid") != owner_uid or data.get("company_id") != company_id:
            raise PermissionError("La ocurrencia no pertenece al ámbito solicitado")

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    @staticmethod
    def _hash_prepared(prepared: PreparedRecurringInvoice) -> str:
        # The snapshot fully determines the billable conditions. Volatile
        # fields (generated invoice id, timestamps) must not change the hash,
        # otherwise re-triggering the same period would be rejected.
        payload = prepared.snapshot.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
