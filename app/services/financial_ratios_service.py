from datetime import datetime, timezone


class FinancialRatiosService:
    @classmethod
    def compute_all_ratios(cls, owner_uid: str, sandbox: bool = False, company_id: str = None) -> dict:
        from app.services.db_service import DatabaseService

        accounts = DatabaseService.get_chart_of_accounts(owner_uid, company_id=company_id)
        entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox, company_id=company_id)
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, company_id=company_id)

        real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]

        def acc_balance(code_prefix: str) -> float:
            bal = 0.0
            for acc in accounts:
                if acc.get("code", "").startswith(code_prefix):
                    for e in entries:
                        if e.get("status") == "voided":
                            continue
                        for line in e.get("lines", []):
                            if line.get("accountId") == acc.get("id"):
                                bal += float(line.get("debit", 0)) - float(line.get("credit", 0))
            return round(bal, 2)

        def acc_balance_by_group(group: str, nature: str = "deudora") -> float:
            bal = 0.0
            for acc in accounts:
                if acc.get("group") == group and acc.get("type") == "movimiento":
                    for e in entries:
                        if e.get("status") == "voided":
                            continue
                        for line in e.get("lines", []):
                            if line.get("accountId") == acc.get("id"):
                                bal += float(line.get("debit", 0)) - float(line.get("credit", 0))
            return round(abs(bal), 2)

        current_assets = acc_balance("1.1")
        current_liabilities = abs(acc_balance("2.1"))
        cash_and_equivalents = acc_balance("1.1.1") + acc_balance("1.1.2")
        total_assets = acc_balance("1")
        total_liabilities = abs(acc_balance("2"))
        total_equity = acc_balance("3")
        net_income = acc_balance_by_group("ingresos") - acc_balance_by_group("costos") - acc_balance_by_group("gastos")
        revenue = acc_balance_by_group("ingresos")
        cogs = acc_balance_by_group("costos")
        opex = acc_balance_by_group("gastos")

        total_cxc = sum(inv.get("netPayable", 0) for inv in real_invoices if inv.get("status") in ["Emitida", "Vencida"])
        total_cxp = sum(exp.get("cxpRemainingBalance", 0) for exp in expenses if exp.get("cxpStatus") != "Pagado" and exp.get("paymentType") == "Crédito")

        return {
            "liquidity": {
                "current_ratio": cls._safe_div(current_assets, current_liabilities),
                "quick_ratio": cls._safe_div(cash_and_equivalents + total_cxc, current_liabilities),
                "cash_ratio": cls._safe_div(cash_and_equivalents, current_liabilities),
            },
            "efficiency": {
                "ar_turnover": cls._safe_div(revenue, total_cxc) if total_cxc > 0 else 0,
                "ar_days": cls._safe_div(365, cls._safe_div(revenue, total_cxc)) if total_cxc > 0 else 0,
                "ap_turnover": cls._safe_div(cogs, total_cxp) if total_cxp > 0 else 0,
                "ap_days": cls._safe_div(365, cls._safe_div(cogs, total_cxp)) if total_cxp > 0 else 0,
                "asset_turnover": cls._safe_div(revenue, total_assets),
            },
            "profitability": {
                "gross_margin": cls._safe_div(revenue - cogs, revenue) * 100,
                "operating_margin": cls._safe_div(revenue - cogs - opex, revenue) * 100,
                "net_margin": cls._safe_div(net_income, revenue) * 100,
                "roa": cls._safe_div(net_income, total_assets) * 100,
                "roe": cls._safe_div(net_income, total_equity) * 100,
            },
            "leverage": {
                "debt_to_equity": cls._safe_div(total_liabilities, total_equity),
                "debt_ratio": cls._safe_div(total_liabilities, total_assets) * 100,
                "interest_coverage": cls._safe_div(net_income + acc_balance("6.4"), acc_balance("6.4")),
            },
            "working_capital": current_assets - current_liabilities,
        }

    @staticmethod
    def _safe_div(a: float, b: float) -> float:
        if abs(b) < 0.01:
            return 0.0
        return round(a / b, 2)

    @classmethod
    def get_ratio_labels(cls) -> dict:
        return {
            "current_ratio": {"name": "Razón Corriente", "description": "Capacidad de pagar obligaciones a corto plazo", "ideal": "> 1.5"},
            "quick_ratio": {"name": "Prueba Ácida", "description": "Liquidez inmediata sin inventarios", "ideal": "> 1.0"},
            "cash_ratio": {"name": "Razón de Efectivo", "description": "Cobertura con solo efectivo", "ideal": "> 0.2"},
            "ar_turnover": {"name": "Rotación de CxC", "description": "Veces que se cobra CxC al año (veces)", "ideal": "> 6"},
            "ar_days": {"name": "Días de Cobro", "description": "Días promedio para cobrar (días)", "ideal": "< 60"},
            "ap_turnover": {"name": "Rotación de CxP", "description": "Veces que se paga CxP al año (veces)", "ideal": "> 4"},
            "ap_days": {"name": "Días de Pago", "description": "Días promedio para pagar (días)", "ideal": "> 30"},
            "asset_turnover": {"name": "Rotación de Activos", "description": "Eficiencia en uso de activos (veces)", "ideal": "> 1"},
            "gross_margin": {"name": "Margen Bruto", "description": "Rentabilidad después de costos directos (%)", "ideal": "> 30%"},
            "operating_margin": {"name": "Margen Operativo", "description": "Rentabilidad operativa (%)", "ideal": "> 15%"},
            "net_margin": {"name": "Margen Neto", "description": "Rentabilidad final (%)", "ideal": "> 10%"},
            "roa": {"name": "ROA", "description": "Retorno sobre Activos (%)", "ideal": "> 5%"},
            "roe": {"name": "ROE", "description": "Retorno sobre Patrimonio (%)", "ideal": "> 15%"},
            "debt_to_equity": {"name": "Deuda / Patrimonio", "description": "Apalancamiento financiero", "ideal": "< 2.0"},
            "debt_ratio": {"name": "Ratio de Endeudamiento", "description": "Porcentaje de activos financiados con deuda (%)", "ideal": "< 60%"},
            "interest_coverage": {"name": "Cobertura de Intereses", "description": "Capacidad de pagar intereses", "ideal": "> 3.0"},
        }
