"""Firestore-backed feature flag loader with an environment default.

The flag document remains the override. When it is absent (or the field is not
set) the environment default applies: enabled outside production, disabled in
production. Read errors still fail closed and never infer a rollout path.
"""

from __future__ import annotations


def _default_enabled() -> bool:
    try:
        from config import Config
        return bool(getattr(Config, "RECURRING_CONTRACT_ENGINE_V2_DEFAULT", False))
    except Exception:
        return False


def firestore_recurring_contract_flag_loader(db, company_id: str, sandbox: bool) -> bool:
    if not db or not company_id:
        return _default_enabled()
    try:
        prefix = "sandbox_" if sandbox else ""
        snapshot = (
            db.collection("companies")
            .document(company_id)
            .collection(prefix + "config")
            .document("feature_flags")
            .get()
        )
        if not getattr(snapshot, "exists", False):
            return _default_enabled()
        return bool((snapshot.to_dict() or {}).get("recurring_contract_engine_v2", _default_enabled()))
    except Exception:
        # Rollout must fail closed on read errors; never authorize V2 by mistake.
        return False
