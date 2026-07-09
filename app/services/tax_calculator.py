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


class DominicanTaxCalculator(TaxCalculator):
    """Calculadora de impuestos para República Dominicana."""

    country_code = "DO"
    country_name = "República Dominicana"
    currency = "DOP"

    def __init__(self, tax_rates: dict = None):
        from app.services.payroll_service import PayrollService

        self._rates = PayrollService.get_rates(tax_rates or {})

    def get_rates(self) -> dict:
        return dict(self._rates)

    def calculate_employee_taxes(self, income: float, period_type: str = "mensual",
                                  context: dict = None) -> dict:
        context = context or {}
        r = self._rates

        period_factor = 24 if period_type == "quincenal" else 12
        afp_cap = r["afp_salary_cap"] / 2 if period_type == "quincenal" else r["afp_salary_cap"]
        sfs_cap = r["sfs_salary_cap"] / 2 if period_type == "quincenal" else r["sfs_salary_cap"]

        afp_cotizable = min(income, afp_cap)
        sfs_cotizable = min(income, sfs_cap)

        afp_employee = round(afp_cotizable * r["afp_employee_rate"], 2)
        sfs_employee = round(sfs_cotizable * r["sfs_employee_rate"], 2)

        infotep_threshold = r["min_salary"] * r["infotep_threshold_multiplier"]
        infotep_employee = round(income * r["infotep_rate"], 2) if income > infotep_threshold else 0.0

        from app.services.payroll_service import PayrollService
        isr_monthly = PayrollService._calculate_isr_monthly(
            income, afp_employee, sfs_employee,
            education_deduction=context.get("education_deduction", 0),
            period_factor=period_factor,
            tax_rates=self._rates,
        )

        return {
            "afp": afp_employee,
            "sfs": sfs_employee,
            "infotep": infotep_employee,
            "isr": isr_monthly,
            "total": round(afp_employee + sfs_employee + infotep_employee + isr_monthly, 2),
            "breakdown": {
                "afp_rate": r["afp_employee_rate"],
                "sfs_rate": r["sfs_employee_rate"],
                "afp_cap": afp_cap,
                "sfs_cap": sfs_cap,
            },
        }

    def calculate_employer_contributions(self, income: float, period_type: str = "mensual",
                                          context: dict = None) -> dict:
        r = self._rates
        afp_cap = r["afp_salary_cap"] / 2 if period_type == "quincenal" else r["afp_salary_cap"]
        sfs_cap = r["sfs_salary_cap"] / 2 if period_type == "quincenal" else r["sfs_salary_cap"]

        afp_cotizable = min(income, afp_cap)
        sfs_cotizable = min(income, sfs_cap)

        afp_employer = round(afp_cotizable * r["afp_employer_rate"], 2)
        sfs_employer = round(sfs_cotizable * r["sfs_employer_rate"], 2)
        srl_employer = round(sfs_cotizable * r["srl_employer_rate"], 2)
        infotep_employer = round(income * r["infotep_rate"], 2)

        return {
            "afp": afp_employer,
            "sfs": sfs_employer,
            "srl": srl_employer,
            "infotep": infotep_employer,
            "total": round(afp_employer + sfs_employer + srl_employer + infotep_employer, 2),
        }

    @classmethod
    def validate_employee_data(cls, employee: dict) -> dict:
        errors = []
        if not employee.get("cedula") and not employee.get("idNumber"):
            errors.append("Cédula o RNC requerido para RD")
        if not employee.get("tssKey"):
            errors.append("Clave nómina TSS requerida")
        if not employee.get("afpProvider"):
            errors.append("AFP requerida")
        return {"valid": len(errors) == 0, "errors": errors}


class TaxCalculatorFactory:
    """Fábrica de calculadoras de impuestos por país."""

    _registry = {
        "DO": DominicanTaxCalculator,
    }

    @classmethod
    def register(cls, country_code: str, calculator_class):
        """Registra una calculadora para un país."""
        cls._registry[country_code.upper()] = calculator_class

    @classmethod
    def create(cls, country_code: str, tax_rates: dict = None) -> Optional[TaxCalculator]:
        """Crea una instancia de calculadora para el país especificado."""
        country_code = country_code.upper()
        calculator_class = cls._registry.get(country_code)
        if calculator_class:
            return calculator_class(tax_rates=tax_rates)
        return None

    @classmethod
    def get_supported_countries(cls) -> list:
        """Retorna lista de países soportados."""
        return [
            {"code": c, "name": cls._registry[c].country_name}
            for c in cls._registry
        ]
