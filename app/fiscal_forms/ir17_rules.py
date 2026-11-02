"""Catálogo oficial IR-17 versión 2026.

La plantilla ``Docs/IR-17-2026.xlsx`` es la fuente de verificación de este
catálogo. Las declaraciones guardan la versión usada para no cambiar con
futuras reformas.
"""

from decimal import Decimal

IR17_RULES_VERSION = "2026"

IR17_LINES = (
    (1, "ALQUILERES", "0.15", "Ley 11-92"),
    (2, "HONORARIOS POR SERVICIOS INDEPENDIENTES", "0.15", "Ley 11-92"),
    (3, "PREMIOS (Ley 253-12)", "0.25", "Ley 253-12"),
    (4, "TRANSFERENCIA DE TÍTULO Y PROPIEDADES", "0.02", "Ley 11-92"),
    (5, "DIVIDENDOS (Ley 253-12)", "0.10", "Ley 253-12"),
    (6, "INTERESES A PERSONAS JURÍDICAS O ENTIDADES NO RESIDENTES (Ley 253-12)", "0.10", "Ley 253-12"),
    (7, "INTERESES A PERSONAS JURÍDICAS O ENTIDADES NO RESIDENTES (Ley 57-2007)", "0.05", "Ley 57-2007"),
    (8, "INTERESES A PERSONAS FÍSICAS NO RESIDENTES (Ley 253-12)", "0.10", "Ley 253-12"),
    (9, "INTERESES A PERSONAS FÍSICAS NO RESIDENTES (Leyes 57-2007 y 253-12)", "0.05", "Leyes 57-2007 y 253-12"),
    (10, "REMESAS AL EXTERIOR (Ley 253-12)", "0.27", "Ley 253-12"),
    (11, "INTERESES PAGADOS POR ENTIDADES NO FINANCIERAS A PERSONAS FÍSICAS RESIDENTES", "0.10", "Ley 11-92"),
    (12, "PAGOS A PROVEEDORES DEL ESTADO (Ley 253-12)", "0.05", "Ley 253-12"),
    (13, "JUEGOS TELEFÓNICOS (Norma 08-2011)", "0.05", "Norma 08-2011"),
    (14, "GANANCIA DE CAPITAL (Norma 07-2011)", "0.01", "Norma 07-2011"),
    (15, "JUEGOS VÍA INTERNET (Ley 139-11, Art. 7)", "0.10", "Ley 139-11"),
    (16, "OTRAS RENTAS (Ley 11-92, Art. 309 Lit. f modificado por Ley 30-26)", "0.15", "Ley 30-26"),
    (17, "OTRAS RENTAS (Decreto 139-98, Art. 70 Lit. a y b)", "0.03", "Decreto 139-98"),
    (18, "OTRAS RETENCIONES (Norma 07-2007 modificado por Ley 30-26)", "0.03", "Ley 30-26"),
    (19, "INTERESES PAGADOS POR ENTIDADES FINANCIERAS A PERSONAS JURÍDICAS RESIDENTES (Norma 13-2011)", "0.01", "Norma 13-2011"),
    (20, "INTERESES PAGADOS POR ENTIDADES FINANCIERAS A PERSONAS FÍSICAS RESIDENTES (Ley 253-12)", "0.10", "Ley 253-12"),
    (21, "ADQUISICIÓN DE BIENES DE PERSONAS FÍSICAS DEL SUBSECTOR DE GANADERÍA DE CARNE BOVINA (Norma 04-25)", "0.01", "Norma 04-25"),
    (22, "REGALÍAS O DERECHOS PAGADOS A NO RESIDENTES (Art. 305-1, Ley 30-26)", "0.15", "Ley 30-26"),
    (23, "LICENCIAS DE SOFTWARE, PUBLICIDAD EN LÍNEA Y ALMACENAMIENTO DE DATOS A NO RESIDENTES (Art. 305-2, Ley 30-26)", "0.15", "Ley 30-26"),
    (24, "REMESAS AL EXTERIOR (Mayores a 1,000 millones - Ley 30-26)", "0.30", "Ley 30-26"),
)

IR17_LINES_BY_NUMBER = {
    number: {
        "number": number,
        "concept": concept,
        "rate": Decimal(rate),
        "legal_reference": legal_reference,
    }
    for number, concept, rate, legal_reference in IR17_LINES
}


def default_line_items():
    return [
        {
            **line,
            "base": "0.00",
            "tax": "0.00",
            "source": "manual",
        }
        for line in IR17_LINES_BY_NUMBER.values()
    ]
