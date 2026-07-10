import re

REGIMEN_ORDINARY = "ordinary"
REGIMEN_RST_INCOME = "rst_income"
REGIMEN_RST_PURCHASES = "rst_purchases"
REGIMEN_CONSUMER = "consumer"
REGIMEN_EXEMPT = "exempt"

REGIMEN_CHOICES = [
    (REGIMEN_ORDINARY, "Régimen Ordinario (General)"),
    (REGIMEN_RST_INCOME, "RST basado en ingresos"),
    (REGIMEN_RST_PURCHASES, "RST basado en compras"),
    (REGIMEN_CONSUMER, "Consumidor Final"),
    (REGIMEN_EXEMPT, "Exento"),
]

REGIMEN_DEFAULT = REGIMEN_ORDINARY

REGIMEN_LEGACY_MAP = {
    "General": REGIMEN_ORDINARY,
    "RST": REGIMEN_RST_INCOME,
    "Simplificado": REGIMEN_RST_INCOME,
}

REGIMEN_RULES = {
    REGIMEN_ORDINARY: {
        "label": "Régimen Ordinario (General)",
        "allowed_ecf_types": ["E31", "E32", "E33", "E34", "E41", "E43", "E44", "E45", "E46", "E47"],
        "itbis_enabled": True,
        "default_ecf_type": "E31",
        "rst_limit": None,
        "description": "Contabilidad completa, ITBIS 16%/18% según actividad.",
    },
    REGIMEN_RST_INCOME: {
        "label": "RST basado en ingresos",
        "allowed_ecf_types": ["E32", "E33", "E34", "E41", "E43"],
        "itbis_enabled": True,
        "default_ecf_type": "E32",
        "rst_limit": 12060000,
        "description": "La DGII estima ISR por escala de ingresos. Factura con ITBIS.",
    },
    REGIMEN_RST_PURCHASES: {
        "label": "RST basado en compras",
        "allowed_ecf_types": ["E32", "E33", "E34", "E41", "E43"],
        "itbis_enabled": True,
        "default_ecf_type": "E32",
        "rst_limit": 12060000,
        "description": "La DGII estima ventas desde compras. Factura con ITBIS.",
    },
    REGIMEN_CONSUMER: {
        "label": "Consumidor Final",
        "allowed_ecf_types": ["E32"],
        "itbis_enabled": True,
        "default_ecf_type": "E32",
        "rst_limit": None,
        "description": "Factura solo E32 (consumo), sin RNC de cliente.",
    },
    REGIMEN_EXEMPT: {
        "label": "Exento",
        "allowed_ecf_types": ["E32"],
        "itbis_enabled": False,
        "default_ecf_type": "E32",
        "rst_limit": None,
        "description": "Actividades exentas de ITBIS. Factura E32 sin ITBIS.",
    },
}


def clean_rnc(rnc):
    if not rnc:
        return ""
    return re.sub(r'[^0-9]', '', str(rnc))


def validate_rnc(clean_rnc):
    if len(clean_rnc) == 9:
        weights = [7, 9, 8, 6, 5, 4, 3, 2]
        digits = [int(d) for d in clean_rnc[:8]]
        check_digit = int(clean_rnc[8])
        total = sum(d * w for d, w in zip(digits, weights))
        remainder = total % 11
        if remainder <= 1:
            expected = 0 if remainder == 0 else 1
        else:
            expected = 11 - remainder
        if expected != check_digit:
            return {"error": True, "message": "RNC inválido: el dígito verificador no coincide."}
        return {"error": False, "rnc": clean_rnc, "razon_social": "", "actividad": "", "regimen": "", "source": "local"}

    elif len(clean_rnc) == 11:
        weights = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
        digits = [int(d) for d in clean_rnc[:10]]
        check_digit = int(clean_rnc[10])
        products = []
        for d, w in zip(digits, weights):
            prod = d * w
            if prod >= 10:
                products.append(prod // 10 + prod % 10)
            else:
                products.append(prod)
        total = sum(products)
        remainder = total % 10
        expected = 0 if remainder == 0 else 10 - remainder
        if expected != check_digit:
            return {"error": True, "message": "Cédula inválida: el dígito verificador no coincide."}
        return {"error": False, "rnc": clean_rnc, "razon_social": "", "actividad": "", "regimen": "", "source": "local"}

    return {"error": True, "message": "Debe tener 9 dígitos (RNC) u 11 (Cédula)."}
