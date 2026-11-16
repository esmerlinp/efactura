from decimal import Decimal, InvalidOperation


E32_BUYER_IDENTIFICATION_THRESHOLD = Decimal("250000.00")


def to_decimal_amount(value):
    """Convert persisted/request amounts without introducing binary float error."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def is_e32(ecf_type):
    value = str(ecf_type or "")
    return "E32" in value or "Factura de Consumo" in value


def e32_requires_buyer_identification(total):
    return to_decimal_amount(total) >= E32_BUYER_IDENTIFICATION_THRESHOLD


def e32_is_rfce(total):
    return to_decimal_amount(total) < E32_BUYER_IDENTIFICATION_THRESHOLD


def normalized_buyer_identifier(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def has_valid_e32_buyer_identifier(value):
    identifier = normalized_buyer_identifier(value)
    return identifier not in ("", "000000000") and len(identifier) in (9, 11)
