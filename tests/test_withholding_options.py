from app.utils.tax_utils import (
    isr_withholding_options,
    itbis_withholding_options,
    DEFAULT_ISR_PAYMENTS_ABROAD,
)
from app.countries.do.tax_rules import DEFAULT_TAX_RULES


def _values(options):
    return [o["value"] for o in options]


def test_isr_defaults_without_payments_abroad():
    opts = isr_withholding_options(DEFAULT_TAX_RULES)
    assert _values(opts) == [0.02, 0.15, 0.15]


def test_isr_defaults_with_payments_abroad():
    opts = isr_withholding_options(DEFAULT_TAX_RULES, include_payments_abroad=True)
    assert _values(opts) == [0.02, 0.27, 0.15, 0.15]
    assert any("Pagos al Exterior" in o["label"] for o in opts)


def test_isr_payments_abroad_fallback_when_missing():
    rules = {"withholding_isr": {"goods_services": 0.02}}
    opts = isr_withholding_options(rules, include_payments_abroad=True)
    assert _values(opts) == [0.02, DEFAULT_ISR_PAYMENTS_ABROAD]


def test_isr_payments_abroad_excluded_when_zero():
    rules = {"withholding_isr": {"goods_services": 0.02, "payments_abroad": 0.0}}
    opts = isr_withholding_options(rules, include_payments_abroad=True)
    assert _values(opts) == [0.02]


def test_isr_zero_rates_excluded():
    rules = {"withholding_isr": {"goods_services": 0, "professional_fees": 0.10}}
    opts = isr_withholding_options(rules)
    assert _values(opts) == [0.10]


def test_isr_label_format():
    rules = {"withholding_isr": {"goods_services": 0.02}}
    opts = isr_withholding_options(rules)
    assert opts[0]["label"] == "2% — Bienes y servicios"


def test_itbis_defaults():
    opts = itbis_withholding_options(DEFAULT_TAX_RULES)
    assert _values(opts) == [0.30, 0.75, 1.00]


def test_itbis_fallback_to_withholding_vat():
    rules = {"withholding_vat": {"corporate_goods": 0.30}}
    opts = itbis_withholding_options(rules)
    assert _values(opts) == [0.30]


def test_empty_rules_return_empty():
    assert isr_withholding_options({}) == []
    assert itbis_withholding_options({}) == []
