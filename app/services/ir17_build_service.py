"""Construcción del IR-17 desde retenciones efectivamente aplicadas (pagos aprobados).

El IR-17 declara la retención realmente retenida mediante pagos aprobados, no el
importe calculado en la factura. La base se prorratea proporcionalmente a la
retención aplicada.
"""

from collections import defaultdict

from app.countries.do.tax_rules import ISR_RULE_TO_IR17_LINE


def build_applied_retention_records(items):
    """Construye registros de retención aplicada a partir de facturas + pagos.

    ``items``: lista de dicts ``{"invoice": {...}, "payments": [...]}``. Solo se
    consideran pagos aprobados y no anulados; la base se prorratea a la retención
    efectivamente aplicada. Las categorías sin línea IR-17 confirmada se omiten.
    """
    records = []
    for item in (items or []):
        invoice = item.get("invoice") or {}
        rule = str(invoice.get("retentionIsrRule") or "").strip().lower()
        line = ISR_RULE_TO_IR17_LINE.get(rule)
        if not line:
            continue
        base = float(invoice.get("retentionIsrBase") or 0)
        calculated = float(invoice.get("retentionIsrAmount") or 0)
        rate = float(invoice.get("retentionIsrRate") or 0)
        for p in (item.get("payments") or []):
            if str(p.get("status") or "").lower() == "voided":
                continue
            if str(p.get("approvalStatus") or "").lower() != "approved":
                continue
            applied = round(float(p.get("retentionIsrApplied") or 0), 2)
            if applied <= 0:
                continue
            applied_base = round(base * (applied / calculated), 2) if calculated > 0 else 0.0
            period = (str(p.get("paymentDate") or "")[:7]).replace("-", "")
            records.append({
                "ir17Line": line,
                "ir17Base": applied_base,
                "ir17Rate": rate,
                "isrWithheld": applied,
                "period": period,
                "supplierId": invoice.get("supplierId", ""),
                "invoiceId": invoice.get("id", ""),
                "paymentId": p.get("id", ""),
                "rule": rule,
            })
    return records


def aggregate_ir17(records, period=None):
    """Agrupa por línea IR-17 (y período opcional) con base, ISR y conteo."""
    grouped = defaultdict(lambda: {"base": 0.0, "tax": 0.0, "count": 0, "operations": []})
    for r in records:
        if period and r.get("period") != period:
            continue
        key = r["ir17Line"]
        grouped[key]["base"] = round(grouped[key]["base"] + r["ir17Base"], 2)
        grouped[key]["tax"] = round(grouped[key]["tax"] + r["isrWithheld"], 2)
        grouped[key]["count"] += 1
        grouped[key]["operations"].append(r)
    return dict(grouped)


def build_ir17_summary(items, period=None):
    """Devuelve ``(registros aplicados, resumen agrupado por línea)``."""
    records = build_applied_retention_records(items)
    return records, aggregate_ir17(records, period=period)
