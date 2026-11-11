from app.models.recurring_contract_emission import FiscalAttemptStatus


def test_accepted_attempt_is_reused_after_worker_restart():
    calls = []

    class Store:
        def get_for_occurrence(self, **kwargs):
            return [type("Attempt", (), {"status": FiscalAttemptStatus.ACCEPTED})()]

    class Outbox:
        def claim(self, **kwargs):
            return type("Command", (), {"occurrence_id": "occ", "fencing_token": 2})()

        def finish(self, **kwargs):
            return {"status": "completed"}

    from app.services.recurring_contract_emission_worker import RecurringContractEmissionWorker
    worker = RecurringContractEmissionWorker(
        outbox=Outbox(), attempts_store=Store(), company_loader=lambda *_: {},
        sequence_consumer=lambda *_args, **_kwargs: calls.append("sequence") or ("E31X", "log"),
        emitter=lambda *_args, **_kwargs: calls.append("emit") or {"success": True, "dgiiStatus": "ACCEPTED"},
    )
    prepared = type("Prepared", (), {"invoice": type("Invoice", (), {"model_dump": lambda self, **_: {"ecfType": "Factura de Crédito Fiscal (E31)", "total": 100}})()})()
    result = worker.process(command_id="cmd", owner_uid="owner", company_id="company", worker_id="worker", prepared=prepared)
    assert result["recovered"] is True
    assert calls == []


def test_ambiguous_attempt_is_not_reemitted_after_restart():
    calls = []

    class Attempt:
        status = FiscalAttemptStatus.UNKNOWN

    class Store:
        def get_for_occurrence(self, **kwargs):
            return [Attempt()]

    class Outbox:
        def claim(self, **kwargs):
            return type("Command", (), {"occurrence_id": "occ", "fencing_token": 1})()

    from app.services.recurring_contract_emission_worker import RecurringContractEmissionWorker
    worker = RecurringContractEmissionWorker(
        outbox=Outbox(), attempts_store=Store(), company_loader=lambda *_: {},
        sequence_consumer=lambda *_args, **_kwargs: calls.append("sequence") or ("E31X", "log"),
        emitter=lambda *_args, **_kwargs: calls.append("emit") or {"success": True, "dgiiStatus": "ACCEPTED"},
    )
    prepared = type("Prepared", (), {"invoice": type("Invoice", (), {"model_dump": lambda self, **_: {"ecfType": "Factura de Crédito Fiscal (E31)", "total": 100}})()})()
    result = worker.process(command_id="cmd", owner_uid="owner", company_id="company", worker_id="worker", prepared=prepared)
    assert result["requires_reconciliation"] is True
    assert calls == []
