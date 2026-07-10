from abc import ABC, abstractmethod

from app.services.tax_calculator import TaxCalculator


class BaseCountryProvider(ABC):
    country_code: str = ""
    country_name: str = ""
    currency: str = ""
    tax_authority: str = ""
    tax_authority_full: str = ""
    social_security_name: str = ""
    social_security_full: str = ""
    labor_ministry: str = ""

    @abstractmethod
    def get_default_chart(self) -> list:
        pass

    @abstractmethod
    def get_tax_rules(self) -> dict:
        pass

    @abstractmethod
    def get_regimen_rules(self) -> dict:
        pass

    @abstractmethod
    def get_payroll_rules(self) -> dict:
        pass

    @abstractmethod
    def get_labor_rules(self) -> dict:
        pass

    @abstractmethod
    def get_tax_calculator(self, tax_rates: dict = None) -> TaxCalculator:
        pass

    @abstractmethod
    def get_account_mapping(self) -> dict:
        pass

    @abstractmethod
    def supports_feature(self, feature: str) -> bool:
        pass
