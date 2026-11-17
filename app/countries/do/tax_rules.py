ITBIS_RATE_GENERAL = 0.18
ITBIS_RATE_REDUCED = 0.16
ITBIS_RATE_CONSTRUCTION = 0.0108

ISR_CORPORATE_RATE = 0.27
ISR_LARGE_TAXPAYER_RATE = 0.27

WITHHOLDING_ISR_RATES = {
    "goods_services": 0.02,
    "professional_fees": 0.15,
    "digital_services_abroad": 0.15,
    "payments_abroad": 0.27,
    "royalties": 0.15,
}

WITHHOLDING_ITBIS_RATES = {
    "corporate_goods": 0.30,
    "legal_services": 0.75,
    "independent_professionals": 1.00,
}

# Categoría de retención del proveedor → (clave ISR, clave ITBIS).
# Solo conecta categorías YA definidas en los diccionarios anteriores.
# None significa "no aplica" para ese impuesto.
WITHHOLDING_CATEGORY_MAP = {
    "goods_services": {"isr": "goods_services", "itbis": "corporate_goods"},
    "professional_fees": {"isr": "professional_fees", "itbis": "independent_professionals"},
    "legal_services": {"isr": None, "itbis": "legal_services"},
    "digital_services_abroad": {"isr": "digital_services_abroad", "itbis": None},
    "payments_abroad": {"isr": "payments_abroad", "itbis": None},
    "royalties": {"isr": "royalties", "itbis": None},
}

# Línea IR-17 correspondiente a cada regla de retención ISR (solo confirmadas en ir17_rules).
ISR_RULE_TO_IR17_LINE = {
    "professional_fees": 2,
    "digital_services_abroad": 23,
    "payments_abroad": 10,
    "royalties": 22,
}

RST_TAX_BRACKETS_2026 = [
    (416220.0, 0.00, 0.0),
    (624329.0, 0.15, 0.0),
    (867123.0, 0.20, 31216.35),
    (float("inf"), 0.25, 79775.15),
]

RST_ANNUAL_LIMIT_2026 = 12068181.09


def calc_rst_isr(annual_taxable_income):
    prev_limit = 0.0
    for limit, rate, base_tax in RST_TAX_BRACKETS_2026:
        if annual_taxable_income <= limit:
            return base_tax + (annual_taxable_income - prev_limit) * rate if base_tax is not None else annual_taxable_income * rate
        prev_limit = limit
    return annual_taxable_income * 0.25


DEFAULT_TAX_RULES = {
    "country": "RD",
    "itbis": {
        "general": ITBIS_RATE_GENERAL,
        "reduced": ITBIS_RATE_REDUCED,
        "construction": ITBIS_RATE_CONSTRUCTION,
    },
    "isc": {
        "codigo_001_propina_legal": 0.10,
        "codigo_002_cdt": 0.02,
        "codigo_003_isc_seguros": 0.16,
        "codigo_004_telecomunicaciones": 0.10,
        "codigo_005_primera_placa": 0.17,
    },
    "isr_corporate": {
        "general": ISR_CORPORATE_RATE,
        "large_taxpayer": ISR_LARGE_TAXPAYER_RATE,
    },
    "withholding_isr": WITHHOLDING_ISR_RATES,
    "withholding_itbis": WITHHOLDING_ITBIS_RATES,
    "withholding_category_map": WITHHOLDING_CATEGORY_MAP,
    "isr_rule_to_ir17_line": ISR_RULE_TO_IR17_LINE,
    "rst": {
        "limit": RST_ANNUAL_LIMIT_2026,
        "brackets": RST_TAX_BRACKETS_2026,
    },
}
