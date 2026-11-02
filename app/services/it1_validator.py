"""Validaciones IT-1-2020 y consistencia entre secciones."""

from app.fiscal_forms.common import money
from app.fiscal_forms.it1_rules import ANNEX_A_SECTIONS, IT1_SECTIONS
from app.services.it1_calculator import calculate_annex_a, calculate_it1, proportionality_coefficient


def validate_it1(data):
    errors = []
    warnings = []
    annex_values = {int(k): money(v) for k, v in (data.get("annex_a", {}).get("values") or {}).items()}
    form_values = {int(k): money(v) for k, v in (data.get("it1", {}).get("values") or {}).items()}
    for section in ANNEX_A_SECTIONS.values():
        for number in section:
            if annex_values.get(number, 0) < 0:
                errors.append(f"Anexo A, casilla {number}: no puede ser negativa.")
    for section in IT1_SECTIONS.values():
        for number in section:
            if form_values.get(number, 0) < 0:
                errors.append(f"IT-1, casilla {number}: no puede ser negativa.")
    constructor_total = money(data.get("annex_a", {}).get("constructor_total_facturado", 0))
    constructor_subject = money(data.get("annex_a", {}).get("constructor_monto_sujeto", 0))
    commission_total = money(data.get("annex_a", {}).get("commission_total_facturado", 0))
    commission_subject = money(data.get("annex_a", {}).get("commission_monto_sujeto", 0))
    if constructor_subject > constructor_total:
        errors.append("Anexo A: el monto sujeto de constructoras excede el total facturado.")
    if commission_subject > commission_total:
        errors.append("Anexo A: el monto sujeto de comisionistas excede el total facturado.")
    if form_values.get(1, 0) and form_values.get(10, 0) != sum((form_values.get(i, 0) for i in range(11, 16)), money(0)):
        errors.append("IT-1: las operaciones gravadas no concilian con las casillas 11 a 15.")
    if data.get("annex_a", {}).get("values", {}).get("53"):
        coefficient = proportionality_coefficient(form_values.get(1, 0), form_values.get(2, 0), form_values.get(5, 0), form_values.get(10, 0))
        if coefficient < 0 or coefficient > 100:
            errors.append("El coeficiente de proporcionalidad debe estar entre 0% y 100%.")
    if data.get("rules_version") != "2020":
        warnings.append("La versión fiscal no corresponde al catálogo histórico IT-1-2020.")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "annex_calculated": calculate_annex_a(data.get("annex_a", {})), "it1_calculated": calculate_it1(data.get("it1", {}))}
