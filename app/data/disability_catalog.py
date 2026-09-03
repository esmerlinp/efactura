"""Catálogo oficial de discapacidades SIRLA (Ministerio de Trabajo RD).

Campo "Discapacidad" de los archivos SIRLA (DGT-3/DGT-4/DGT-5): AN de 50
posiciones, permite múltiples códigos separados por coma. "Ninguna" (4714)
es el valor por defecto cuando el empleado no tiene discapacidad.

Fuente: catálogo oficial SIRLA.
"""

SIRLA_DISABILITIES = [
    {"code": "285", "name": "Discapacidad Auditiva"},
    {"code": "289", "name": "Discapacidad Visual"},
    {"code": "1493", "name": "Discapacidad Intelectual"},
    {"code": "4062", "name": "Discapacidad del Habla"},
    {"code": "4063", "name": "Discapacidad Física"},
    {"code": "4714", "name": "Ninguna"},
    {"code": "4742", "name": "Discapacidad Psicosocial"},
    {"code": "4743", "name": "Discapacidad Psicomotora"},
]

DEFAULT_DISABILITY_CODE = "4714"

_DISABILITY_BY_CODE = {d["code"]: d["name"] for d in SIRLA_DISABILITIES}


def is_valid_disability_code(code) -> bool:
    """True si el código es una discapacidad oficial SIRLA."""
    return str(code or "").strip() in _DISABILITY_BY_CODE


def get_disability_name(code) -> str:
    """Devuelve el nombre de la discapacidad, o '' si no existe."""
    return _DISABILITY_BY_CODE.get(str(code or "").strip(), "")


def normalize_disability(value) -> str:
    """Normaliza el valor de discapacidad a una cadena de códigos válidos.

    Acepta una cadena separada por comas o una lista. Descarta códigos
    inválidos y duplicados. Si el resultado queda vacío (o el valor es
    None/''), devuelve "4714" (Ninguna). Si hay discapacidades reales,
    excluye automáticamente "4714".
    """
    if value is None:
        return DEFAULT_DISABILITY_CODE

    if isinstance(value, (list, tuple, set)):
        parts = [str(v).strip() for v in value]
    else:
        parts = [p.strip() for p in str(value).split(",")]

    codes = []
    for p in parts:
        if not p:
            continue
        if p == DEFAULT_DISABILITY_CODE:
            continue  # "Ninguna" no coexiste con discapacidades reales
        if is_valid_disability_code(p) and p not in codes:
            codes.append(p)

    if not codes:
        return DEFAULT_DISABILITY_CODE

    return ",".join(codes)
