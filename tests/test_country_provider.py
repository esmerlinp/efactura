"""Tests para CountryProviderFactory — sin dependencia de Flask ni Firestore."""

import sys
import types
from unittest.mock import MagicMock


def _setup_mocks():
    """Mock dependencias externas para pruebas unitarias aisladas."""
    # --- Mock flask ---
    flask_mod = types.ModuleType("flask")
    sys.modules["flask"] = flask_mod

    # --- Mock app package ---
    app_mod = types.ModuleType("app")
    app_mod.__path__ = ["app"]
    sys.modules["app"] = app_mod

    app_services = types.ModuleType("app.services")
    app_services.__path__ = ["app/services"]
    sys.modules["app.services"] = app_services

    app_countries = types.ModuleType("app.countries")
    app_countries.__path__ = ["app/countries"]
    sys.modules["app.countries"] = app_countries

    app_countries_do = types.ModuleType("app.countries.do")
    app_countries_do.__path__ = ["app/countries/do"]
    sys.modules["app.countries.do"] = app_countries_do

    # --- Mock TaxCalculator ABC ---
    from abc import ABC, abstractmethod

    class MockTaxCalculator(ABC):
        country_code: str = ""
        country_name: str = ""
        currency: str = ""

        @abstractmethod
        def calculate_employee_taxes(self, income, period_type="mensual", context=None):
            pass

        @abstractmethod
        def calculate_employer_contributions(self, income, period_type="mensual", context=None):
            pass

        @abstractmethod
        def get_rates(self):
            pass

    tax_calc_mod = types.ModuleType("app.services.tax_calculator")
    tax_calc_mod.TaxCalculator = MockTaxCalculator
    tax_calc_mod.TaxCalculatorFactory = type(
        "Factory", (), {"create": staticmethod(lambda c, r=None: None)}
    )
    sys.modules["app.services.tax_calculator"] = tax_calc_mod


_setup_mocks()

from app.countries.base import BaseCountryProvider
from app.services.country_provider import CountryProviderFactory


class _TestProvider(BaseCountryProvider):
    country_code = "XX"
    country_name = "Testland"
    currency = "XXX"
    tax_authority = "TAX"

    def get_default_chart(self):
        return [{"code": "1", "name": "Test"}]

    def get_tax_rules(self):
        return {"rate": 0.1}

    def get_regimen_rules(self):
        return {"test": True}

    def get_payroll_rules(self):
        return {"afp": 0.02}

    def get_labor_rules(self):
        return {"days": 30}

    def get_tax_calculator(self, tax_rates=None):
        return None

    def supports_feature(self, feature):
        return feature in ["test"]


class TestCountryProviderFactory:
    """Pruebas de unidad para CountryProviderFactory."""

    def setup_method(self):
        CountryProviderFactory._registry = {}

    def test_contract_enforced(self):
        """BaseCountryProvider ABC fuerza el contrato correctamente."""
        tp = _TestProvider()
        assert tp.country_code == "XX"
        assert tp.country_name == "Testland"
        assert tp.get_default_chart() == [{"code": "1", "name": "Test"}]
        assert tp.supports_feature("test") is True
        assert tp.supports_feature("nope") is False

    def test_register_and_create(self):
        CountryProviderFactory.register("XX", _TestProvider)
        provider = CountryProviderFactory.create("XX")
        assert provider is not None
        assert isinstance(provider, _TestProvider)
        assert provider.country_code == "XX"

    def test_create_with_lowercase(self):
        CountryProviderFactory.register("XX", _TestProvider)
        provider = CountryProviderFactory.create("xx")
        assert provider is not None
        assert provider.country_code == "XX"

    def test_create_unknown_returns_none(self):
        provider = CountryProviderFactory.create("ZZ")
        assert provider is None

    def test_create_do_provider(self):
        """Verifica que create('DO') registre y devuelva DOProvider."""
        provider = CountryProviderFactory.create("DO")
        assert provider is not None
        assert provider.country_code == "DO"
        assert provider.country_name == "República Dominicana"
        assert provider.currency == "DOP"
        assert provider.tax_authority == "DGII"

    def test_unknown_country_returns_none(self):
        """Países no soportados deben retornar None."""
        assert CountryProviderFactory.create("MX") is None
        assert CountryProviderFactory.create("US") is None
        assert CountryProviderFactory.create("ES") is None

    def test_get_supported_countries(self):
        CountryProviderFactory.register("XX", _TestProvider)
        countries = CountryProviderFactory.get_supported_countries()
        assert isinstance(countries, list)
        codes = {c["code"] for c in countries}
        assert "XX" in codes

    def test_get_supported_countries_after_lazy_register(self):
        """create('DO') debe agregar DO a la lista de países soportados."""
        CountryProviderFactory.create("DO")
        countries = CountryProviderFactory.get_supported_countries()
        codes = {c["code"] for c in countries}
        assert "DO" in codes

    def test_multiple_registrations(self):
        class ProviderA(BaseCountryProvider):
            country_code = "AA"
            country_name = "A"
            currency = "AAA"
            tax_authority = "TA"
            def get_default_chart(self): return []
            def get_tax_rules(self): return {}
            def get_regimen_rules(self): return {}
            def get_payroll_rules(self): return {}
            def get_labor_rules(self): return {}
            def get_tax_calculator(self, r=None): return None
            def supports_feature(self, f): return False

        class ProviderB(BaseCountryProvider):
            country_code = "BB"
            country_name = "B"
            currency = "BBB"
            tax_authority = "TB"
            def get_default_chart(self): return []
            def get_tax_rules(self): return {}
            def get_regimen_rules(self): return {}
            def get_payroll_rules(self): return {}
            def get_labor_rules(self): return {}
            def get_tax_calculator(self, r=None): return None
            def supports_feature(self, f): return False

        CountryProviderFactory.register("AA", ProviderA)
        CountryProviderFactory.register("BB", ProviderB)

        assert CountryProviderFactory.create("AA").country_code == "AA"
        assert CountryProviderFactory.create("BB").country_code == "BB"

    def test_do_provider_get_default_chart(self):
        provider = CountryProviderFactory.create("DO")
        chart = provider.get_default_chart()
        assert isinstance(chart, list)
        assert len(chart) > 0

    def test_do_provider_get_tax_rules(self):
        provider = CountryProviderFactory.create("DO")
        rules = provider.get_tax_rules()
        assert isinstance(rules, dict)
        assert "itbis" in rules

    def test_do_provider_get_payroll_rules(self):
        provider = CountryProviderFactory.create("DO")
        payroll = provider.get_payroll_rules()
        assert isinstance(payroll, dict)
        assert payroll.get("afp_employee_rate") == 0.0287

    def test_do_provider_get_labor_rules(self):
        provider = CountryProviderFactory.create("DO")
        labor = provider.get_labor_rules()
        assert isinstance(labor, dict)
        assert labor.get("working_days_monthly") == 23.83

    def test_do_provider_supports_features(self):
        provider = CountryProviderFactory.create("DO")
        assert provider.supports_feature("dgii") is True
        assert provider.supports_feature("electronic_invoicing") is True
        assert provider.supports_feature("payroll") is True
        assert provider.supports_feature("fake_feature") is False
