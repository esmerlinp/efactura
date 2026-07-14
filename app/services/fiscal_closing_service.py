from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from flask import current_app as app


class FiscalClosingService:
    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @classmethod
    def generate_closing_preview(cls, owner_uid: str, year: int, sandbox: bool = False) -> dict:
        from app.services.db_service import DatabaseService

        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        all_entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)

        # Filtrar entradas por el año fiscal correspondiente
        date_from = f"{year}-01-01"
        date_to = f"{year}-12-31"
        entries = [
            e for e in all_entries
            if date_from <= str(e.get("date", ""))[:10] <= date_to
        ]
        # Incluir también entradas de cierre del año (dated 12-31 pero con entryType "closing")
        closing_entries = [
            e for e in all_entries
            if e.get("entryType") == "closing" and str(e.get("concept", "")).endswith(str(year))
        ]
        existing_closing_ids = {e["id"] for e in entries if e.get("entryType") == "closing"}
        for ce in closing_entries:
            if ce["id"] not in existing_closing_ids:
                entries.append(ce)

        income_codes = {"4"}
        expense_codes = {"5", "6"}

        income_balances = {}
        expense_balances = {}
        retained_earnings_account = None
        retained_earnings_nature = "acreedora"

        for acc in accounts:
            code = acc.get("code", "")
            group = acc.get("group", "")
            usage = acc.get("usage", "")

            if usage == "resultados_acumulados" or "resultado" in acc.get("name", "").lower():
                retained_earnings_account = acc
                retained_earnings_nature = acc.get("nature", "acreedora")

            if not code:
                continue

            is_income = False
            is_expense = False
            for prefix in income_codes:
                if code.startswith(prefix) and acc.get("type") == "movimiento":
                    is_income = True
                    break
            if not is_income:
                for prefix in expense_codes:
                    if code.startswith(prefix) and acc.get("type") == "movimiento":
                        is_expense = True
                        break

            if not is_income and not is_expense:
                continue

            balance = cls._compute_account_balance(acc["id"], entries)
            if is_income:
                income_balances[acc["id"]] = {"code": code, "name": acc.get("name", ""), "balance": balance, "nature": acc.get("nature", "deudora")}
            else:
                expense_balances[acc["id"]] = {"code": code, "name": acc.get("name", ""), "balance": balance, "nature": acc.get("nature", "deudora")}

        net_income = 0.0
        income_lines = []
        expense_lines = []

        for acc_id, data in income_balances.items():
            nature = data["nature"]
            balance = data["balance"]
            if nature == "acreedora":
                net_income += balance
                if abs(balance) > 0.01:
                    income_lines.append({"accountId": acc_id, "accountCode": data["code"], "accountName": data["name"], "debit": abs(balance), "credit": 0.0, "description": f"Cierre de ingresos {year}"})
            else:
                net_income -= balance
                if abs(balance) > 0.01:
                    income_lines.append({"accountId": acc_id, "accountCode": data["code"], "accountName": data["name"], "debit": 0.0, "credit": abs(balance), "description": f"Cierre de ingresos {year}"})

        for acc_id, data in expense_balances.items():
            nature = data["nature"]
            balance = data["balance"]
            if nature == "deudora":
                net_income -= balance
                if abs(balance) > 0.01:
                    expense_lines.append({"accountId": acc_id, "accountCode": data["code"], "accountName": data["name"], "debit": 0.0, "credit": abs(balance), "description": f"Cierre de gastos/costos {year}"})
            else:
                net_income += balance
                if abs(balance) > 0.01:
                    expense_lines.append({"accountId": acc_id, "accountCode": data["code"], "accountName": data["name"], "debit": abs(balance), "credit": 0.0, "description": f"Cierre de gastos/costos {year}"})

        retained_line = None
        if retained_earnings_account:
            if net_income > 0:
                retained_line = {"accountId": retained_earnings_account["id"], "accountCode": retained_earnings_account.get("code", ""), "accountName": retained_earnings_account.get("name", ""), "debit": 0.0, "credit": abs(net_income), "description": f"Utilidad neta del ejercicio {year}"}
            elif net_income < 0:
                retained_line = {"accountId": retained_earnings_account["id"], "accountCode": retained_earnings_account.get("code", ""), "accountName": retained_earnings_account.get("name", ""), "debit": abs(net_income), "credit": 0.0, "description": f"Pérdida neta del ejercicio {year}"}

        return {
            "year": year,
            "net_income": round(net_income, 2),
            "income_lines": income_lines,
            "expense_lines": expense_lines,
            "retained_line": retained_line,
            "total_income_accounts": len(income_balances),
            "total_expense_accounts": len(expense_balances),
            "retained_earnings_account": retained_earnings_account.get("name") if retained_earnings_account else None,
        }

    @classmethod
    def execute_year_close(cls, owner_uid: str, year: int, performed_by: str = "", sandbox: bool = False) -> dict:
        from app.services.accounting_service import AccountingService
        from app.services.accounting_service import _accounting_entry_exists

        # Prevenir doble cierre
        if _accounting_entry_exists(owner_uid, "closing", f"year_{year}"):
            return {"status": "already_closed", "message": f"El año fiscal {year} ya tiene un asiento de cierre."}

        preview = cls.generate_closing_preview(owner_uid, year, sandbox=sandbox)

        lines = preview["income_lines"] + preview["expense_lines"]
        if preview["retained_line"]:
            lines.append(preview["retained_line"])

        if not lines:
            return {"status": "no_entries", "message": "No hay movimientos en cuentas de ingreso/gasto para este año."}

        entry_data = {
            "entryType": "closing",
            "date": f"{year}-12-31",
            "concept": f"Asiento de cierre del ejercicio fiscal {year}",
            "lines": lines,
            "createdBy": performed_by,
            "referenceId": f"year_{year}",
            "prefix": "C",
        }

        entry = AccountingService.generate_entry(owner_uid, entry_data, sandbox=sandbox)

        from app.services.fiscal_period_service import FiscalPeriodService
        FiscalPeriodService.close_year(owner_uid, year, closed_by=performed_by)

        return {"status": "success", "entry_id": entry["id"], "entry_number": entry["number"], "net_income": preview["net_income"]}

    @staticmethod
    def _compute_account_balance(account_id: str, entries: list) -> float:
        debit = 0.0
        credit = 0.0
        for entry in entries:
            if entry.get("status") == "voided":
                continue
            for line in entry.get("lines", []):
                if line.get("accountId") == account_id:
                    debit += float(line.get("debit", 0))
                    credit += float(line.get("credit", 0))
        return round(debit - credit, 2)
