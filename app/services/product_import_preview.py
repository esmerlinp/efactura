# app/services/product_import_preview.py
"""
Previsualización y validación de la importación de productos (sin escritura).

Analiza las filas resueltas de una importación y produce:
    - Acción por fila: new | update | duplicate | error.
    - Errores y advertencias con su columna.
    - Resumen de conteos (nuevos, actualizados, duplicados, errores).

Es el único punto de validación de filas y precio para la importación, de modo
que la previsualización y el procesamiento final usan exactamente las mismas
reglas (compartidas con `app/web/items_import.py` vía `resolve_import_price`).
"""

from decimal import Decimal

from app.services.pricing_service import PricingService, PricingError


def sanitize_float(value, default=0.0):
    """Convierte un valor de importación a float tolerando RD$, $, espacios y coma decimal."""
    if not value:
        return default
    try:
        cleaned = str(value).strip().replace('RD$', '').replace('$', '').replace(' ', '')
        if ',' in cleaned and '.' in cleaned:
            cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            cleaned = cleaned.replace(',', '.')
        return float(cleaned)
    except Exception:
        return default


def resolve_import_price(cost_price, pricing_mode, markup_pct_raw, price_raw):
    """Resuelve el precio de una fila. Retorna ``(price, column, reason)``.

    ``column``/``reason`` son ``None`` cuando la fila es válida.
    """
    pricing_mode = PricingService.normalize_mode(pricing_mode)
    if pricing_mode == PricingService.MODE_MARKUP:
        if cost_price <= 0:
            return None, "costPrice", "Modalidad PORCENTAJE requiere un costo mayor a 0."
        markup_pct = sanitize_float(markup_pct_raw, None)
        if markup_pct is None:
            return None, "markupPercentage", f"Modalidad PORCENTAJE requiere un porcentaje válido (valor actual: '{markup_pct_raw}')."
        try:
            price = float(PricingService.compute_price(
                cost_price, pricing_mode, markup_percentage=markup_pct))
        except PricingError as pe:
            return None, "markupPercentage", f"Porcentaje inválido: {pe}"
        return price, None, None

    price = sanitize_float(price_raw, 0.0)
    if price < 0:
        return None, "price", f"Precio inválido: '{price_raw}'."
    return price, None, None


def build_preview(rows, existing_codes=None, existing_barcodes=None):
    """Construye la previsualización de una importación.

    Parámetros:
        rows: lista de dicts por fila con claves de campo (name, code, barcode,
              costPrice, pricingMode, markupPercentage, price) y ``row`` (número).
        existing_codes: conjunto de códigos ya existentes (para upsert).
        existing_barcodes: conjunto de códigos de barra ya existentes.

    Retorna:
        {"summary": {...}, "rows": [...]}
    """
    existing_codes = existing_codes or set()
    existing_barcodes = existing_barcodes or set()
    seen_codes = set()
    seen_barcodes = set()

    detail = []
    summary = {
        "totalRows": 0,
        "validRows": 0,
        "errorRows": 0,
        "warningRows": 0,
        "newProducts": 0,
        "updatedProducts": 0,
        "duplicateRows": 0,
        "inventoryMovements": 0,
        "totalUnits": 0.0,
        "totalInventoryValue": 0.0,
    }

    for row in rows:
        row_num = row.get("row")
        name = (row.get("name") or "").strip()
        code = (row.get("code") or "").strip()
        code_key = code.lower()
        barcode = (row.get("barcode") or "").strip()
        barcode_key = barcode.lower()

        cost_price = sanitize_float(row.get("costPrice"))
        pricing_mode = PricingService.normalize_mode(row.get("pricingMode"))
        price, err_col, err_reason = resolve_import_price(
            cost_price, pricing_mode,
            (row.get("markupPercentage") or "").strip(),
            row.get("price"),
        )

        initial_qty = sanitize_float(row.get("initialStock"))
        initial_unit_cost = sanitize_float(row.get("initialUnitCost"))
        warehouse = (row.get("warehouseId") or "").strip()

        errors = []
        warnings = []

        if not name:
            errors.append({"column": "name", "reason": "Falta el nombre o descripción del artículo."})
        if err_col:
            errors.append({"column": err_col, "reason": err_reason})

        if initial_qty > 0:
            if not warehouse:
                errors.append({"column": "warehouseId", "reason": "Existencia inicial requiere un almacén."})
            effective_unit_cost = initial_unit_cost if initial_unit_cost > 0 else cost_price
            if effective_unit_cost <= 0:
                warnings.append({"column": "initialUnitCost", "reason": "Existencia inicial sin costo: se valorará a 0."})

        if errors:
            action = "error"
        elif code_key and code_key in seen_codes:
            action = "duplicate"
            warnings.append({"column": "code", "reason": f"Código duplicado dentro del archivo: '{code}'."})
        elif code_key and code_key in existing_codes:
            action = "update"
        else:
            action = "new"

        if code_key:
            seen_codes.add(code_key)
        if barcode_key:
            if barcode_key in seen_barcodes:
                warnings.append({"column": "barcode", "reason": f"Código de barra duplicado: '{barcode}'."})
            seen_barcodes.add(barcode_key)

        summary["totalRows"] += 1
        if action == "error":
            summary["errorRows"] += 1
        elif action == "duplicate":
            summary["duplicateRows"] += 1
        elif action == "update":
            summary["updatedProducts"] += 1
        elif action == "new":
            summary["newProducts"] += 1
        if warnings:
            summary["warningRows"] += 1

        if initial_qty > 0 and action in ("new", "update"):
            summary["inventoryMovements"] += 1
            summary["totalUnits"] += initial_qty
            unit_value = initial_unit_cost if initial_unit_cost > 0 else cost_price
            summary["totalInventoryValue"] += round(initial_qty * unit_value, 2)

        detail.append({
            "row": row_num,
            "code": code,
            "barcode": barcode,
            "name": name,
            "action": action,
            "pricingMode": pricing_mode,
            "price": price,
            "initialStock": initial_qty,
            "warehouseId": warehouse,
            "initialUnitCost": initial_unit_cost,
            "errors": errors,
            "warnings": warnings,
        })

    summary["validRows"] = (
        summary["totalRows"] - summary["errorRows"] - summary["duplicateRows"]
    )

    return {"summary": summary, "rows": detail}
