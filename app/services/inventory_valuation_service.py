# app/services/inventory_valuation_service.py
"""
InventoryValuationService — Motor de Valoración de Inventario.

Implementa el método de **costo promedio ponderado móvil** con aritmética
decimal exacta (nunca punto flotante para importes monetarios) y mantiene la
compatibilidad con el costeo FIFO legacy.

Fuente de verdad de la valoración (por producto + almacén):
    `inventory_stock/{itemId}_{warehouseId}` → { quantity, totalValue, unitCost, lastPurchaseCost }

Reglas:
- Costo de referencia (`items.costPrice`): valor por defecto al crear una entrada; NO se modifica.
- Último costo de compra: `unitCost` efectivo de la última ENTRADA/COMPRA confirmada.
- Costo promedio ponderado móvil: `totalValue / quantity` por almacén.

Fórmula (entrada):
    nuevoPromedio = (valorActual + valorNuevaEntrada) / (existenciaActual + cantidadRecibida)

Salida:
    COGS = costoPromedioVigente × cantidad; el promedio NO cambia.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# Precisión contable: cantidades y costo unitario a 4 decimales, totales a 2.
_QTY_QUANT = Decimal("0.0001")
_VALUE_QUANT = Decimal("0.01")
_UNIT_COST_QUANT = Decimal("0.0001")

METHOD_FIFO = "fifo"
METHOD_PROMEDIO = "promedio"
METHOD_ESTANDAR = "estandar"


def _dec(value, default="0"):
    """Convierte cualquier valor a Decimal de forma segura."""
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _qty(value):
    return _dec(value)


def quantize_unit(value):
    return value.quantize(_UNIT_COST_QUANT, rounding=ROUND_HALF_UP)


def quantize_value(value):
    return value.quantize(_VALUE_QUANT, rounding=ROUND_HALF_UP)


class InventoryValuationService:
    """Motor de cálculo del costo promedio ponderado móvil."""

    METHOD_FIFO = METHOD_FIFO
    METHOD_PROMEDIO = METHOD_PROMEDIO
    METHOD_ESTANDAR = METHOD_ESTANDAR

    @staticmethod
    def resolve_method(item_dict=None, company_method=None, tx_override=None, default=METHOD_FIFO):
        """Resuelve el método de valoración aplicable.

        Prioridad:
        1. `tx_override` (override explícito de la transacción).
        2. `item_dict.valuationMethod` (por producto).
        3. `company_method` (configuración de la empresa).
        4. `default` (FIFO legacy por compatibilidad).
        """
        for candidate in (tx_override, item_dict.get("valuationMethod") if item_dict else None, company_method):
            if candidate:
                m = str(candidate).strip().lower()
                if m in (METHOD_FIFO, METHOD_PROMEDIO, METHOD_ESTANDAR):
                    return m
        return default

    @staticmethod
    def entry_line_value(unit_cost, qty, discount_amount=0.0, additional_costs=0.0,
                         non_recoverable_tax=0.0):
        """Valor de adquisición de una línea (base para la valoración de la entrada).

        = (costoUnitario × cantidad) − descuentoComercial + costosAdicionales + ITBIS_noRecuperable
        El ITBIS recuperable NO forma parte del costo (se excluye por diseño).

        Se retorna con precisión completa (Decimal) para no perder decimales al
        derivar el costo unitario efectivo; el llamador cuantiza el total a 2 dp.
        """
        gross = _qty(unit_cost) * _qty(qty)
        return gross - _dec(discount_amount) + _dec(additional_costs) + _dec(non_recoverable_tax)

    @staticmethod
    def effective_unit_cost(line_value, qty):
        """Costo unitario efectivo de una línea (valor de línea / cantidad)."""
        qt = _qty(qty)
        if qt <= 0:
            return Decimal("0")
        return quantize_unit(_dec(line_value) / qt)

    @staticmethod
    def moving_average_after_entry(current_qty, current_value, entry_qty, entry_value):
        """Aplica la fórmula del promedio móvil a una entrada.

        Retorna dict con {quantity, totalValue, unitCost} ya cuantizados.
        """
        cq = _qty(current_qty)
        cv = _dec(current_value)
        eq = _qty(entry_qty)
        ev = _dec(entry_value)

        new_qty = cq + eq
        new_value = cv + ev
        new_avg = (new_value / new_qty) if new_qty > 0 else Decimal("0")

        return {
            "quantity": new_qty,
            "totalValue": quantize_value(new_value),
            "unitCost": quantize_unit(new_avg),
        }

    @staticmethod
    def exit_valuation(current_qty, current_value, exit_qty):
        """Calcula COGS y nuevo estado de valoración para una salida.

        COGS = promedioVigente × cantidad. El promedio NO cambia en una salida.
        """
        cq = _qty(current_qty)
        cv = _dec(current_value)
        eq = _qty(exit_qty)

        if eq <= 0 or cq <= 0:
            return {
                "quantity": cq,
                "totalValue": quantize_value(cv),
                "cogs": Decimal("0"),
                "unitCost": quantize_unit(cv / cq) if cq > 0 else Decimal("0"),
            }

        avg_full = cv / cq
        cogs = quantize_value(avg_full * eq)
        new_value = cv - cogs
        if new_value < 0:
            new_value = Decimal("0")

        return {
            "quantity": cq - eq,
            "totalValue": quantize_value(new_value),
            "cogs": cogs,
            "unitCost": quantize_unit(avg_full),
        }

    @staticmethod
    def get_company_valuation_method(company_id, sandbox=True, owner_uid=""):
        """Lee la política de valoración de la empresa (best-effort, sin excepciones).

        Configuración esperada: `config/inventory_settings` → { valuationMethod }.
        Retorna None si no está configurada.
        """
        try:
            from app.services.db_service import db_firestore, firebase_initialized, _company_coll
            if not firebase_initialized or db_firestore is None:
                return None
            doc = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name="config") \
                .document("inventory_settings").get()
            if getattr(doc, "exists", False):
                data = doc.to_dict() or {}
                m = data.get("valuationMethod")
                if m:
                    return str(m).strip().lower()
        except Exception:
            pass
        return None
