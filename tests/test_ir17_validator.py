from app.services.ir17_validator import validate_ir17


def test_invalid_period_and_negative_base():
    result = validate_ir17({"period": "202613", "rnc": "123", "line_items": [{"number": 1, "base": "-1", "rate": "0.15"}]})
    assert not result["valid"]
    assert any("mes" in error.lower() for error in result["errors"])
    assert any("negativa" in error.lower() for error in result["errors"])


def test_valid_period_and_rnc():
    result = validate_ir17({"period": "202601", "rnc": "123456789", "line_items": [{"number": 1, "base": "10", "rate": "0.15"}]})
    assert result["valid"]
