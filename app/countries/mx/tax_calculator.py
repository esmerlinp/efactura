from app.services.tax_calculator import TaxCalculator


class MexicanTaxCalculator(TaxCalculator):
    country_code = "MX"
    country_name = "Mexico"
    currency = "MXN"

    def __init__(self, tax_rates: dict = None):
        from app.countries.mx.provider import MXProvider
        provider = MXProvider()
        self._rates = provider.get_payroll_rules()
        if tax_rates:
            self._rates.update(tax_rates)

    def get_rates(self) -> dict:
        return dict(self._rates)

    def calculate_employee_taxes(self, income: float, period_type: str = "mensual",
                                  context: dict = None) -> dict:
        context = context or {}
        r = self._rates

        period_factor = 24 if period_type == "quincenal" else 12
        imss_cap = r["imss_salary_cap"] / 2 if period_type == "quincenal" else r["imss_salary_cap"]

        imss_cotizable = min(income, imss_cap)
        imss_employee = round(imss_cotizable * r["imss_employee_rate"], 2)

        isr_monthly = self._calculate_isr(income, period_factor)

        return {
            "imss": imss_employee,
            "isr": isr_monthly,
            "total": round(imss_employee + isr_monthly, 2),
            "breakdown": {
                "imss_rate": r["imss_employee_rate"],
                "imss_cap": imss_cap,
            },
        }

    def _calculate_isr(self, income: float, period_factor: int) -> float:
        annualized = income * period_factor
        table = self._rates.get("isr_annual_table", [])

        for bracket in table:
            lower, upper, fixed, rate = bracket
            if upper is None or annualized <= upper:
                return round(((annualized - lower) * rate + fixed) / period_factor, 2)

        return round(annualized * 0.35 / period_factor, 2)

    def calculate_employer_contributions(self, income: float, period_type: str = "mensual",
                                          context: dict = None) -> dict:
        r = self._rates
        imss_cap = r["imss_salary_cap"] / 2 if period_type == "quincenal" else r["imss_salary_cap"]

        imss_cotizable = min(income, imss_cap)
        imss_employer = round(imss_cotizable * r["imss_employer_rate"], 2)
        sar_employer = round(imss_cotizable * r["sar_rate"], 2)
        infonavit_employer = round(imss_cotizable * r["infonavit_rate"], 2)

        return {
            "imss": imss_employer,
            "sar": sar_employer,
            "infonavit": infonavit_employer,
            "total": round(imss_employer + sar_employer + infonavit_employer, 2),
        }

    @classmethod
    def validate_employee_data(cls, employee: dict) -> dict:
        errors = []
        if not employee.get("rfc"):
            errors.append("RFC requerido para MX")
        if not employee.get("nss"):
            errors.append("NSS (Numero de Seguro Social) requerido")
        if not employee.get("curp"):
            errors.append("CURP requerida")
        return {"valid": len(errors) == 0, "errors": errors}
