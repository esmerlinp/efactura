"""Payroll Calendar — Vista de calendario anual con todos los períodos de nómina."""

import calendar
from datetime import date
from flask import render_template, request, redirect, url_for, session

from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    MONTHS_ES,
)


def _get_dominican_holidays(year: int) -> list:
    """Retorna lista de feriados dominicanos para un año."""
    holidays = [
        (f"{year}-01-01", "Año Nuevo"),
        (f"{year}-01-06", "Día de Reyes"),
        (f"{year}-01-21", "Día de la Altagracia"),
        (f"{year}-01-26", "Día de Duarte"),
        (f"{year}-02-27", "Independencia Nacional"),
        (f"{year}-05-01", "Día del Trabajo"),
        (f"{year}-08-16", "Restauración"),
        (f"{year}-09-24", "Día de las Mercedes"),
        (f"{year}-11-06", "Constitución"),
        (f"{year}-12-25", "Navidad"),
    ]
    return holidays


def _format_period_label(period: dict) -> str:
    r = period.get("periodRange", "")
    if r:
        return r[:30]
    return period.get("periodKey", "")


STATUS_COLORS = {
    "borrador": "#94a3b8",
    "calculada": "#3b82f6",
    "validada": "#8b5cf6",
    "aprobada": "#f59e0b",
    "contabilizada": "#06b6d4",
    "pagada": "#10b981",
    "cerrada": "#6b7280",
}

STATUS_LABELS = {
    "borrador": "Borrador",
    "calculada": "Calculada",
    "validada": "Validada",
    "aprobada": "Aprobada",
    "contabilizada": "Contabilizada",
    "pagada": "Pagada",
    "cerrada": "Cerrada",
}


@web_rrhh_bp.route("/rrhh/payroll/calendar")
def payroll_calendar_view():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    now = date.today()
    year = int(request.args.get("year", now.year))

    periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
    year_periods = [p for p in periods if p.get("year") == year]
    groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    group_map = {g["id"]: g for g in groups}

    holidays = _get_dominican_holidays(year)
    holiday_dates = {h[0]: h[1] for h in holidays}

    months_data = []
    for m in range(1, 13):
        month_name = MONTHS_ES[m - 1]
        month_periods = [p for p in year_periods if p.get("month") == m]
        days_in_month = calendar.monthrange(year, m)[1]

        weeks = []
        cal = calendar.Calendar(firstweekday=6)
        for week in cal.monthdatescalendar(year, m):
            week_data = []
            for d in week:
                date_str = d.isoformat()
                day_periods = []
                for p in month_periods:
                    p_start = p.get("startDate", "")
                    p_end = p.get("endDate", "")
                    if p_start <= date_str <= p_end:
                        group = group_map.get(p.get("payrollGroupId", ""), {})
                        day_periods.append({
                            "id": p.get("id", ""),
                            "key": p.get("periodKey", ""),
                            "label": _format_period_label(p),
                            "status": p.get("status", ""),
                            "statusLabel": STATUS_LABELS.get(p.get("status", ""), ""),
                            "statusColor": STATUS_COLORS.get(p.get("status", ""), "#94a3b8"),
                            "groupName": group.get("name", ""),
                            "totalNet": p.get("totalNet", 0),
                        })

                week_data.append({
                    "date": date_str,
                    "day": d.day,
                    "isCurrentMonth": d.month == m,
                    "isWeekend": d.weekday() >= 5,
                    "isToday": date_str == now.isoformat(),
                    "isHoliday": date_str in holiday_dates,
                    "holidayName": holiday_dates.get(date_str, ""),
                    "periods": day_periods,
                })
            weeks.append(week_data)

        months_data.append({
            "month": m,
            "name": month_name,
            "nameFull": f"{month_name} {year}",
            "weeks": weeks,
            "periodCount": len(month_periods),
            "totalNet": round(sum(p.get("totalNet", 0) for p in month_periods), 2),
        })

    years_available = sorted(set(p.get("year", now.year) for p in periods if p.get("year")))
    if year not in years_available:
        years_available.append(year)
    years_available.sort()

    return render_template("rrhh/payroll_calendar.html", active_page="rrhh_payroll",
                           months_data=months_data, year=year,
                           years_available=years_available,
                           status_labels=STATUS_LABELS, status_colors=STATUS_COLORS,
                           group_map={g["id"]: g["name"] for g in groups})
