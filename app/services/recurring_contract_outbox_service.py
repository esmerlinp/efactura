"""Transactional outbox coordination for recurring-contract commands."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.models.recurring_contract_outbox import (
    OutboxCommandError,
    OutboxCommandStatus,
    RecurringContractEmissionOutboxCommand,
)


class OutboxNotFoundError(LookupError):
    pass


class OutboxLeaseError(RuntimeError):
    pass


class OutboxCommandService:
    COLLECTION = "contract_emission_outbox"

    def __init__(self, firestore_db: Any, *, clock: Callable[[], datetime] | None = None):
        self.db = firestore_db
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _collection(self, company_id: str, sandbox: bool):
        prefix = "sandbox_" if sandbox else ""
        return self.db.collection("companies").document(company_id).collection(prefix + self.COLLECTION)

    @staticmethod
    def logical_id(company_id: str, occurrence_id: str, command_type: str) -> str:
        return hashlib.sha256(f"{company_id}:{occurrence_id}:{command_type}".encode()).hexdigest()

    def get(self, *, owner_uid: str, company_id: str, command_id: str, sandbox: bool = True):
        snapshot = self._collection(company_id, sandbox).document(command_id).get()
        if not getattr(snapshot, "exists", False):
            return None
        data = snapshot.to_dict()
        self._assert_scope(data, owner_uid, company_id)
        return RecurringContractEmissionOutboxCommand(**data)

    def create_idempotent(
        self,
        *,
        owner_uid: str,
        company_id: str,
        contract_id: str,
        occurrence_id: str,
        attempt_id: str,
        command_type: str = "prepare_emission",
        sandbox: bool = True,
        max_attempts: int = 5,
    ):
        command_id = self.logical_id(company_id, occurrence_id, command_type)
        ref = self._collection(company_id, sandbox).document(command_id)

        def operation(transaction):
            current = self._snapshot(transaction.get(ref))
            if current and current.exists:
                data = current.to_dict()
                self._assert_scope(data, owner_uid, company_id)
                return RecurringContractEmissionOutboxCommand(**data)
            command = RecurringContractEmissionOutboxCommand(
                command_id=command_id,
                owner_uid=owner_uid,
                company_id=company_id,
                contract_id=contract_id,
                occurrence_id=occurrence_id,
                attempt_id=attempt_id,
                command_type=command_type,
                max_attempts=max_attempts,
            )
            transaction.create(ref, command.model_dump(mode="json"))
            return command

        return self._run_transaction(operation)

    def claim(self, *, owner_uid: str, company_id: str, command_id: str, worker_id: str, ttl_seconds: int = 120, sandbox: bool = True):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds debe ser positivo")
        ref = self._collection(company_id, sandbox).document(command_id)
        now = self.clock()

        def operation(transaction):
            current = self._required_snapshot(transaction.get(ref))
            data = current.to_dict()
            self._assert_scope(data, owner_uid, company_id)
            status = OutboxCommandStatus(data["status"])
            if status in {OutboxCommandStatus.COMPLETED, OutboxCommandStatus.CANCELLED}:
                raise OutboxLeaseError("El comando ya no puede procesarse")
            if int(data.get("attempt_count", 0)) >= int(data.get("max_attempts", 5)):
                raise OutboxLeaseError("El comando agotó sus reintentos")
            expiry = self._parse_datetime(data.get("lease_expires_at"))
            if data.get("lease_owner") and data["lease_owner"] != worker_id and expiry and expiry > now:
                raise OutboxLeaseError("El comando tiene un lease vigente")
            token = int(data.get("fencing_token", 0)) + 1
            data.update({
                "status": OutboxCommandStatus.PROCESSING.value,
                "lease_owner": worker_id,
                "lease_expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
                "fencing_token": token,
                "attempt_count": int(data.get("attempt_count", 0)) + 1,
                "updated_at": now.isoformat(),
            })
            transaction.set(ref, data)
            return RecurringContractEmissionOutboxCommand(**data)

        return self._run_transaction(operation)

    def finish(
        self,
        *,
        owner_uid: str,
        company_id: str,
        command_id: str,
        worker_id: str,
        fencing_token: int,
        success: bool,
        retryable: bool = False,
        error: str | None = None,
        error_class: str | None = None,
        retry_delay_seconds: int = 60,
        sandbox: bool = True,
    ):
        ref = self._collection(company_id, sandbox).document(command_id)
        now = self.clock()

        def operation(transaction):
            current = self._required_snapshot(transaction.get(ref))
            data = current.to_dict()
            self._assert_scope(data, owner_uid, company_id)
            if data.get("lease_owner") != worker_id or int(data.get("fencing_token", -1)) != fencing_token:
                raise OutboxLeaseError("Fencing token o propietario inválido")
            command = RecurringContractEmissionOutboxCommand(**data)
            if success:
                target = OutboxCommandStatus.COMPLETED
            elif retryable and command.attempt_count < command.max_attempts:
                target = OutboxCommandStatus.RETRY_WAIT
            else:
                target = OutboxCommandStatus.FAILED
            updated = command.transition_to(target)
            payload = updated.model_dump(mode="json")
            payload.update({
                "last_error": error,
                "error_class": error_class,
                "available_at": (now + timedelta(seconds=retry_delay_seconds)).isoformat() if target == OutboxCommandStatus.RETRY_WAIT else data.get("available_at"),
                "lease_owner": None,
                "lease_expires_at": None,
                "updated_at": now.isoformat(),
            })
            transaction.set(ref, payload)
            return RecurringContractEmissionOutboxCommand(**payload)

        return self._run_transaction(operation)

    def recover_expired(self, *, owner_uid: str, company_id: str, command_id: str, sandbox: bool = True):
        """Clear an expired lease without advancing the command attempt."""
        ref = self._collection(company_id, sandbox).document(command_id)
        now = self.clock()

        def operation(transaction):
            current = self._required_snapshot(transaction.get(ref))
            data = current.to_dict()
            self._assert_scope(data, owner_uid, company_id)
            expiry = self._parse_datetime(data.get("lease_expires_at"))
            if not expiry or expiry > now:
                raise OutboxLeaseError("El lease aún está vigente")
            data.update({"lease_owner": None, "lease_expires_at": None, "status": OutboxCommandStatus.RETRY_WAIT.value, "available_at": now.isoformat(), "updated_at": now.isoformat()})
            transaction.set(ref, data)
            return RecurringContractEmissionOutboxCommand(**data)

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
            raise OutboxNotFoundError("Comando outbox no encontrado")
        return snapshot

    @staticmethod
    def _assert_scope(data, owner_uid, company_id):
        if data.get("owner_uid") != owner_uid or data.get("company_id") != company_id:
            raise PermissionError("El comando no pertenece al ámbito solicitado")

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))
