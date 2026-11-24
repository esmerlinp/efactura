"""Shared profitability calculations for dashboard and sales reports."""

from collections import defaultdict


def build_profitability(invoices, catalog_items, year=None, month=0, item_type=None):
    catalog_cost = {}
    for item in catalog_items:
        cost = float(item.get("costPrice", 0) or 0)
        for key in (item.get("id"), item.get("code"), item.get("name")):
            key = str(key or "").strip().lower()
            if key:
                catalog_cost[key] = cost

    products = defaultdict(lambda: {
        "code": "", "name": "", "type": "", "quantity": 0.0,
        "revenue": 0.0, "cost": 0.0, "cost_known": True,
    })

    for invoice in invoices:
        if invoice.get("isQuotation") or invoice.get("status") in ("Anulada", "Borrador", "Consolidada"):
            continue
        date_key = str(invoice.get("date") or invoice.get("createdAt") or "")[:7]
        if year is not None and (not date_key.startswith(f"{year:04d}-") or (month and date_key != f"{year:04d}-{month:02d}")):
            continue
        for line in invoice.get("items", []):
            line_type = line.get("type", "Bien")
            if item_type and line_type != item_type:
                continue
            code = str(line.get("code") or line.get("id") or "").strip()
            name = str(line.get("name") or "Sin nombre").strip()
            key = (code or name).lower()
            quantity = float(line.get("quantity", 1) or 0)
            revenue = float(line.get("total", line.get("subtotal", 0)) or 0)
            cost_key = (code or name).lower()
            historical_cost = float(
                line.get("originalCost") or line.get("unitCost") or line.get("costPrice") or 0
            )
            catalog_unit_cost = catalog_cost.get(cost_key, 0.0)
            unit_cost = historical_cost if historical_cost > 0 else catalog_unit_cost
            has_cost = True
            product = products[key]
            product["code"] = code
            product["name"] = name
            product["type"] = line_type
            product["quantity"] += quantity
            product["revenue"] += revenue
            product["cost_known"] = product["cost_known"] and has_cost
            product["cost"] += unit_cost * quantity

    rows = []
    for product in products.values():
        profit = product["revenue"] - product["cost"] if product["cost_known"] else None
        margin = (profit / product["revenue"] * 100) if profit is not None and product["revenue"] else None
        rows.append({
            "code": product["code"], "name": product["name"], "type": product["type"],
            "quantity": product["quantity"], "revenue": round(product["revenue"], 2),
            "cost": round(product["cost"], 2) if product["cost_known"] else None,
            "profit": round(profit, 2) if profit is not None else None,
            "margin": round(margin, 2) if margin is not None else None,
            "cost_known": product["cost_known"],
        })
    rows.sort(key=lambda row: row["revenue"], reverse=True)
    known = [row for row in rows if row["cost_known"]]
    total_revenue = round(sum(row["revenue"] for row in rows), 2)
    total_cost = round(sum(row["cost"] for row in known), 2)
    total_profit = round(sum(row["profit"] for row in known), 2)
    return rows, total_revenue, total_cost, total_profit
