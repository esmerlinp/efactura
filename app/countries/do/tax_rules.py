ITBIS_RATE_GENERAL = 0.18
ITBIS_RATE_REDUCED = 0.16
ITBIS_RATE_CONSTRUCTION = 0.0108

ISR_CORPORATE_RATE = 0.27
ISR_LARGE_TAXPAYER_RATE = 0.30

WITHHOLDING_ISR_RATES = {
    "goods_services": 0.02,
    "professional_fees": 0.10,
    "digital_services_abroad": 0.15,
}

WITHHOLDING_ITBIS_RATES = {
    "corporate_goods": 0.30,
    "legal_services": 0.75,
    "independent_professionals": 1.00,
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
    "rst": {
        "limit": RST_ANNUAL_LIMIT_2026,
        "brackets": RST_TAX_BRACKETS_2026,
    },
}
