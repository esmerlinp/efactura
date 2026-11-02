from decimal import Decimal

from app.services.ir17_service import _firestore_safe


def test_firestore_safe_converts_nested_decimal_values():
    result = _firestore_safe({"rate": Decimal("0.15"), "items": [{"tax": Decimal("1.50")}]})
    assert result == {"rate": "0.15", "items": [{"tax": "1.50"}]}
