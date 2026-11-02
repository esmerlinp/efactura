"""Catálogo histórico IT-1-2020 basado en el instructivo DGII entregado.

No debe usarse para períodos posteriores hasta que DGII confirme una versión
vigente. La plantilla ``docs/IT-1-2020.xls`` se conserva sin modificaciones.
"""

from app.fiscal_forms.common import FiscalRulesVersion

IT1_RULES_VERSION = FiscalRulesVersion(
    form="IT-1",
    version="2020",
    status="historical",
    source="docs/IT-1-2020.xls + InstructivoLlenado IT-1 2020",
    effective_from="2020-01",
    effective_to="2020-12",
)

ANNEX_A_SECTIONS = {
    "ncf": tuple(range(1, 12)),
    "sales_methods": tuple(range(12, 20)),
    "income_types": tuple(range(20, 27)),
    "withholding_payments": tuple(range(27, 34)),
    "constructors": tuple(range(34, 39)),
    "commission_agents": tuple(range(39, 43)),
    "informative": (43, 44),
    "itbis_paid": tuple(range(45, 57)),
}

IT1_SECTIONS = {
    "operations": tuple(range(1, 16)),
    "settlement": tuple(range(16, 35)),
    "penalties": tuple(range(35, 38)),
    "total": (38,),
    "withheld_itbis": tuple(range(39, 61)),
    "withholding_settlement": tuple(range(61, 64)),
}

ANNEX_A_FORMULAS = {
    11: "1 + 2 + 3 - 4 + 5 + 6 + 7 + 8 + 9 - 10",
    19: "12 + 13 + 14 + 15 + 16 + 17 + 18",
    26: "20 + 21 + 22 + 23 + 24 + 25",
    33: "27 + 28 + 29 + 30 + 31 + 32",
    37: "total_facturado_34 + total_facturado_35; monto_34 + monto_35 + monto_36",
    38: "total_facturado_37 - monto_37",
    41: "total_facturado_39 + total_facturado_40; monto_39 + monto_40",
    42: "total_facturado_41 - monto_41",
    48: "45 + 46 + 47",
    52: "49 + 50 + 51",
    55: "53 * 54 / 100",
    56: "52 + 55",
}

IT1_FORMULAS = {
    9: "2 + 3 + 4 + 5 + 6 + 7 + 8",
    10: "1 - 9",
    16: "11 * 0.18",
    17: "12 * 0.16",
    18: "13 * 0.09",
    19: "14 * 0.08",
    20: "15 * 0.18",
    21: "16 + 17 + 18 + 19 + 20",
    25: "22 + 23 + 24",
    26: "max(21 - 25, 0)",
    27: "max(25 - 21, 0)",
    28: "saldos_compensables_autorizados",
    29: "saldo_a_favor_anterior",
    30: "anexo_a.casilla_33",
    31: "otros_pagos_computables_a_cuenta",
    32: "compensaciones_y_reembolsos_autorizados",
    33: "positive(26 - 28 - 29 - 30 - 31 - 32)",
    34: "positive(28 + 29 + 30 + 31 + 32 - 26) or (27 + 28 + 29 + 30 + 31 + 32)",
    38: "33 + 35 + 36 + 37",
    39: "services_withholding_section_total",
    40: "services_subject_to_withholding_individuals",
    41: "services_subject_to_withholding_nonprofits",
    42: "40 + 41",
    43: "services_subject_to_withholding_companies",
    44: "rst_18_base",
    45: "rst_16_base",
    46: "44 + 45",
    47: "purchase_receipts_18_base",
    48: "purchase_receipts_16_base",
    49: "47 + 48",
    50: "41 * 0.18",
    51: "42 * 0.18",
    52: "43 * 0.18 * 0.30",
    55: "53 + 54",
    58: "56 + 57",
    59: "disabled_until_official_perception_rule",
    60: "50 + 51 + 52 + 55 + 58 + 59",
    61: "withholding_payments_account",
    62: "max(60 - 61, 0)",
    63: "max(61 - 60, 0)",
}

PROPORTIONALITY_FORMULA = "((IT1.casilla_2 + IT1.casilla_5 + IT1.casilla_10) / IT1.casilla_1) * 100"
PROPORTIONALITY_ADMITTED_FORMULA = "AnexoA.casilla_53 * coeficiente / 100"


def validate_catalog_numbers():
    annex = sorted(number for section in ANNEX_A_SECTIONS.values() for number in section)
    form = sorted(number for section in IT1_SECTIONS.values() for number in section)
    return {
        "annex_a_count": len(set(annex)),
        "annex_a_numbers": tuple(sorted(set(annex))),
        "it1_count": len(set(form)),
        "it1_numbers": tuple(sorted(set(form))),
    }
