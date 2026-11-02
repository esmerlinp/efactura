"""Precarga conservadora del IR-17.

No infiere una retención a partir del total de una factura. Solo usa campos
explícitos de retención, clasificación y base presentes en registros fuente.
"""

from collections import defaultdict


def _period(value):
    return str(value or "")[:7].replace("-", "")


def build_prefill(expenses, period):
    grouped = defaultdict(lambda: {"base": 0.0, "tax": 0.0, "records": []})
    warnings = []
    for expense in expenses or []:
        if _period(expense.get("date") or expense.get("createdAt")) != period:
            continue
        number = expense.get("ir17Line") or expense.get("tipoRetencionIR17")
        base = expense.get("ir17Base")
        tax = expense.get("isrWithheld") or expense.get("retainedISR")
        rate = expense.get("ir17Rate")
        if number is None or base is None or tax is None or rate is None:
            continue
        try:
            number = int(number)
            base = float(base)
            tax = float(tax)
            rate = float(rate)
        except (TypeError, ValueError):
            warnings.append(f"Registro {expense.get('id', '')} omitido: datos IR-17 inválidos.")
            continue
        grouped[number]["base"] += base
        grouped[number]["tax"] += tax
        grouped[number]["records"].append(expense.get("id", ""))
    return {"lines": dict(grouped), "warnings": warnings}
