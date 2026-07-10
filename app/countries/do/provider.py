from app.countries.base import BaseCountryProvider
from app.services.tax_calculator import TaxCalculator


class DOProvider(BaseCountryProvider):
    country_code = "DO"
    country_name = "República Dominicana"
    currency = "DOP"
    tax_authority = "DGII"
    tax_authority_full = "Dirección General de Impuestos Internos"
    social_security_name = "TSS"
    social_security_full = "Tesorería de la Seguridad Social"
    labor_ministry = "Ministerio de Trabajo"

    SUPPORTED_FEATURES = {
        "dgii", "electronic_invoicing", "payroll", "accounting",
        "ncf", "ecf", "itbis", "isr", "tss", "labor_liquidation",
        "multi_moneda", "retenciones", "reportes_dgii",
    }

    def get_default_chart(self) -> list:
        from app.countries.do.chart_of_accounts import get_default_chart
        return get_default_chart()

    def get_tax_rules(self) -> dict:
        from app.countries.do.tax_rules import DEFAULT_TAX_RULES
        rules = dict(DEFAULT_TAX_RULES)
        rules.setdefault("vat", rules.pop("itbis", {}))
        rules.setdefault("withholding_vat", rules.pop("withholding_itbis", {}))
        return rules

    def get_regimen_rules(self) -> dict:
        from app.countries.do.dgii_client import (
            REGIMEN_RULES, REGIMEN_DEFAULT, REGIMEN_LEGACY_MAP,
            REGIMEN_ORDINARY, REGIMEN_RST_INCOME, REGIMEN_RST_PURCHASES,
        )
        return {
            "default": REGIMEN_DEFAULT,
            "ordinary_key": REGIMEN_ORDINARY,
            "legacy_map": REGIMEN_LEGACY_MAP,
            "rst_income": REGIMEN_RST_INCOME,
            "rst_purchases": REGIMEN_RST_PURCHASES,
            "regimes": REGIMEN_RULES,
        }

    def get_payroll_rules(self) -> dict:
        from app.countries.do.payroll_rules import (
            AFP_EMPLOYEE_RATE, AFP_EMPLOYER_RATE,
            SFS_EMPLOYEE_RATE, SFS_EMPLOYER_RATE,
            SRL_EMPLOYER_RATE, INFOTEP_RATE,
            AFP_SALARY_CAP, SFS_SALARY_CAP,
            ISR_ANNUAL_TABLE, ANNUAL_EDUCATION_DEDUCTION,
            MIN_SALARY, DEFAULT_OVERTIME_RATE,
            DEFAULT_WORKING_DAYS_PER_MONTH, DEFAULT_WORKING_HOURS_PER_DAY,
            DEFAULT_INFOTEP_THRESHOLD_MULTIPLIER,
            DEFAULT_ACCOUNT_SALARIES_PAYABLE,
            DEFAULT_ACCOUNT_AFP_EMPLOYEE, DEFAULT_ACCOUNT_SFS_EMPLOYEE,
            DEFAULT_ACCOUNT_ISR_EMPLOYEE,
            DEFAULT_ACCOUNT_AFP_EMPLOYER, DEFAULT_ACCOUNT_SFS_EMPLOYER,
            DEFAULT_ACCOUNT_SRL_EMPLOYER,
            DEFAULT_ACCOUNT_INFOTEP_EMPLOYER, DEFAULT_ACCOUNT_INFOTEP_EMPLOYEE,
            DEFAULT_ACCOUNT_OTHER_DEDUCTIONS,
            DEFAULT_COST_CENTER_ACCOUNTS,
        )
        return {
            "afp_employee_rate": AFP_EMPLOYEE_RATE,
            "afp_employer_rate": AFP_EMPLOYER_RATE,
            "sfs_employee_rate": SFS_EMPLOYEE_RATE,
            "sfs_employer_rate": SFS_EMPLOYER_RATE,
            "srl_employer_rate": SRL_EMPLOYER_RATE,
            "infotep_rate": INFOTEP_RATE,
            "afp_salary_cap": AFP_SALARY_CAP,
            "sfs_salary_cap": SFS_SALARY_CAP,
            "isr_annual_table": ISR_ANNUAL_TABLE,
            "annual_education_deduction": ANNUAL_EDUCATION_DEDUCTION,
            "min_salary": MIN_SALARY,
            "default_overtime_rate": DEFAULT_OVERTIME_RATE,
            "default_working_days_per_month": DEFAULT_WORKING_DAYS_PER_MONTH,
            "default_working_hours_per_day": DEFAULT_WORKING_HOURS_PER_DAY,
            "default_infotep_threshold_multiplier": DEFAULT_INFOTEP_THRESHOLD_MULTIPLIER,
            "default_account_salaries_payable": DEFAULT_ACCOUNT_SALARIES_PAYABLE,
            "default_account_afp_employee": DEFAULT_ACCOUNT_AFP_EMPLOYEE,
            "default_account_sfs_employee": DEFAULT_ACCOUNT_SFS_EMPLOYEE,
            "default_account_isr_employee": DEFAULT_ACCOUNT_ISR_EMPLOYEE,
            "default_account_afp_employer": DEFAULT_ACCOUNT_AFP_EMPLOYER,
            "default_account_sfs_employer": DEFAULT_ACCOUNT_SFS_EMPLOYER,
            "default_account_srl_employer": DEFAULT_ACCOUNT_SRL_EMPLOYER,
            "default_account_infotep_employer": DEFAULT_ACCOUNT_INFOTEP_EMPLOYER,
            "default_account_infotep_employee": DEFAULT_ACCOUNT_INFOTEP_EMPLOYEE,
            "default_account_other_deductions": DEFAULT_ACCOUNT_OTHER_DEDUCTIONS,
            "default_cost_center_accounts": DEFAULT_COST_CENTER_ACCOUNTS,
        }

    def get_labor_rules(self) -> dict:
        from app.countries.do.labor_rules import (
            DIAS_LABORABLES_MENSUAL,
            DIAS_LABORABLES_QUINCENAL,
            DIAS_LABORABLES_SEMANAL,
            TABLA_VACACIONES_PROPORCIONAL,
        )
        return {
            "working_days_monthly": DIAS_LABORABLES_MENSUAL,
            "working_days_biweekly": DIAS_LABORABLES_QUINCENAL,
            "working_days_weekly": DIAS_LABORABLES_SEMANAL,
            "vacation_proportional_table": TABLA_VACACIONES_PROPORCIONAL,
        }

    def get_tax_calculator(self, tax_rates: dict = None) -> TaxCalculator:
        from app.countries.do.tax_calculator import DominicanTaxCalculator
        return DominicanTaxCalculator(tax_rates=tax_rates)

    def get_account_mapping(self) -> dict:
        return {
            "vat_payable": "itbis_pagar",
            "vat_credit": "itbis_credito",
            "vat_withholding": "itbis_retenido",
            "income_tax_withholding": "isr_retenido",
        }

    def get_tax_labels(self) -> dict:
        return {
            "vat_invoice": "ITBIS factura",
            "vat_withholding": "ITBIS retenido",
            "vat_credit": "ITBIS crédito fiscal",
            "vat_credit_note": "ITBIS devolución",
            "income_tax_withholding": "ISR retenido",
            "vat": "ITBIS",
        }

    def supports_feature(self, feature: str) -> bool:
        return feature in self.SUPPORTED_FEATURES
