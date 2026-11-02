"""Validaciones de integridad del IR-17."""

import re
from decimal import Decimal, InvalidOperation

from app.fiscal_forms.ir17_rules import IR17_LINES_BY_NUMBER
from app.services.ir17_calculator import calculate_ir17


def validate_ir17(data, require_general=True):
    errors = []
    warnings = []
    period = str(data.get("period", ""))
    if not re.fullmatch(r"\d{6}", period):
        errors.append("El período debe tener formato AAAAMM.")
    elif not 1 <= int(period[4:]) <= 12:
        errors.append("El mes del período no es válido.")
    if require_general and not str(data.get("rnc", "")).strip():
        errors.append("El RNC o cédula es obligatorio.")
    for item in data.get("line_items", []):
        number = int(item.get("number", 0))
        if number not in IR17_LINES_BY_NUMBER:
            errors.append(f"Casilla de retención no reconocida: {number}.")
            continue
        for field in ("base",):
            try:
                if Decimal(str(item.get(field, "0"))) < 0:
                    errors.append(f"La base de la casilla {number} no puede ser negativa.")
            except (InvalidOperation, ValueError):
                errors.append(f"La base de la casilla {number} debe ser numérica.")
    calculated = calculate_ir17(data)
    supplied = data.get("totals", {}) or {}
    if supplied and str(supplied.get("total_payable", calculated["total_payable"])) != calculated["total_payable"]:
        warnings.append("Los totales enviados fueron recalculados por VykOne.")
    if data.get("source_warnings"):
        warnings.extend(data["source_warnings"])
    return {"valid": not errors, "errors": errors, "warnings": warnings, "calculated": calculated}
