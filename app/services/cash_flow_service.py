"""
CashFlowService — Proyección de flujo de caja, alertas de liquidez y forecasting.

Factores considerados:
- Saldos actuales de cuentas bancarias
- CxC: facturas pendientes de cobro con fecha de vencimiento
- CxP: gastos a crédito pendientes de pago con fecha de vencimiento
- Recurrencias: facturas y gastos recurrentes programados
- Contratos: facturación automática de contratos activos
"""

import calendar
from datetime import datetime, timedelta, timezone, date
from dataclasses import dataclass, field
from typing import Optional

from app.services.db_service import DatabaseService


@dataclass
class CashFlowItem:
    """Ítem individual de flujo de caja proyectado."""
    date: str
    description: str
    amount: float
    type: str  # "inflow" | "outflow"
    source: str  # "cxc", "cxp", "recurring_invoice", "recurring_expense", "contract", "transfer"
    reference_id: str = ""
    certainty: str = "high"  # "high" (factura emitida), "medium" (recurrencia), "low" (estimado)


@dataclass
class MonthProjection:
    """Proyección mensual agregada."""
    key: str  # "2026-07"
    label: str  # "Julio 2026"
    inflow: float = 0.0
    outflow: float = 0.0
    net: float = 0.0
    cumulative: float = 0.0
    items: list = field(default_factory=list)


@dataclass
class DeficitAlert:
    """Alerta de déficit de liquidez."""
    month_label: str
    month_key: str
    projected_balance: float
    severity: str  # "warning" (negativo próximo mes), "danger" (negativo este mes), "critical" (múltiples meses)


class CashFlowService:
    """Servicio de proyección de flujo de caja."""

    @staticmethod
    def _parse_date(date_str: str) -> date:
        """Convierte string de fecha a date, con múltiples formatos."""
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

    @classmethod
    def get_current_liquidity(cls, owner_uid: str, sandbox: bool = True) -> float:
        """Saldo total disponible sumando todas las cuentas bancarias."""
        accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox) or []
        return sum(float(a.get("currentBalance", 0.0)) for a in accounts)

    @classmethod
    def project_cash_flow(
        cls,
        owner_uid: str,
        months: int = 12,
        sandbox: bool = True,
        include_recurring: bool = True,
        include_contracts: bool = True,
        invoices: Optional[list] = None,
        expenses: Optional[list] = None,
    ) -> list[MonthProjection]:
        """
        Genera proyección de flujo de caja para los próximos N meses.

        Args:
            owner_uid: UID del propietario.
            months: Número de meses a proyectar (default 12).
            sandbox: Entorno sandbox o producción.
            include_recurring: Incluir facturas/gastos recurrentes programados.
            include_contracts: Incluir contratos con nextBillingDate.
            invoices: Lista de facturas pre-fetched (opcional).
            expenses: Lista de gastos pre-fetched (opcional).

        Returns:
            Lista de MonthProjection ordenada cronológicamente.
        """
        today = date.today()
        current_balance = cls.get_current_liquidity(owner_uid, sandbox=sandbox)

        # Inicializar meses
        projections: dict[str, MonthProjection] = {}
        for i in range(months):
            proj_date = today.replace(day=1)
            # Avanzar i meses respetando cambio de año
            m = proj_date.month - 1 + i
            y = proj_date.year + m // 12
            m = m % 12 + 1
            key = f"{y}-{m:02d}"
            label = cls._month_label(y, m)
            projections[key] = MonthProjection(key=key, label=label)

        # ── CxC: Facturas pendientes de cobro ──
        invoices = invoices if invoices is not None else (DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or [])
        for inv in invoices:
            if inv.get("isQuotation") or inv.get("status") in ("Anulada", "Borrador", "Pagado", "Consolidada"):
                continue
            remaining = float(inv.get("remainingBalance", 0.0))
            if remaining <= 0:
                continue
            due_str = inv.get("dueDate", "")
            due_date = cls._parse_date(due_str)
            key = f"{due_date.year}-{due_date.month:02d}"
            if key in projections:
                projections[key].inflow += remaining
                projections[key].items.append({
                    "date": due_date.isoformat(),
                    "description": f"Cobro {inv.get('invoiceNumber', '')} — {inv.get('clientName', '')}",
                    "amount": remaining,
                    "type": "inflow",
                    "source": "cxc",
                    "reference_id": inv.get("id", ""),
                    "certainty": "high",
                })

        # ── CxP: Gastos a crédito pendientes de pago ──
        expenses = expenses if expenses is not None else (DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or [])
        for exp in expenses:
            if exp.get("approvalStatus") == "Rechazado":
                continue
            if exp.get("paymentType") != "Crédito":
                continue
            if exp.get("cxpStatus") == "Pagado":
                continue
            remaining = float(exp.get("cxpRemainingBalance", 0.0))
            if remaining <= 0:
                continue
            due_str = exp.get("dueDate", "") or exp.get("date", "")
            due_date = cls._parse_date(due_str)
            key = f"{due_date.year}-{due_date.month:02d}"
            if key in projections:
                projections[key].outflow += remaining
                projections[key].items.append({
                    "date": due_date.isoformat(),
                    "description": f"Pago {exp.get('concept', 'Gasto')}",
                    "amount": remaining,
                    "type": "outflow",
                    "source": "cxp",
                    "reference_id": exp.get("id", ""),
                    "certainty": "high",
                })

        # ── Recurrencias: Facturas recurrentes ──
        if include_recurring:
            for inv in invoices:
                if not inv.get("isRecurring"):
                    continue
                next_date_str = inv.get("nextOccurrenceDate", "")
                if not next_date_str:
                    continue
                next_date = cls._parse_date(next_date_str)
                amount = float(inv.get("total", 0.0))
                interval = inv.get("recurrenceInterval", "mensual")
                cls._add_recurring_items(
                    projections, next_date, amount, "inflow", "recurring_invoice",
                    f"Factura recurrente — {inv.get('clientName', '')}",
                    inv.get("id", ""), interval, months, today
                )

            # Gastos recurrentes
            for exp in expenses:
                if not exp.get("isRecurring"):
                    continue
                next_date_str = exp.get("nextOccurrenceDate", "")
                if not next_date_str:
                    continue
                next_date = cls._parse_date(next_date_str)
                amount = float(exp.get("amount", 0.0))
                interval = exp.get("recurrenceInterval", "mensual")
                end_date_str = exp.get("recurrenceEndDate", "")
                end_date = cls._parse_date(end_date_str) if end_date_str else None
                cls._add_recurring_items(
                    projections, next_date, amount, "outflow", "recurring_expense",
                    f"Gasto recurrente — {exp.get('concept', '')}",
                    exp.get("id", ""), interval, months, today, end_date=end_date
                )

        # ── Contratos ──
        if include_contracts:
            contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox) or []
            for contract in contracts:
                if contract.get("status") != "Activo":
                    continue
                next_billing = contract.get("nextBillingDate", "")
                if not next_billing:
                    continue
                next_date = cls._parse_date(next_billing)
                amount = float(contract.get("amount", 0.0))
                freq = contract.get("frequency") or contract.get("recurrenceInterval", "mensual")
                cls._add_recurring_items(
                    projections, next_date, amount, "inflow", "contract",
                    f"Contrato {contract.get('contractNumber', '')} — {contract.get('clientName', '')}",
                    contract.get("id", ""), freq, months, today
                )

        # ── Calcular netos y acumulados ──
        sorted_keys = sorted(projections.keys())
        result = []
        cumulative = current_balance

        for k in sorted_keys:
            p = projections[k]
            p.net = round(p.inflow - p.outflow, 2)
            cumulative += p.net
            p.cumulative = round(cumulative, 2)
            # Ordenar items por fecha
            p.items.sort(key=lambda x: x["date"])
            result.append(p)

        return result

    @classmethod
    def _add_recurring_items(
        cls,
        projections: dict,
        start_date: date,
        amount: float,
        item_type: str,
        source: str,
        description: str,
        reference_id: str,
        interval: str,
        max_months: int,
        today: date,
        end_date: Optional[date] = None,
    ):
        """Añade ítems recurrentes a los meses de proyección."""
        from app.services.recurrence import RecurrenceService

        current_date = start_date
        # Generar ocurrencias mientras estén dentro del rango de proyección
        last_proj_month = today.replace(day=1)
        m = last_proj_month.month - 1 + max_months
        y = last_proj_month.year + m // 12
        m = m % 12 + 1
        max_date = date(y, m, calendar.monthrange(y, m)[1])

        count = 0
        max_occurrences = 24  # Safety limit
        while current_date <= max_date and count < max_occurrences:
            if end_date and current_date > end_date:
                break
            key = f"{current_date.year}-{current_date.month:02d}"
            if key in projections:
                item = {
                    "date": current_date.isoformat(),
                    "description": description,
                    "amount": amount,
                    "type": item_type,
                    "source": source,
                    "reference_id": reference_id,
                    "certainty": "medium",
                }
                if item_type == "inflow":
                    projections[key].inflow += amount
                else:
                    projections[key].outflow += amount
                projections[key].items.append(item)

            # Calcular próxima ocurrencia
            current_date_str = current_date.strftime("%Y-%m-%d")
            next_str = RecurrenceService.calculate_next_date(current_date_str, interval)
            current_date = cls._parse_date(next_str)
            count += 1

    @classmethod
    def get_deficit_alerts(cls, projections: list[MonthProjection]) -> list[DeficitAlert]:
        """Analiza proyecciones y genera alertas de déficit."""
        alerts = []
        consecutive_negative = 0

        for p in projections:
            if p.cumulative < 0:
                consecutive_negative += 1
                severity = "warning"
                if consecutive_negative >= 3:
                    severity = "critical"
                elif consecutive_negative >= 2:
                    severity = "danger"
                alerts.append(DeficitAlert(
                    month_label=p.label,
                    month_key=p.key,
                    projected_balance=p.cumulative,
                    severity=severity,
                ))
            else:
                consecutive_negative = 0

        return alerts

    @classmethod
    def get_weekly_forecast(cls, owner_uid: str, weeks: int = 12, sandbox: bool = True,
                            invoices: Optional[list] = None, expenses: Optional[list] = None) -> list[dict]:
        """
        Proyección semanal de flujo de caja.

        Args:
            owner_uid: UID del propietario.
            weeks: Número de semanas a proyectar.
            sandbox: Entorno.
            invoices: Lista de facturas pre-fetched (opcional).
            expenses: Lista de gastos pre-fetched (opcional).

        Returns:
            Lista de dicts con week_start, week_label, inflow, outflow, net, balance.
        """
        today = date.today()
        # Alinear al lunes
        monday = today - timedelta(days=today.weekday())
        current_balance = cls.get_current_liquidity(owner_uid, sandbox=sandbox)

        # Inicializar semanas
        weeks_data = []
        for i in range(weeks):
            ws = monday + timedelta(weeks=i)
            we = ws + timedelta(days=6)
            weeks_data.append({
                "week_start": ws.isoformat(),
                "week_end": we.isoformat(),
                "week_label": f"{ws.day}/{ws.month} — {we.day}/{we.month}",
                "inflow": 0.0,
                "outflow": 0.0,
            })

        # ── CxC ──
        invoices = invoices if invoices is not None else (DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or [])
        for inv in invoices:
            if inv.get("isQuotation") or inv.get("status") in ("Anulada", "Borrador", "Pagado", "Consolidada"):
                continue
            remaining = float(inv.get("remainingBalance", 0.0))
            if remaining <= 0:
                continue
            due_date = cls._parse_date(inv.get("dueDate", ""))
            for w in weeks_data:
                ws = cls._parse_date(w["week_start"])
                we = cls._parse_date(w["week_end"])
                if ws <= due_date <= we:
                    w["inflow"] += remaining
                    break

        # ── CxP ──
        expenses = expenses if expenses is not None else (DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or [])
        for exp in expenses:
            if exp.get("approvalStatus") == "Rechazado":
                continue
            if exp.get("paymentType") != "Crédito":
                continue
            if exp.get("cxpStatus") == "Pagado":
                continue
            remaining = float(exp.get("cxpRemainingBalance", 0.0))
            if remaining <= 0:
                continue
            due_date = cls._parse_date(exp.get("dueDate", "") or exp.get("date", ""))
            for w in weeks_data:
                ws = cls._parse_date(w["week_start"])
                we = cls._parse_date(w["week_end"])
                if ws <= due_date <= we:
                    w["outflow"] += remaining
                    break

        # Calcular netos y balances
        balance = current_balance
        for w in weeks_data:
            w["net"] = round(w["inflow"] - w["outflow"], 2)
            balance += w["net"]
            w["balance"] = round(balance, 2)

        return weeks_data

    @staticmethod
    def _month_label(year: int, month: int) -> str:
        """Retorna nombre del mes capitalizado en español."""
        names = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
        ]
        return f"{names[month - 1]} {year}"
