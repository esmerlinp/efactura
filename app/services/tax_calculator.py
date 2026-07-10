"""TaxCalculator — Abstracción multi-país para cálculo de impuestos de nómina."""

from abc import ABC, abstractmethod
from typing import Optional


class TaxCalculator(ABC):
    """Interfaz base para calculadoras de impuestos por país."""

    country_code: str = ""
    country_name: str = ""
    currency: str = ""

    @abstractmethod
    def calculate_employee_taxes(self, income: float, period_type: str = "mensual",
                                  context: dict = None) -> dict:
        """Calcula impuestos y deducciones del empleado.

        Returns:
            Dict con {social_security, income_tax, other_deductions, total_deductions}
        """
        pass

    @abstractmethod
    def calculate_employer_contributions(self, income: float, period_type: str = "mensual",
                                          context: dict = None) -> dict:
        """Calcula aportes del empleador.

        Returns:
            Dict con {social_security, other, total}
        """
        pass

    @abstractmethod
    def get_rates(self) -> dict:
        """Retorna las tasas impositivas vigentes."""
        pass

    @classmethod
    def validate_employee_data(cls, employee: dict) -> dict:
        """Valida que el empleado tenga los datos requeridos para este país."""
        return {"valid": True, "errors": []}


class TaxCalculatorFactory:
    """Fábrica de calculadoras de impuestos por país."""

    _registry = {}

    @classmethod
    def register(cls, country_code: str, calculator_class):
        """Registra una calculadora para un país."""
        cls._registry[country_code.upper()] = calculator_class

    @classmethod
    def create(cls, country_code: str, tax_rates: dict = None) -> Optional[TaxCalculator]:
        """Crea una instancia de calculadora para el país especificado."""
        country_code = country_code.upper()
        calculator_class = cls._registry.get(country_code)
        if not calculator_class:
            calculator_class = cls._lazy_register(country_code)
        if calculator_class:
            return calculator_class(tax_rates=tax_rates)
        return None

    @classmethod
    def _lazy_register(cls, country_code: str):
        if country_code == "DO":
            from app.countries.do.tax_calculator import DominicanTaxCalculator
            cls._registry["DO"] = DominicanTaxCalculator
            return DominicanTaxCalculator
        if country_code == "MX":
            from app.countries.mx.tax_calculator import MexicanTaxCalculator
            cls._registry["MX"] = MexicanTaxCalculator
            return MexicanTaxCalculator
        return None

    @classmethod
    def get_supported_countries(cls) -> list:
        """Retorna lista de países soportados."""
        return [
            {"code": c, "name": cls._registry[c].country_name}
            for c in cls._registry
        ]



