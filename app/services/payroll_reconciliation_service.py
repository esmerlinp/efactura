"""PayrollReconciliationService — Conciliación de pagos de nómina con transacciones bancarias."""

from datetime import date, datetime
from typing import Optional


class PayrollReconciliationService:
    """Servicio de conciliación entre nómina pagada y movimientos bancarios."""

    @classmethod
    def reconcile_period(cls, period: dict, bank_transactions: list,
                         employees: dict = None) -> dict:
        """Concilia un período de nómina contra transacciones bancarias.

        Args:
            period: Dict del PayrollPeriod con líneas de nómina.
            bank_transactions: Lista de transacciones bancarias [{amount, description, date, reference}].
            employees: Dict de empleados {id: employee} para matching por nombre.

        Returns:
            Dict con {matched, unmatched, partial, total_net, summary, details}
        """
        from app.services.payroll_service import PayrollService

        plines = period.get("lines", [])
        total_net = period.get("totalNet", 0)
        employees = employees or {}

        matched = []
        unmatched = []
        partial = []
        tx_used = set()

        for line in plines:
            emp_id = line.get("employeeId", "")
            emp = employees.get(emp_id, {})
            emp_name = line.get("employeeName", emp.get("fullName", emp_id))
            net = line.get("netSalary", 0)
            bank = emp.get("bank", "")
            account = emp.get("accountNumber", "")

            best_match = None
            best_score = 0

            for ti, tx in enumerate(bank_transactions):
                if ti in tx_used:
                    continue
                tx_amount = abs(float(tx.get("amount", 0)))
                tx_desc = (tx.get("description", "") or "").lower()
                tx_ref = (tx.get("reference", "") or "").lower()

                score = 0
                if abs(tx_amount - net) < 0.01:
                    score += 50
                elif abs(tx_amount - net) < net * 0.01:
                    score += 30

                if account and account in tx_desc:
                    score += 30
                if emp_name.lower() in tx_desc or emp_name.lower() in tx_ref:
                    score += 40

                if score > best_score:
                    best_score = score
                    best_match = (ti, tx)

            detail = {
                "employeeId": emp_id,
                "employeeName": emp_name,
                "netSalary": net,
                "bank": bank,
                "accountNumber": account,
                "matched": False,
                "transaction": None,
                "score": best_score,
            }

            if best_match and best_score >= 60:
                ti, tx = best_match
                tx_used.add(ti)
                detail["matched"] = True
                detail["transaction"] = {
                    "amount": tx.get("amount"),
                    "date": tx.get("date", ""),
                    "description": tx.get("description", ""),
                    "reference": tx.get("reference", ""),
                }
                matched.append(detail)
            elif best_match and best_score >= 30:
                ti, tx = best_match
                tx_used.add(ti)
                detail["matched"] = True
                detail["transaction"] = {
                    "amount": tx.get("amount"),
                    "date": tx.get("date", ""),
                    "description": tx.get("description", ""),
                    "reference": tx.get("reference", ""),
                }
                partial.append(detail)
            else:
                unmatched.append(detail)

        total_employees = len(plines)
        matched_count = len(matched) + len(partial)
        unmatched_count = len(unmatched)

        return {
            "periodKey": period.get("periodKey", ""),
            "periodRange": period.get("periodRange", ""),
            "totalNet": round(total_net, 2),
            "totalEmployees": total_employees,
            "matchedCount": matched_count,
            "unmatchedCount": unmatched_count,
            "partialCount": len(partial),
            "reconciledPct": round(matched_count / total_employees * 100, 1) if total_employees else 0,
            "matched": matched,
            "partial": partial,
            "unmatched": unmatched,
            "unusedTransactions": [
                {"amount": tx.get("amount"), "date": tx.get("date", ""),
                 "description": tx.get("description", "")}
                for ti, tx in enumerate(bank_transactions) if ti not in tx_used
            ],
        }

    @classmethod
    def reconcile_all_periods(cls, periods: list, bank_transactions: list,
                              employees: dict = None) -> list:
        """Concilia múltiples períodos contra las mismas transacciones bancarias."""
        results = []
        tx_remaining = list(bank_transactions)

        for period in sorted(periods, key=lambda p: p.get("periodKey", "")):
            result = cls.reconcile_period(period, tx_remaining, employees=employees)
            results.append(result)
            tx_remaining = result.get("unusedTransactions", [])
            tx_remaining = [
                {"amount": t["amount"], "date": t.get("date", ""),
                 "description": t.get("description", ""), "reference": t.get("reference", "")}
                for t in tx_remaining
            ]

        return results

    @classmethod
    def suggest_reconciliation(cls, period: dict, employees: dict = None) -> dict:
        """Sugiere acciones para reconciliar pagos no matched.

        Returns un dict con sugerencias por empleado no conciliado.
        """
        employees = employees or {}
        plines = period.get("lines", [])
        suggestions = []

        for line in plines:
            emp_id = line.get("employeeId", "")
            emp = employees.get(emp_id, {})
            net = line.get("netSalary", 0)
            emp_name = line.get("employeeName", emp.get("fullName", emp_id))
            bank = emp.get("bank", "")
            account = emp.get("accountNumber", "")

            actions = []
            if not account:
                actions.append("Registrar número de cuenta bancaria del empleado")
            if not bank:
                actions.append("Registrar banco del empleado")
            if account and bank:
                actions.append(f"Buscar transferencia de RD$ {net:,.2f} a cuenta {account} en {bank}")
            if not actions:
                actions.append(f"Verificar pago de RD$ {net:,.2f} a {emp_name}")

            suggestions.append({
                "employeeId": emp_id,
                "employeeName": emp_name,
                "netSalary": net,
                "bank": bank,
                "accountNumber": account,
                "actions": actions,
            })

        return {"periodKey": period.get("periodKey", ""), "suggestions": suggestions}
