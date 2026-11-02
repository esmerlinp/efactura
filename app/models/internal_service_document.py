"""Modelo y reglas de valor para documentos internos de promociones."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


MONEY_QUANTUM = Decimal("0.01")
PROMOTION_TYPES = {
    "servicio_gratuito": "Servicio gratuito",
    "descuento_100": "Descuento promocional del 100 %",
    "periodo_prueba": "Período de prueba",
    "bonificacion": "Bonificación comercial",
    "cortesia": "Cortesía",
}
PERSISTED_STATES = {"active", "voided"}


def money(value: Any) -> Decimal:
    return Decimal(str(value or "0")).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def cents(value: Decimal) -> int:
    return int((money(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def amount_from_cents(value: Any) -> Decimal:
    return money(Decimal(int(value or 0)) / Decimal("100"))


@dataclass(frozen=True)
class InternalServiceLine:
    item_id: str
    code: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_rate: Decimal
    subtotal: Decimal
    discount: Decimal
    payable: Decimal
    item_snapshot: dict

    def to_dict(self) -> dict:
        return {
            "itemId": self.item_id,
            "code": self.code,
            "description": self.description,
            "quantity": str(self.quantity),
            "unitPriceCents": cents(self.unit_price),
            "discountRate": str(self.discount_rate),
            "subtotalCents": cents(self.subtotal),
            "discountCents": cents(self.discount),
            "payableCents": cents(self.payable),
            "itemSnapshot": self.item_snapshot,
        }


def calculate_line(item: dict, quantity: Any, discount_rate: Any = "100") -> InternalServiceLine:
    qty = Decimal(str(quantity or "0"))
    rate = Decimal(str(discount_rate or "0"))
    if qty <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    if rate < 0 or rate > 100:
        raise ValueError("El descuento debe estar entre 0 y 100 %.")

    unit_price = money(item.get("price", item.get("unitPrice", 0)))
    if unit_price < 0:
        raise ValueError("El precio unitario no puede ser negativo.")
    subtotal = money(qty * unit_price)
    discount = money(subtotal * rate / Decimal("100"))
    payable = money(subtotal - discount)
    snapshot = dict(item)
    return InternalServiceLine(
        item_id=str(item.get("id", "")),
        code=str(item.get("code", "")),
        description=str(item.get("name", item.get("description", ""))),
        quantity=qty,
        unit_price=unit_price,
        discount_rate=rate,
        subtotal=subtotal,
        discount=discount,
        payable=payable,
        item_snapshot=snapshot,
    )


def calculated_status(document: dict, today: str) -> str:
    if document.get("persistedState") == "voided":
        return "anulado"
    start = document.get("promotionStartDate", "")
    end = document.get("promotionEndDate", "")
    if start and today < start:
        return "proximo"
    if end and today > end:
        return "vencido"
    return "vigente"
