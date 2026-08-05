"""TSS License Mapping — Homologación de tipos de licencia SPN → TSS.

Los códigos internos de licencias del sistema deben mapearse a los códigos
de la TSS para el archivo de Novedades (NV):
  VC = Vacaciones
  LV = Licencia Voluntaria
  LM = Licencia por Maternidad
  LD = Licencia por Discapacidad
"""

from typing import Optional

DEFAULT_TSS_LICENSE_MAPPING = {
    "vacaciones": "VC",
    "maternidad": "LM",
    "voluntaria": "LV",
    "discapacidad": "LD",
    "enfermedad": "LV",
    "luto": "LV",
    "sindical": "LV",
    "licencia_medica": "LV",
    "permiso_personal": "LV",
    "paternidad": "LV",
    "estudios": "LV",
}

TSS_NOVEDAD_CODES = frozenset({"VC", "LV", "LM", "LD"})


def get_tss_license_mapping(company_profile: Optional[dict] = None) -> dict:
    """Obtiene el mapeo de licencias SPN→TSS para una empresa.

    Prioriza la configuración por empresa almacenada en el perfil de compañía.
    Si no existe, usa el mapeo por defecto hardcodeado.

    Args:
        company_profile: Dict del perfil de la compañía desde Firestore.

    Returns:
        Dict con {spn_license_code: tss_code}.
    """
    custom = (company_profile or {}).get("tss_license_mapping") or {}
    mapping = dict(DEFAULT_TSS_LICENSE_MAPPING)
    mapping.update(custom)
    return mapping


def map_leave_to_tss(spn_type: str, mapping: Optional[dict] = None) -> str:
    """Convierte un tipo de licencia SPN al código TSS correspondiente.

    Args:
        spn_type: Tipo de licencia interno (ej. "maternidad", "enfermedad").
        mapping: Mapeo personalizado. Si es None, usa el default.

    Returns:
        Código TSS de 2 caracteres (VC, LV, LM, LD) o cadena vacía si no mapea.
    """
    if not spn_type:
        return ""
    m = mapping or DEFAULT_TSS_LICENSE_MAPPING
    return m.get(spn_type.strip(), "")


def map_vacation_to_tss() -> str:
    """Las vacaciones siempre mapean a VC."""
    return "VC"
