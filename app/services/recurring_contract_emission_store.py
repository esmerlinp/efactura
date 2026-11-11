"""Scoped stores for fiscal attempts and post-acceptance effects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.recurring_contract_emission import (
    PostAcceptanceEffect,
    PostAcceptanceEffectType,
    RecurringContractEmissionAttempt,
)


class RecurringContractEmissionStore:
    def __init__(self, firestore_db: Any):
        self.db = firestore_db

    def _collection(self, company_id, name, sandbox):
        prefix = "sandbox_" if sandbox else ""
        return self.db.collection("companies").document(company_id).collection(prefix + name)

    def save(self, attempt: RecurringContractEmissionAttempt, *, sandbox=True):
        ref = self._collection(attempt.company_id, "contract_emission_attempts", sandbox).document(attempt.attempt_id)
        ref.set(attempt.model_dump(mode="json"))

    def get(self, *, company_id, attempt_id, owner_uid, sandbox=True):
        snapshot = self._collection(company_id, "contract_emission_attempts", sandbox).document(attempt_id).get()
        if not getattr(snapshot, "exists", False):
            return None
        data = snapshot.to_dict()
        self._assert_scope(data, owner_uid, company_id)
        return RecurringContractEmissionAttempt(**data)

    def get_for_occurrence(self, *, company_id, occurrence_id, owner_uid, sandbox=True):
        docs = self._collection(company_id, "contract_emission_attempts", sandbox).where("occurrence_id", "==", occurrence_id).get()
        result = []
        for snapshot in docs:
            data = snapshot.to_dict()
            self._assert_scope(data, owner_uid, company_id)
            result.append(RecurringContractEmissionAttempt(**data))
        return result

    @staticmethod
    def _assert_scope(data, owner_uid, company_id):
        if data.get("owner_uid") != owner_uid or data.get("company_id") != company_id:
            raise PermissionError("El intento fiscal no pertenece al ámbito solicitado")


class RecurringContractEffectsStore:
    def __init__(self, firestore_db: Any):
        self.db = firestore_db

    def _collection(self, company_id, sandbox):
        prefix = "sandbox_" if sandbox else ""
        return self.db.collection("companies").document(company_id).collection(prefix + "contract_post_acceptance_effects")

    @staticmethod
    def logical_id(invoice_id: str, event_type: PostAcceptanceEffectType) -> str:
        return f"{invoice_id}:{event_type.value}"

    def claim_or_get(self, *, owner_uid, company_id, invoice_id, event_type, sandbox=True):
        ref = self._collection(company_id, sandbox).document(self.logical_id(invoice_id, event_type))
        snapshot = ref.get()
        if getattr(snapshot, "exists", False):
            data = snapshot.to_dict()
            if data.get("owner_uid") != owner_uid or data.get("company_id") != company_id:
                raise PermissionError("El efecto no pertenece al ámbito solicitado")
            return PostAcceptanceEffect(**data)
        effect = PostAcceptanceEffect(
            effect_id=ref.path.rsplit("/", 1)[-1],
            owner_uid=owner_uid,
            company_id=company_id,
            invoice_id=invoice_id,
            event_type=event_type,
        )
        ref.create(effect.model_dump(mode="json"))
        return effect

    def complete(self, effect, *, result=None, sandbox=True):
        updated = effect.model_copy(update={"status": "COMPLETED", "result": result or {}, "updated_at": datetime.now(timezone.utc)})
        self._collection(effect.company_id, sandbox).document(effect.effect_id).set(updated.model_dump(mode="json"))
        return updated

    def fail(self, effect, *, error, sandbox=True):
        updated = effect.model_copy(update={"status": "PENDING", "error": error, "updated_at": datetime.now(timezone.utc)})
        self._collection(effect.company_id, sandbox).document(effect.effect_id).set(updated.model_dump(mode="json"))
        return updated
