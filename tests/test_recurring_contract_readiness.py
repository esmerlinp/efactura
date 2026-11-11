from app.services.recurring_contract_observability_service import RecurringContractObservabilityService
from app.services.recurring_contract_flag_loader import firestore_recurring_contract_flag_loader


class Item:
    def __init__(self, status, lease_expires_at=None):
        self.status = status
        self.lease_expires_at = lease_expires_at


def test_observability_detects_operational_risks():
    summary = RecurringContractObservabilityService.summarize(
        attempts=[Item("UNKNOWN"), Item("ACCEPTED")],
        outbox_commands=[Item("retry_wait"), Item("failed")],
        occurrences=[Item("processing", lease_expires_at="expired")],
    )
    assert summary["unknown_attempts"] == 1
    assert summary["outbox_retry_wait"] == 1
    assert summary["outbox_failed"] == 1
    assert summary["expired_leases"] == 1
    assert set(RecurringContractObservabilityService.alert_candidates(summary)) >= {"unknown_attempts", "outbox_failed"}


def test_feature_flag_read_error_fails_closed():
    class Broken:
        def collection(self, _):
            raise RuntimeError("unavailable")
    assert firestore_recurring_contract_flag_loader(Broken(), "company", True) is False


def test_feature_flag_uses_environment_default_when_document_missing(monkeypatch):
    from config import Config

    class Missing:
        def collection(self, *_):
            return self

        def document(self, *_):
            return self

        def get(self):
            class Snap:
                exists = False

                def to_dict(self):
                    return {}

            return Snap()

    monkeypatch.setattr(Config, "RECURRING_CONTRACT_ENGINE_V2_DEFAULT", True)
    assert firestore_recurring_contract_flag_loader(Missing(), "company", True) is True

    monkeypatch.setattr(Config, "RECURRING_CONTRACT_ENGINE_V2_DEFAULT", False)
    assert firestore_recurring_contract_flag_loader(Missing(), "company", True) is False


def test_feature_flag_document_value_overrides_environment_default(monkeypatch):
    from config import Config

    class Present:
        def collection(self, *_):
            return self

        def document(self, *_):
            return self

        def get(self):
            class Snap:
                exists = True

                def to_dict(self):
                    return {"recurring_contract_engine_v2": False}

            return Snap()

    monkeypatch.setattr(Config, "RECURRING_CONTRACT_ENGINE_V2_DEFAULT", True)
    assert firestore_recurring_contract_flag_loader(Present(), "company", True) is False
