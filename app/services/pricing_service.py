# app/services/pricing_service.py
"""
PricingService — Cálculo central de precio de venta por monto o markup sobre costo.

Único punto de cálculo de precios para:
    - Formulario de producto (UI).
    - API de productos.
    - Importación masiva de productos.

Semántica:
    - `amount`: el precio de venta se introduce directamente.
    - `markup`: el precio se calcula como `costo × (1 + porcentaje / 100)`.

Reglas:
    - Aritmética decimal exacta (nunca punto flotante para importes monetarios).
    - Redondeo monetario a 2 decimales (ROUND_HALF_UP), coherente con
      `inventory_valuation_service.quantize_value`.
    - Porcentaje entre 0 y un máximo configurable (no se permiten negativos).
    - `price` se mantiene como el precio final absoluto de venta.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

PRICING_MODE_AMOUNT = "amount"
PRICING_MODE_MARKUP = "markup"

_MONEY_QUANT = Decimal("0.01")
_PCT_QUANT = Decimal("0.0001")
MAX_MARKUP_PERCENTAGE = Decimal("1000")


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


def quantize_money(value):
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


class PricingError(ValueError):
    """Excepción lanzada cuando los datos de precio no son válidos."""
    pass


class PricingService:
    """Motor de cálculo de precio de venta."""

    MODE_AMOUNT = PRICING_MODE_AMOUNT
    MODE_MARKUP = PRICING_MODE_MARKUP
    DEFAULT_MODE = PRICING_MODE_AMOUNT

    @classmethod
    def normalize_mode(cls, value) -> str:
        """Normaliza la modalidad de precio a 'amount' o 'markup'.

        Acepta sinónimos frecuentes en plantillas/UI (porcentaje, percentage, %).
        Cualquier valor desconocido o vacío se interpreta como 'amount' para
        mantener compatibilidad con productos existentes.
        """
        if value is None or str(value).strip() == "":
            return cls.DEFAULT_MODE
        v = str(value).strip().lower()
        if v in ("markup", "porcentaje", "porciento", "percentage", "percent", "%"):
            return cls.MODE_MARKUP
        return cls.MODE_AMOUNT

    @staticmethod
    def compute_price(
        cost,
        mode,
        markup_percentage=None,
        explicit_price=None,
    ) -> Decimal:
        """Calcula el precio de venta según la modalidad.

        - `amount`: devuelve `explicit_price` redondeado a 2 decimales.
        - `markup`: devuelve `cost × (1 + markup_percentage / 100)` redondeado.

        Lanza `PricingError` si los datos no son válidos.
        """
        mode = PricingService.normalize_mode(mode)

        if mode == PRICING_MODE_MARKUP:
            pct = _dec(markup_percentage)
            if pct < 0:
                raise PricingError("El porcentaje de incremento no puede ser negativo.")
            if pct > MAX_MARKUP_PERCENTAGE:
                raise PricingError(
                    f"El porcentaje de incremento no puede superar {MAX_MARKUP_PERCENTAGE}%."
                )
            base = _dec(cost)
            if base < 0:
                raise PricingError("El costo no puede ser negativo.")
            return quantize_money(base * (Decimal("1") + pct / Decimal("100")))

        price = _dec(explicit_price)
        if price < 0:
            raise PricingError("El precio de venta no puede ser negativo.")
        return quantize_money(price)

    @classmethod
    def resolve(cls, cost, mode, markup_percentage=None, explicit_price=None):
        """Calcula el precio y devuelve el detalle de la resolución.

        Retorna un dict con la modalidad normalizada, el porcentaje aplicado
        (solo para markup) y el precio resultante.
        """
        mode = cls.normalize_mode(mode)
        pct = _dec(markup_percentage) if mode == PRICING_MODE_MARKUP else None
        price = cls.compute_price(
            cost, mode, markup_percentage=markup_percentage, explicit_price=explicit_price
        )
        return {
            "pricingMode": mode,
            "markupPercentage": float(pct) if pct is not None else None,
            "price": float(price),
        }
