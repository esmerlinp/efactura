"""Prueba de integración de concurrencia contra el emulador de Firestore (opcional).

Se ejecuta solo cuando hay un emulador disponible, definiendo la variable de
entorno ``FIRESTORE_EMULATOR_HOST`` (p. ej. ``localhost:8080``). El emulador se
puede levantar con:

    gcloud beta emulators firestore start --host-port=localhost:8080
    export FIRESTORE_EMULATOR_HOST=localhost:8080
    export FIRESTORE_PROJECT_ID=vykone-demo
    python -m pytest tests/test_cash_emulator_integration.py -q

En ausencia del emulador, la prueba se omite (``pytest.skip``). El doble en
memoria (``tests/cash_firestore_double.py``) cubre la lógica de guardas de forma
determinista; esta prueba valida las primitivas atómicas reales de Firestore.
"""
import os
import threading

import pytest


FIRESTORE_EMULATOR_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST")

pytestmark = pytest.mark.skipif(
    not FIRESTORE_EMULATOR_HOST,
    reason="Requiere FIRESTORE_EMULATOR_HOST (emulador de Firestore) para ejecutarse.",
)


@pytest.fixture
def emulator_env():
    from app.services import db_service
    assert db_service.firebase_initialized, "Firebase no inicializado contra el emulador."
    return db_service


def _register_id():
    import uuid
    return f"reg-int-{uuid.uuid4().hex[:8]}"


def test_two_concurrent_opens_only_one_wins(emulator_env):
    from app.services.db_service import DatabaseService, CashRegisterOccupiedError

    register_id = _register_id()
    company_id = f"itest-{register_id}"
    results = []
    errors = []

    def open_it(user):
        try:
            DatabaseService.open_cash_shift(
                "itest-owner",
                {"registerId": register_id, "openedByUserId": user,
                 "openedByUserEmail": f"{user}@x.com", "openingAmount": 0.0},
                company_id=company_id, sandbox=True,
            )
            results.append(user)
        except CashRegisterOccupiedError:
            errors.append(user)

    threads = [threading.Thread(target=open_it, args=(f"u{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1
    assert len(errors) == 1


def test_sale_after_closing_is_rejected(emulator_env):
    from app.services.db_service import DatabaseService, CashShiftLockError

    register_id = _register_id()
    company_id = f"itest-{register_id}"
    shift = DatabaseService.open_cash_shift(
        "itest-owner",
        {"registerId": register_id, "openedByUserId": "cajero",
         "openedByUserEmail": "cajero@x.com", "openingAmount": 0.0},
        company_id=company_id, sandbox=True,
    )
    assert shift
    DatabaseService.initiate_close_cash_shift("itest-owner", shift["id"], company_id=company_id, sandbox=True)

    with pytest.raises(CashShiftLockError):
        DatabaseService.register_sale_cash_transactions(
            "itest-owner", register_id, shift["id"],
            [{"id": "tx-int-1", "shiftId": shift["id"], "type": "SALE",
              "amount": 10.0, "paymentMethod": "Efectivo"}],
            company_id=company_id, sandbox=True,
        )
