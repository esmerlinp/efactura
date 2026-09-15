from decimal import Decimal

import pytest

from app.services.insurance_cost_calculator import InsuranceCostError, calculate_contribution


def test_percentage_split():
    result = calculate_contribution("2000", {"type": "percentage", "value": "60"}, {"type": "percentage", "value": "40"})
    assert result["companyAmount"] == Decimal("1200.00")
    assert result["employeeAmount"] == Decimal("800.00")


def test_fixed_split():
    result = calculate_contribution(2000, {"type": "fixed_amount", "value": "1500"}, {"type": "fixed_amount", "value": "500"})
    assert result["companyAmount"] == Decimal("1500.00")
    assert result["employeeAmount"] == Decimal("500.00")


def test_company_fixed_employee_remainder():
    result = calculate_contribution(2000, {"type": "fixed_amount", "value": "1000"}, {"type": "remainder", "value": None})
    assert result["employeeAmount"] == Decimal("1000.00")


def test_company_percentage_employee_remainder():
    result = calculate_contribution(2000, {"type": "percentage", "value": "60"}, {"type": "remainder", "value": None})
    assert result["employeeAmount"] == Decimal("800.00")


def test_employee_fixed_company_remainder():
    result = calculate_contribution(2000, {"type": "remainder", "value": None}, {"type": "fixed_amount", "value": "500"})
    assert result["companyAmount"] == Decimal("1500.00")


@pytest.mark.parametrize("company,employee", [
    ({"type": "percentage", "value": "101"}, {"type": "remainder"}),
    ({"type": "fixed_amount", "value": "2500"}, {"type": "fixed_amount", "value": "500"}),
    ({"type": "remainder"}, {"type": "remainder"}),
])
def test_invalid_rules(company, employee):
    with pytest.raises(InsuranceCostError):
        calculate_contribution(2000, company, employee)
