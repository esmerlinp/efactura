from app.countries.base import BaseCountryProvider
from app.services.tax_calculator import TaxCalculator

_MX_CHART = [
    {"code": "101001", "name": "Caja", "group": "activos", "usage": "banco"},
    {"code": "101002", "name": "Bancos", "group": "activos", "usage": "banco"},
    {"code": "103001", "name": "Clientes", "group": "activos", "usage": "cxc"},
    {"code": "103002", "name": "Deudores Diversos", "group": "activos", "usage": "cxc"},
    {"code": "104001", "name": "Inventarios", "group": "activos", "usage": "inventario"},
    {"code": "106001", "name": "IVA Acreditable", "group": "activos", "usage": "vat_credit"},
    {"code": "106002", "name": "IVA por Acreditar", "group": "activos", "usage": "vat_credit"},
    {"code": "107001", "name": "ISR Retenido a Favor", "group": "activos", "usage": "income_tax_withholding"},
    {"code": "110001", "name": "Equipo de Computo", "group": "activos", "usage": "activo_fijo"},
    {"code": "110002", "name": "Mobiliario y Equipo", "group": "activos", "usage": "activo_fijo"},
    {"code": "110003", "name": "Depreciacion Acumulada", "group": "activos", "usage": "depreciacion_acumulada"},
    {"code": "201001", "name": "Proveedores", "group": "pasivos", "usage": "cxp"},
    {"code": "202001", "name": "Acreedores Diversos", "group": "pasivos", "usage": "cxp"},
    {"code": "203001", "name": "IVA por Pagar", "group": "pasivos", "usage": "vat_payable"},
    {"code": "203002", "name": "IVA Retenido", "group": "pasivos", "usage": "vat_withholding"},
    {"code": "204001", "name": "ISR por Pagar", "group": "pasivos", "usage": "income_tax_payable"},
    {"code": "204002", "name": "ISR Retenido", "group": "pasivos", "usage": "income_tax_withholding"},
    {"code": "205001", "name": "IMSS por Pagar", "group": "pasivos", "usage": "imss_pagar"},
    {"code": "205002", "name": "SAR por Pagar", "group": "pasivos", "usage": "sar_pagar"},
    {"code": "205003", "name": "INFONAVIT por Pagar", "group": "pasivos", "usage": "infonavit_pagar"},
    {"code": "206001", "name": "Prestamos Bancarios CP", "group": "pasivos", "usage": None},
    {"code": "301001", "name": "Capital Social", "group": "patrimonio", "usage": "capital"},
    {"code": "301002", "name": "Resultado del Ejercicio", "group": "patrimonio", "usage": "resultado_ejercicio"},
    {"code": "401001", "name": "Ingresos por Ventas", "group": "ingresos", "usage": "ventas"},
    {"code": "402001", "name": "Devoluciones sobre Ventas", "group": "ingresos", "usage": "devoluciones_ventas"},
    {"code": "501001", "name": "Costo de Ventas", "group": "costos", "usage": "costo_ventas"},
    {"code": "601001", "name": "Gastos Operativos", "group": "gastos", "usage": "gastos"},
    {"code": "602001", "name": "Sueldos y Salarios", "group": "gastos", "usage": "sueldos"},
    {"code": "603001", "name": "Cargas Sociales", "group": "gastos", "usage": "cargas_sociales"},
    {"code": "604001", "name": "Honorarios Profesionales", "group": "gastos", "usage": "gastos"},
]


_MX_TAX_RULES = {
    "country": "MX",
    "vat": {
        "general": 0.16,
        "frontier": 0.08,
        "exempt": 0.0,
    },
    "isc": {},
    "isr_corporate": {
        "general": 0.30,
    },
    "withholding_isr": {
        "professional_fees": 0.1066,
        "lease": 0.10,
        "interest": 0.0023,
        "foreign_resident": 0.25,
    },
    "withholding_vat": {
        "goods_services": 0.1066,
    },
    "ieps": {},
}


_MX_WITHHOLDING_ISR_RATES = {
    "professional_fees": 0.1066,
    "lease": 0.10,
    "interest": 0.0023,
    "foreign_resident": 0.25,
}


_MX_WITHHOLDING_VAT_RATES = {
    "goods_services": 0.1066,
}


_MX_ISR_TABLE = [
    (0.01, 644.21, 0.00, 0.0192),
    (644.22, 5478.36, 12.38, 0.0640),
    (5478.37, 9625.53, 321.26, 0.1088),
    (9625.54, 11191.37, 772.10, 0.1600),
    (11191.38, 13388.74, 1022.01, 0.1792),
    (13388.75, 26973.24, 1415.90, 0.2136),
    (26973.25, 42557.55, 4317.18, 0.2352),
    (42557.56, 54799.19, 7982.94, 0.3000),
    (54799.20, 110040.48, 11655.43, 0.3200),
    (110040.49, 147147.17, 29335.47, 0.3400),
    (147147.18, None, 41951.75, 0.3500),
]


_MX_REGIMEN_RULES = {
    "moral": {
        "label": "Persona Moral",
        "default_ecf_type": "Factura (CFDI)",
        "vat_enabled": True,
        "withholding_required": True,
    },
    "fisica": {
        "label": "Persona Fisica",
        "default_ecf_type": "Factura (CFDI)",
        "vat_enabled": True,
        "withholding_required": True,
    },
}


class MXProvider(BaseCountryProvider):
    country_code = "MX"
    country_name = "Mexico"
    currency = "MXN"
    tax_authority = "SAT"
    tax_authority_full = "Servicio de Administracion Tributaria"
    social_security_name = "IMSS"
    social_security_full = "Instituto Mexicano del Seguro Social"
    labor_ministry = "STPS"

    SUPPORTED_FEATURES = {
        "sat", "electronic_invoicing", "accounting",
        "cfdi", "iva", "isr", "imss", "infonavit",
        "retenciones", "nomina", "sar",
    }

    def get_default_chart(self) -> list:
        return list(_MX_CHART)

    def get_tax_rules(self) -> dict:
        return dict(_MX_TAX_RULES)

    def get_regimen_rules(self) -> dict:
        return dict(_MX_REGIMEN_RULES)

    def get_payroll_rules(self) -> dict:
        return {
            "imss_employee_rate": 0.015,
            "imss_employer_rate": 0.07,
            "sar_rate": 0.02,
            "infonavit_rate": 0.05,
            "imss_salary_cap": 25.0,
            "isr_annual_table": list(_MX_ISR_TABLE),
            "annual_education_deduction": 0,
            "min_salary": 248.93,
            "default_overtime_rate": 2.0,
            "default_working_days_per_month": 30,
            "default_working_hours_per_day": 8,
            "default_infotep_threshold_multiplier": 5,
            "default_account_salaries_payable": "205002",
            "default_account_imss_employee": "205001",
            "default_account_isr_employee": "204002",
            "default_account_imss_employer": "205001",
            "default_account_sar_employer": "205002",
            "default_account_infonavit_employer": "205003",
            "default_account_infotep_employer": "",
            "default_account_infotep_employee": "",
            "default_account_other_deductions": "202001",
            "default_cost_center_accounts": [],
        }

    def get_labor_rules(self) -> dict:
        return {
            "working_days_monthly": 30,
            "working_days_biweekly": 15,
            "working_days_weekly": 7,
            "vacation_proportional_table": [
                (1, 6), (2, 8), (3, 10), (4, 12),
                (5, 14), (9, 16), (10, 18), (14, 20),
                (19, 22), (24, 24), (29, 26), (34, 28),
            ],
        }

    def get_tax_calculator(self, tax_rates: dict = None) -> TaxCalculator:
        from app.countries.mx.tax_calculator import MexicanTaxCalculator
        return MexicanTaxCalculator(tax_rates=tax_rates)

    def get_account_mapping(self) -> dict:
        return {
            "vat_payable": "vat_payable",
            "vat_credit": "vat_credit",
            "vat_withholding": "vat_withholding",
            "income_tax_withholding": "income_tax_withholding",
        }

    def get_tax_labels(self) -> dict:
        return {
            "vat_invoice": "IVA factura",
            "vat_withholding": "IVA retenido",
            "vat_credit": "IVA credito fiscal",
            "vat_credit_note": "IVA devolucion",
            "income_tax_withholding": "ISR retenido",
            "vat": "IVA",
        }

    def supports_feature(self, feature: str) -> bool:
        return feature in self.SUPPORTED_FEATURES
