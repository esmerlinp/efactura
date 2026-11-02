from decimal import Decimal

from app.fiscal_forms.ir17_rules import IR17_LINES
from app.services.ir17_calculator import calculate_ir17


def test_catalog_has_official_24_lines():
    assert len(IR17_LINES) == 24
    assert IR17_LINES[0][2] == "0.15"
    assert IR17_LINES[-1][2] == "0.30"


def test_ir17_totals_match_formulas():
    data = {
        "line_items": [{"number": 1, "concept": "Alquiler", "base": "1000", "rate": "0.15"}],
        "conventions_amount": "20",
        "supplementary_benefits": "100",
        "supplementary_rate": "0.27",
        "authorized_credits": "10",
        "account_payments": "5",
        "prior_balance": "0",
        "surcharges": "2",
        "indemnity_interest": "1",
    }
    result = calculate_ir17(data)
    assert result["total_other_withholdings"] == "150.00"
    assert result["total_other_with_conventions"] == "170.00"
    assert result["supplementary_tax"] == "27.00"
    assert result["tax_due"] == "197.00"
    assert result["difference_to_pay"] == "182.00"
    assert result["total_payable"] == "185.00"


def test_percentage_input_is_supported_for_supplementary_rate():
    data = {"line_items": [], "supplementary_benefits": "100", "supplementary_rate": "27"}
    assert calculate_ir17(data)["supplementary_tax"] == "27.00"
