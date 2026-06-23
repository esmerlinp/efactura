import pytest
from app.services.tax_engine import (
    TaxEngine,
    calc_rst_isr,
    ITBIS_RATE_GENERAL,
    ITBIS_RATE_REDUCED,
    ISR_CORPORATE_RATE,
    ISR_LARGE_TAXPAYER_RATE,
    WITHHOLDING_ISR_RATES,
    WITHHOLDING_ITBIS_RATES,
    RST_ANNUAL_LIMIT_2026,
)


class TestTaxEngineDefaults:
    def setup_method(self):
        self.engine = TaxEngine()

    def test_itbis_general_rate(self):
        assert self.engine.get_itbis_rate("general") == ITBIS_RATE_GENERAL

    def test_itbis_reduced_rate(self):
        assert self.engine.get_itbis_rate("reduced") == ITBIS_RATE_REDUCED

    def test_isr_corporate_rate(self):
        assert self.engine.get_isr_corporate_rate() == ISR_CORPORATE_RATE

    def test_isr_large_taxpayer_rate(self):
        assert self.engine.get_isr_corporate_rate(is_large_taxpayer=True) == ISR_LARGE_TAXPAYER_RATE

    def test_withholding_isr_goods(self):
        assert self.engine.get_withholding_isr_rate("goods_services") == 0.02

    def test_withholding_isr_professional(self):
        assert self.engine.get_withholding_isr_rate("professional_fees") == 0.10

    def test_withholding_isr_digital_abroad(self):
        assert self.engine.get_withholding_isr_rate("digital_services_abroad") == 0.15

    def test_withholding_itbis_corporate(self):
        assert self.engine.get_withholding_itbis_rate("corporate_goods") == 0.30

    def test_withholding_itbis_legal(self):
        assert self.engine.get_withholding_itbis_rate("legal_services") == 0.75

    def test_rst_limit(self):
        assert self.engine.get_rst_limit() == RST_ANNUAL_LIMIT_2026


class TestTaxEngineSupplier:
    def setup_method(self):
        self.engine = TaxEngine()

    def test_supplier_with_custom_isr_rate(self):
        supplier = {"tasaRetencionISR": 5.0}
        rate = self.engine.get_withholding_isr_rate_for_supplier(supplier)
        assert rate == 0.05

    def test_supplier_foreign_digital_services(self):
        supplier = {"esExtranjero": True, "tasaRetencionISR": 0.0}
        rate = self.engine.get_withholding_isr_rate_for_supplier(supplier)
        assert rate == 0.15

    def test_supplier_isr_withholding_flag(self):
        supplier = {"isrWithholding": True, "esExtranjero": False, "tasaRetencionISR": 0.0}
        rate = self.engine.get_withholding_isr_rate_for_supplier(supplier)
        assert rate == 0.02

    def test_supplier_with_custom_itbis_rate(self):
        supplier = {"tasaRetencionITBIS": 50.0}
        rate = self.engine.get_withholding_itbis_rate_for_supplier(supplier)
        assert rate == 0.50

    def test_supplier_itbis_withholding_flag(self):
        supplier = {"itbisWithholding": True, "tasaRetencionITBIS": 0.0}
        rate = self.engine.get_withholding_itbis_rate_for_supplier(supplier)
        assert rate == 0.30

    def test_supplier_no_withholding(self):
        supplier = {}
        assert self.engine.get_withholding_isr_rate_for_supplier(supplier) == 0.0
        assert self.engine.get_withholding_itbis_rate_for_supplier(supplier) == 0.0

    def test_none_supplier(self):
        assert self.engine.get_withholding_isr_rate_for_supplier(None) == 0.0
        assert self.engine.get_withholding_itbis_rate_for_supplier(None) == 0.0


class TestRstCalculation:
    def test_below_exempt_threshold(self):
        assert calc_rst_isr(400000.0) == 0.0

    def test_exact_exempt_threshold(self):
        assert calc_rst_isr(416220.0) == 0.0

    def test_first_bracket(self):
        tax = calc_rst_isr(500000.0)
        expected = (500000.0 - 416220.0) * 0.15
        assert tax == pytest.approx(expected)

    def test_second_bracket(self):
        tax = calc_rst_isr(700000.0)
        expected = 31216.35 + (700000.0 - 624329.0) * 0.20
        assert tax == pytest.approx(expected, rel=1e-9)

    def test_third_bracket(self):
        tax = calc_rst_isr(900000.0)
        expected = 79775.15 + (900000.0 - 867123.0) * 0.25
        assert tax == pytest.approx(expected, rel=1e-9)

    def test_high_income(self):
        tax = calc_rst_isr(5000000.0)
        expected = 79775.15 + (5000000.0 - 867123.0) * 0.25
        assert tax == pytest.approx(expected, rel=1e-9)


class TestResolveItbisRate:
    def setup_method(self):
        self.engine = TaxEngine()

    def test_reduced_for_tax_code_003(self):
        item = {"codigoImpuesto": "003", "itbisRate": 0.0}
        rate = self.engine.resolve_itbis_rate(item)
        assert rate == ITBIS_RATE_REDUCED

    def test_explicit_rate_wins(self):
        item = {"itbisRate": 0.10, "codigoImpuesto": "003"}
        rate = self.engine.resolve_itbis_rate(item)
        assert rate == 0.10

    def test_general_default(self):
        item = {"itbisRate": 0.0}
        rate = self.engine.resolve_itbis_rate(item)
        assert rate == ITBIS_RATE_GENERAL

    def test_rst_regime_disables_itbis(self):
        item = {"itbisRate": 0.18}
        profile = {"regimenFiscal": "exempt"}
        rate = self.engine.resolve_itbis_rate(item, profile=profile)
        assert rate == 0.0
