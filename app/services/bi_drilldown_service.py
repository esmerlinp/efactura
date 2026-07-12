from collections import defaultdict
from datetime import datetime, timezone


DRILLDOWN_METRICS = {
    "sales": "Ventas",
    "expenses": "Egresos",
    "cxc": "Cuentas por Cobrar",
    "cxp": "Cuentas por Pagar",
    "taxes": "ITBIS",
    "products": "Margen por Producto",
    "clients": "Clientes Rentables",
    "budget": "Presupuesto vs Real",
}


class BIDrilldownService:
    @staticmethod
    def _parse_date(value):
        try:
            if not value:
                return None
            if "T" in value:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            return datetime.strptime(value[:10], "%Y-%m-%d")
        except Exception:
            return None

    @classmethod
    def _in_period(cls, doc: dict, year: int, month: int, date_fields=None) -> bool:
        for field in date_fields or ("date", "createdAt"):
            dt = cls._parse_date(doc.get(field, ""))
            if dt:
                return dt.year == year and (month == 0 or dt.month == month)
        return False

    @classmethod
    def get_drilldown(cls, owner_uid: str, metric: str, year: int = None, month: int = 0, sandbox: bool = True, branch_id: str = None, project_id: str = None) -> dict:
        from app.services.db_service import DatabaseService

        now = datetime.now(timezone.utc)
        year = int(year or now.year)
        month = int(month or 0)
        metric = metric if metric in DRILLDOWN_METRICS else "sales"

        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, branch_id=branch_id, project_id=project_id)
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=branch_id, project_id=project_id)
        real_invoices = [
            inv for inv in invoices
            if not inv.get("isQuotation") and inv.get("status") not in ("Anulada", "Borrador", "Consolidada")
        ]

        if metric == "sales":
            rows = cls._sales_rows(real_invoices, year, month)
            total = sum(r["amount"] for r in rows)
            columns = ["Fecha", "Documento", "Cliente", "Estado", "Monto"]
        elif metric == "expenses":
            rows = cls._expense_rows(expenses, year, month)
            total = sum(r["amount"] for r in rows)
            columns = ["Fecha", "Documento", "Proveedor / Concepto", "Categoría", "Monto"]
        elif metric == "cxc":
            rows = cls._cxc_rows(real_invoices)
            total = sum(r["amount"] for r in rows)
            columns = ["Fecha", "Documento", "Cliente", "Estado", "Balance"]
        elif metric == "cxp":
            rows = cls._cxp_rows(expenses)
            total = sum(r["amount"] for r in rows)
            columns = ["Fecha", "Documento", "Proveedor / Concepto", "Estado", "Balance"]
        elif metric == "taxes":
            rows = cls._tax_rows(real_invoices, expenses, year, month)
            total = sum(r["amount"] for r in rows)
            columns = ["Fecha", "Tipo", "Documento", "Base", "ITBIS"]
        elif metric == "products":
            rows = cls._product_rows(real_invoices, year, month)
            total = sum(r["amount"] for r in rows)
            columns = ["Producto", "Cantidad", "Ingresos", "Costo Est.", "Margen"]
        elif metric == "clients":
            rows = cls._client_rows(real_invoices, year, month)
            total = sum(r["amount"] for r in rows)
            columns = ["Cliente", "Facturas", "Ingresos", "Ganancia Est.", "Margen"]
        else:
            rows = cls._budget_rows(owner_uid, year, month or now.month, sandbox)
            total = sum(r["amount"] for r in rows)
            columns = ["Categoría", "Presupuesto", "Real", "Variación", "Uso"]

        return {
            "metric": metric,
            "title": DRILLDOWN_METRICS[metric],
            "year": year,
            "month": month,
            "columns": columns,
            "rows": rows,
            "total": round(total, 2),
            "count": len(rows),
        }

    @classmethod
    def _sales_rows(cls, invoices, year, month):
        rows = []
        for inv in invoices:
            if not cls._in_period(inv, year, month):
                continue
            rows.append({
                "date": (inv.get("date") or inv.get("createdAt") or "")[:10],
                "doc": inv.get("invoiceNumber") or inv.get("encf") or inv.get("id", ""),
                "name": inv.get("clientName") or inv.get("clientRNC") or "Consumidor Final",
                "status": inv.get("status", ""),
                "amount": round(float(inv.get("total", 0.0)), 2),
                "link": ("web_invoices.invoice_detail", {"invoice_id": inv.get("id")}) if inv.get("id") else None,
            })
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    @classmethod
    def _expense_rows(cls, expenses, year, month):
        rows = []
        for exp in expenses:
            if not cls._in_period(exp, year, month):
                continue
            rows.append({
                "date": (exp.get("date") or exp.get("createdAt") or "")[:10],
                "doc": exp.get("ncf") or exp.get("ecfNumber") or exp.get("id", ""),
                "name": exp.get("providerName") or exp.get("concept") or "Gasto",
                "status": exp.get("category", "otros"),
                "amount": round(float(exp.get("amount", 0.0)), 2),
                "link": ("web_invoices.expense_detail", {"expense_id": exp.get("id")}) if exp.get("id") else None,
            })
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    @classmethod
    def _cxc_rows(cls, invoices):
        rows = []
        for inv in invoices:
            if inv.get("status") not in ("Emitida", "Vencida", "Parcialmente Cobrada"):
                continue
            balance = float(inv.get("remainingBalance", inv.get("netPayable", 0.0)) or 0.0)
            if balance <= 0:
                continue
            rows.append({
                "date": (inv.get("dueDate") or inv.get("date") or "")[:10],
                "doc": inv.get("invoiceNumber") or inv.get("encf") or inv.get("id", ""),
                "name": inv.get("clientName") or inv.get("clientRNC") or "Cliente",
                "status": inv.get("status", ""),
                "amount": round(balance, 2),
                "link": ("web_invoices.invoice_detail", {"invoice_id": inv.get("id")}) if inv.get("id") else None,
            })
        return sorted(rows, key=lambda r: r["date"])

    @staticmethod
    def _cxp_rows(expenses):
        rows = []
        for exp in expenses:
            if exp.get("paymentType") != "Crédito" or exp.get("cxpStatus") == "Pagado":
                continue
            balance = float(exp.get("cxpRemainingBalance", exp.get("amount", 0.0)) or 0.0)
            if balance <= 0:
                continue
            rows.append({
                "date": (exp.get("dueDate") or exp.get("date") or "")[:10],
                "doc": exp.get("ncf") or exp.get("ecfNumber") or exp.get("id", ""),
                "name": exp.get("providerName") or exp.get("concept") or "Cuenta por pagar",
                "status": exp.get("cxpStatus", ""),
                "amount": round(balance, 2),
                "link": ("web_invoices.expense_detail", {"expense_id": exp.get("id")}) if exp.get("id") else None,
            })
        return sorted(rows, key=lambda r: r["date"])

    @classmethod
    def _tax_rows(cls, invoices, expenses, year, month):
        rows = []
        for inv in invoices:
            if cls._in_period(inv, year, month):
                rows.append({
                    "date": (inv.get("date") or "")[:10],
                    "doc": inv.get("invoiceNumber") or inv.get("encf") or inv.get("id", ""),
                    "name": "ITBIS en venta",
                    "status": f"Base RD$ {float(inv.get('subtotal', 0.0)):,.2f}",
                    "amount": round(float(inv.get("totalITBIS", 0.0)), 2),
                    "link": ("web_invoices.invoice_detail", {"invoice_id": inv.get("id")}) if inv.get("id") else None,
                })
        for exp in expenses:
            if cls._in_period(exp, year, month):
                rows.append({
                    "date": (exp.get("date") or "")[:10],
                    "doc": exp.get("ncf") or exp.get("ecfNumber") or exp.get("id", ""),
                    "name": "ITBIS en compra",
                    "status": f"Base RD$ {float(exp.get('amount', 0.0)):,.2f}",
                    "amount": -round(float(exp.get("itbisAmount", 0.0)), 2),
                    "link": ("web_invoices.expense_detail", {"expense_id": exp.get("id")}) if exp.get("id") else None,
                })
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    @classmethod
    def _product_rows(cls, invoices, year, month):
        products = defaultdict(lambda: {"name": "", "qty": 0.0, "revenue": 0.0, "cost": 0.0})
        for inv in invoices:
            if not cls._in_period(inv, year, month):
                continue
            for item in inv.get("items", []):
                key = item.get("id") or item.get("code") or item.get("name") or "Sin producto"
                qty = float(item.get("quantity", 0) or 0)
                revenue = float(item.get("total", item.get("subtotal", 0)) or 0)
                cost = float(item.get("costPrice", item.get("cost", 0)) or 0) * qty
                products[key]["name"] = item.get("name") or key
                products[key]["qty"] += qty
                products[key]["revenue"] += revenue
                products[key]["cost"] += cost
        rows = []
        for p in products.values():
            profit = p["revenue"] - p["cost"]
            margin = round((profit / p["revenue"]) * 100, 1) if p["revenue"] else 0
            rows.append({
                "date": p["name"],
                "doc": f"{p['qty']:,.2f}",
                "name": f"RD$ {p['revenue']:,.2f}",
                "status": f"RD$ {p['cost']:,.2f}",
                "amount": round(profit, 2),
                "pct": margin,
                "link": None,
            })
        return sorted(rows, key=lambda r: r["amount"], reverse=True)

    @classmethod
    def _client_rows(cls, invoices, year, month):
        clients = defaultdict(lambda: {"name": "", "count": 0, "revenue": 0.0, "profit": 0.0})
        for inv in invoices:
            if not cls._in_period(inv, year, month):
                continue
            cid = inv.get("clientId") or inv.get("clientRNC") or "consumidor-final"
            revenue = float(inv.get("total", 0) or 0)
            cost = 0.0
            for item in inv.get("items", []):
                cost += float(item.get("costPrice", item.get("cost", 0)) or 0) * float(item.get("quantity", 0) or 0)
            clients[cid]["name"] = inv.get("clientName") or inv.get("clientRNC") or "Consumidor Final"
            clients[cid]["count"] += 1
            clients[cid]["revenue"] += revenue
            clients[cid]["profit"] += revenue - cost
        rows = []
        for c in clients.values():
            margin = round((c["profit"] / c["revenue"]) * 100, 1) if c["revenue"] else 0
            rows.append({
                "date": c["name"],
                "doc": str(c["count"]),
                "name": f"RD$ {c['revenue']:,.2f}",
                "status": f"RD$ {c['profit']:,.2f}",
                "amount": round(c["profit"], 2),
                "pct": margin,
                "link": None,
            })
        return sorted(rows, key=lambda r: r["amount"], reverse=True)

    @staticmethod
    def _budget_rows(owner_uid, year, month, sandbox):
        from app.services.budget_service import BudgetService
        variance = BudgetService.get_variance(owner_uid, year, month, sandbox=sandbox)
        rows = []
        for item in variance.values():
            rows.append({
                "date": item["label"],
                "doc": f"RD$ {item['budget']:,.2f}",
                "name": f"RD$ {item['actual']:,.2f}",
                "status": f"RD$ {item['variance']:,.2f}",
                "amount": item["variance"],
                "pct": item["pct_used"],
                "link": None,
            })
        return rows

