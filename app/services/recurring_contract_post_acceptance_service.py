"""Idempotent post-acceptance effects for recurring-contract invoices."""

from __future__ import annotations

from typing import Any, Callable

from app.models.recurring_contract_emission import PostAcceptanceEffectType


class RecurringContractPostAcceptanceService:
    def __init__(self, *, effects_store: Any, effect_handlers: dict[PostAcceptanceEffectType, Callable]):
        self.effects_store = effects_store
        self.effect_handlers = effect_handlers

    def process(self, *, owner_uid: str, company_id: str, invoice_id: str, invoice: dict, sandbox: bool = True):
        if str(invoice.get("dgiiStatus", "")).upper() != "ACCEPTED":
            return {"success": False, "status": "not_accepted", "effects": {}}
        results = {}
        for event_type, handler in self.effect_handlers.items():
            effect = self.effects_store.claim_or_get(
                owner_uid=owner_uid,
                company_id=company_id,
                invoice_id=invoice_id,
                event_type=event_type,
                sandbox=sandbox,
            )
            if effect.status == "PROCESSING":
                results[event_type.value] = {"status": "already_processing"}
                continue
            if effect.status == "COMPLETED":
                results[event_type.value] = effect.result or {}
                continue
            try:
                result = handler(owner_uid=owner_uid, company_id=company_id, invoice_id=invoice_id, invoice=invoice, sandbox=sandbox)
                self.effects_store.complete(effect, result=result, sandbox=sandbox)
                results[event_type.value] = result
            except Exception as exc:
                self.effects_store.fail(effect, error=str(exc), sandbox=sandbox)
                results[event_type.value] = {"error": str(exc)}
        complete = all(
            isinstance(value, dict) and value.get("status") not in {"already_processing"}
            and "error" not in value for value in results.values()
        )
        return {"success": complete, "status": "completed" if complete else "pending_effects", "effects": results}
