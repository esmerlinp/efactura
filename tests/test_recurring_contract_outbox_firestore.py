"""Optional Firestore integration prerequisite test."""

import os

import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("FIRESTORE_EMULATOR_HOST"),
    reason="Firestore Emulator no configurado",
)


def test_firestore_emulator_prerequisites():
    try:
        from google.cloud import firestore
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"SDK Firestore no disponible: {exc}")
    assert firestore is not None
