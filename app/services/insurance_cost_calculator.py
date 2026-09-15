"""Calculo y validacion monetaria de contribuciones de seguro."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


CENT = Decimal("0.01")
VALID_TYPES = {"percentage", "fixed_amount", "remainder"}


class InsuranceCostError(ValueError):
    pass


def money(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InsuranceCostError("El importe debe ser numerico.") from exc
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _rule(rule, label):
    rule = rule or {}
    rule_type = rule.get("type", "")
    if rule_type not in VALID_TYPES:
        raise InsuranceCostError(f"Regla invalida para {label}.")
    value = None if rule_type == "remainder" else money(rule.get("value", 0))
    if value is not None and value < 0:
        raise InsuranceCostError(f"El valor de {label} no puede ser negativo.")
    if rule_type == "percentage" and value > 100:
        raise InsuranceCostError(f"El porcentaje de {label} no puede superar 100.")
    return rule_type, value


def calculate_contribution(base_amount, company_rule, employee_rule):
    base = money(base_amount)
    if base < 0:
        raise InsuranceCostError("La tarifa base no puede ser negativa.")
    company_type, company_value = _rule(company_rule, "empresa")
    employee_type, employee_value = _rule(employee_rule, "empleado")
    if company_type == employee_type == "remainder":
        raise InsuranceCostError("Solo una parte puede ser REMAINDER.")

    def resolve(rule_type, value):
        if rule_type == "percentage":
            return (base * value / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
        if rule_type == "fixed_amount":
            return value
        return None

    company = resolve(company_type, company_value)
    employee = resolve(employee_type, employee_value)
    if company is None:
        company = base - employee
    elif employee is None:
        employee = base - company

    if company < 0 or employee < 0:
        raise InsuranceCostError("La contribucion restante no puede ser negativa.")
    if company + employee != base:
        raise InsuranceCostError("Las contribuciones deben completar la tarifa base.")
    return {"companyAmount": company, "employeeAmount": employee, "totalAmount": base}
