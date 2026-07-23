"""
PaymentSchedulerService — Calendario de pagos, priorización y sugerencias de plan de pagos.

Gestiona la programación de pagos a proveedores (CxP) basándose en:
- Fechas de vencimiento
- Prioridad del proveedor
- Montos pendientes
- Liquidez disponible
"""

from datetime import datetime, timedelta, timezone, date
from dataclasses import dataclass, field
from typing import Optional

from app.services.db_service import DatabaseService


@dataclass
class ScheduledPayment:
    """Pago programado individual."""
    expense_id: str
    concept: str
    supplier_name: str = ""
    supplier_rnc: str = ""
    due_date: str = ""
    amount: float = 0.0
    remaining: float = 0.0
    days_overdue: int = 0
    priority: str = "normal"  # "urgent", "high", "normal", "low"
    suggested_pay_date: str = ""
    category: str = ""
    cxp_status: str = ""


@dataclass
class PaymentPlan:
    """Plan de pagos sugerido."""
    payments: list = field(default_factory=list)
    total_to_pay: float = 0.0
    available_balance: float = 0.0
    remaining_after_plan: float = 0.0
    coverage_pct: float = 0.0
    uncovered_amount: float = 0.0
    uncovered_count: int = 0


class PaymentSchedulerService:
    """Servicio de programación de pagos."""

    @classmethod
    def get_payment_calendar(
        cls,
        owner_uid: str,
        sandbox: bool = True,
        days_ahead: int = 60,
        include_paid: bool = False,
        company_id: Optional[str] = None,
    ) -> list[ScheduledPayment]:
        """
        Obtiene el calendario de pagos CxP pendientes.

        Args:
            owner_uid: UID del propietario.
            sandbox: Entorno.
            days_ahead: Días hacia adelante para proyectar.
            include_paid: Incluir pagos ya realizados.
            company_id: ID de la empresa (multi-company).

        Returns:
            Lista de ScheduledPayment ordenados por prioridad.
        """
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, company_id=company_id) or []
        payments = []

        for exp in expenses:
            if exp.get("approvalStatus") == "Rechazado":
                continue
            if exp.get("paymentType") != "Crédito":
                continue
            cxp_status = exp.get("cxpStatus", "")
            if cxp_status == "Pagado" and not include_paid:
                continue

            remaining = float(exp.get("cxpRemainingBalance", 0.0))
            if remaining <= 0 and cxp_status == "Pagado":
                continue

            due_str = exp.get("dueDate", "") or exp.get("date", "")
            due_date = cls._parse_date(due_str)
            days_overdue = (today - due_date).days if due_date < today else 0
            amount = remaining if remaining > 0 else float(exp.get("amount", 0.0))

            # Determinar prioridad
            priority = cls._calculate_priority(days_overdue, amount)

            # Día sugerido de pago
            suggested = cls._suggest_pay_date(due_date, today, priority)

            payments.append(ScheduledPayment(
                expense_id=exp.get("id", ""),
                concept=exp.get("concept", "Sin concepto"),
                supplier_name=exp.get("supplierName", ""),
                supplier_rnc=exp.get("rncEmisor", ""),
                due_date=due_date.isoformat(),
                amount=amount,
                remaining=remaining,
                days_overdue=max(0, days_overdue),
                priority=priority,
                suggested_pay_date=suggested.isoformat(),
                category=exp.get("category", ""),
                cxp_status=cxp_status,
            ))

        # Ordenar: urgentes primero, luego por días vencidos, luego por monto
        priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        payments.sort(key=lambda p: (
            priority_order.get(p.priority, 99),
            -p.days_overdue,
            -p.amount,
        ))

        return payments

    @classmethod
    def suggest_payment_plan(
        cls,
        owner_uid: str,
        sandbox: bool = True,
        max_days: int = 30,
        company_id: Optional[str] = None,
    ) -> PaymentPlan:
        """
        Sugiere un plan de pagos priorizado basado en liquidez disponible.

        Args:
            owner_uid: UID del propietario.
            sandbox: Entorno.
            max_days: Solo considerar pagos con vencimiento en estos días.
            company_id: ID de la empresa (multi-company).

        Returns:
            PaymentPlan con pagos sugeridos y métricas.
        """
        from app.services.cash_flow_service import CashFlowService

        available = CashFlowService.get_current_liquidity(owner_uid, sandbox=sandbox, company_id=company_id)
        all_payments = cls.get_payment_calendar(owner_uid, sandbox=sandbox, company_id=company_id)

        today = date.today()
        cutoff = today + timedelta(days=max_days)
        pending = [
            p for p in all_payments
            if cls._parse_date(p.due_date) <= cutoff
        ]

        plan = PaymentPlan(
            payments=[],
            available_balance=available,
        )
        remaining_budget = available

        for p in pending:
            if remaining_budget >= p.amount:
                plan.payments.append(p)
                plan.total_to_pay += p.amount
                remaining_budget -= p.amount
            else:
                # Pago parcial si es urgente
                if p.priority in ("urgent", "high") and remaining_budget > 0:
                    partial = p
                    partial.amount = remaining_budget
                    plan.payments.append(partial)
                    plan.total_to_pay += remaining_budget
                    remaining_budget = 0
                break

        plan.remaining_after_plan = remaining_budget
        plan.uncovered_amount = sum(
            p.amount for p in pending
            if p.expense_id not in {x.expense_id for x in plan.payments}
        )
        plan.uncovered_count = len(pending) - len(plan.payments)
        plan.coverage_pct = round(
            (plan.total_to_pay / (plan.total_to_pay + plan.uncovered_amount)) * 100
            if (plan.total_to_pay + plan.uncovered_amount) > 0 else 100,
            1,
        )

        return plan

    @classmethod
    def get_calendar_stats(cls, owner_uid: str, sandbox: bool = True, company_id: Optional[str] = None) -> dict:
        """Estadísticas del calendario de pagos."""
        today = date.today()
        payments = cls.get_payment_calendar(owner_uid, sandbox=sandbox, company_id=company_id)

        overdue = [p for p in payments if p.days_overdue > 0]
        this_week = [
            p for p in payments
            if 0 <= (cls._parse_date(p.due_date) - today).days <= 7
        ]
        this_month = [
            p for p in payments
            if 0 <= (cls._parse_date(p.due_date) - today).days <= 30
        ]

        return {
            "total_pending": len(payments),
            "total_amount": round(sum(p.amount for p in payments), 2),
            "overdue_count": len(overdue),
            "overdue_amount": round(sum(p.amount for p in overdue), 2),
            "this_week_count": len(this_week),
            "this_week_amount": round(sum(p.amount for p in this_week), 2),
            "this_month_count": len(this_month),
            "this_month_amount": round(sum(p.amount for p in this_month), 2),
            "urgent_count": sum(1 for p in payments if p.priority == "urgent"),
            "high_count": sum(1 for p in payments if p.priority == "high"),
        }

    @staticmethod
    def _parse_date(date_str: str) -> date:
        """Convierte string de fecha a date."""
        if not date_str:
            return date.today()
        date_str = str(date_str)[:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except Exception:
            return date.today()

    @staticmethod
    def _calculate_priority(days_overdue: int, amount: float) -> str:
        """Determina prioridad basada en días vencidos y monto."""
        if days_overdue > 30:
            return "urgent"
        if days_overdue > 7:
            return "high"
        if days_overdue > 0:
            return "high"
        if amount > 50000:
            return "high"
        if amount > 10000:
            return "normal"
        return "low"

    @staticmethod
    def _suggest_pay_date(due_date: date, today: date, priority: str) -> date:
        """Sugiere fecha de pago basada en prioridad."""
        if priority == "urgent":
            return today
        if priority == "high":
            return today + timedelta(days=3)
        if due_date <= today:
            return today + timedelta(days=7)
        return due_date
