def get_ecf_type_number_code(ecf_type):
    if "E31" in ecf_type: return "31"
    if "E32" in ecf_type: return "32"
    if "E33" in ecf_type: return "33"
    if "E34" in ecf_type: return "34"
    if "E41" in ecf_type: return "41"
    if "E43" in ecf_type: return "43"
    if "E44" in ecf_type: return "44"
    if "E45" in ecf_type: return "45"
    if "E46" in ecf_type: return "46"
    if "E47" in ecf_type: return "47"
    if "E48" in ecf_type: return "48"
    if "E49" in ecf_type: return "49"
    if "E50" in ecf_type: return "50"
    if "B12" in ecf_type: return "12"
    return "32"

def get_ecf_type_short_code(ecf_type):
    return f"E{get_ecf_type_number_code(ecf_type)}"

def is_ncf_type_rui(ecf_type_or_ncf):
    return "B12" in ecf_type_or_ncf or ecf_type_or_ncf == "12"

# Catálogo DGII — Códigos de Modificación (InformacionReferencia de E33/E34)
DGII_MODIFICATION_REASONS = {
    1: "Devolución",
    2: "Corrección de texto",
    3: "Corrige Montos del NCF Modificado",
    4: "Descuento por volumen",
    5: "Otros",
}

def get_modification_reason_dgii(code, stored_reason=None, ecf_type_value=None):
    """Etiqueta oficial DGII del código de modificación (E33/E34).

    Para el código 3 el texto depende del tipo de comprobante: e-CF → el
    texto usa ``e-NCF Modificado``; NCF tradicional → ``NCF Modificado``.
    Para los demás códigos se prefiere el motivo almacenado y se usa el
    texto DGII como respaldo.
    """
    try:
        c = int(code)
    except (TypeError, ValueError):
        return stored_reason or ""
    if c == 3:
        if ecf_type_value:
            from app.models.fiscal_document_type import by_code
            try:
                is_ecf = by_code(ecf_type_value).code.startswith("E")
            except (KeyError, ValueError, TypeError):
                is_ecf = str(ecf_type_value).strip().upper().startswith("E")
            if is_ecf:
                return "Corrige Montos del e-NCF Modificado"
        return "Corrige Montos del NCF Modificado"
    return stored_reason or DGII_MODIFICATION_REASONS.get(c, "") or ""
