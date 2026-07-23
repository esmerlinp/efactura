"""Blueprint de RRHH: empleados, asistencia, vacaciones, permisos, nómina, evaluaciones, capacitaciones."""

import io
import os
import csv
import json
import uuid
import calendar
import re
import html
import threading
from datetime import datetime, timezone, date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file, current_app

web_rrhh_bp = Blueprint("web_rrhh", __name__, template_folder="templates")


def _get_owner_uid_and_sandbox():
    uid = session.get("selected_owner_uid", "") or session.get("user", {}).get("ownerUID", "")
    sandbox = session.get("is_sandbox_mode", True)
    company_id = session.get("selected_company_id")
    return uid, sandbox, company_id


def _login_required():
    return "user" not in session


def _is_hr_role():
    user = session.get("user", {})
    role = user.get("role", "")
    perms = user.get("permissions", {})
    return role == "owner" or perms.get("canHR", True)


def _sanitize_for_role(employee: dict) -> dict:
    if _is_hr_role():
        return employee
    safe = dict(employee)
    for field in ("baseSalary", "salary", "hourlyRate", "accountNumber", "bank", "accountType",
                  "salaryType", "afpProvider", "afpSalaryCap", "sfsSalaryCap", "tssRegistrationNumber"):
        if field in safe:
            safe[field] = "***"
    return safe


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: Generar períodos disponibles según frecuencia
# ═══════════════════════════════════════════════════════════════════════════

MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _filter_employees_by_period(employees, period_key=None, frequency_mode=None):
    """Compatibilidad: ahora todos los empleados del grupo se incluyen sin filtrar."""
    return list(employees), []


def _generate_periods(frequency: str, year: int = None):
    """Genera lista de períodos disponibles para el año."""
    if year is None:
        year = date.today().year
    periods = []
    if frequency in ("quincenal", "ambos", "quincenal_y_mensual"):
        for m in range(1, 13):
            last_day = calendar.monthrange(year, m)[1]
            mid = 15
            label_m = MONTHS_ES[m - 1]
            periods.append({
                "key": f"{year}-{m:02d}-1",
                "label": f"Q1: 1 {label_m} - 15 {label_m}",
                "start": f"{year}-{m:02d}-01",
                "end": f"{year}-{m:02d}-{mid}",
                "type": "quincenal",
            })
            periods.append({
                "key": f"{year}-{m:02d}-2",
                "label": f"Q2: 16 {label_m} - {last_day} {label_m}",
                "start": f"{year}-{m:02d}-16",
                "end": f"{year}-{m:02d}-{last_day}",
                "type": "quincenal",
            })
    if frequency in ("mensual", "ambos", "quincenal_y_mensual"):
        for m in range(1, 13):
            label_m = MONTHS_ES[m - 1]
            last_day = calendar.monthrange(year, m)[1]
            periods.append({
                "key": f"{year}-{m:02d}-M",
                "label": f"M: {label_m} {year}",
                "start": f"{year}-{m:02d}-01",
                "end": f"{year}-{m:02d}-{last_day}",
                "type": "mensual",
            })
    return periods


# ── Import all module files so their @routes are registered on the Blueprint ──
from app.web.rrhh import onboarding          # noqa: E402, F401
from app.web.rrhh import dashboard           # noqa: E402, F401
from app.web.rrhh import employees           # noqa: E402, F401
from app.web.rrhh import payslip             # noqa: E402, F401
from app.web.rrhh import termination         # noqa: E402, F401
from app.web.rrhh import liquidacion         # noqa: E402, F401
from app.web.rrhh import employees_export    # noqa: E402, F401
from app.web.rrhh import employee_import     # noqa: E402, F401
from app.web.rrhh import salary_history      # noqa: E402, F401
from app.web.rrhh import documents           # noqa: E402, F401
from app.web.rrhh import checklist           # noqa: E402, F401
from app.web.rrhh import org_chart           # noqa: E402, F401
from app.web.rrhh import attendance          # noqa: E402, F401
from app.web.rrhh import vacations           # noqa: E402, F401
from app.web.rrhh import leaves              # noqa: E402, F401
from app.web.rrhh import payroll_process     # noqa: E402, F401
from app.web.rrhh import payroll_groups      # noqa: E402, F401
from app.web.rrhh import payroll_history     # noqa: E402, F401
from app.web.rrhh import positions
from app.web.rrhh import departments            # noqa: E402, F401
from app.web.rrhh import concepts            # noqa: E402, F401
from app.web.rrhh import portal              # noqa: E402, F401
from app.web.rrhh import audit               # noqa: E402, F401
from app.web.rrhh import payroll_settings    # noqa: E402, F401
from app.web.rrhh import reports             # noqa: E402, F401
from app.web.rrhh import dependents          # noqa: E402, F401
from app.web.rrhh import payroll_workflow    # noqa: E402, F401
from app.web.rrhh import evaluations         # noqa: E402, F401
from app.web.rrhh import trainings           # noqa: E402, F401
from app.web.rrhh import mass_actions        # noqa: E402, F401
from app.web.rrhh import payroll_rules       # noqa: E402, F401
from app.web.rrhh import payroll_calendar    # noqa: E402, F401
from app.web.rrhh import dgt as _dgt         # noqa: E402, F401
from app.web.rrhh import recurring           # noqa: E402, F401
from app.web.rrhh import legal_parameters    # noqa: E402, F401
from app.web.rrhh import overtime            # noqa: E402, F401
from app.web.rrhh import work_certificate    # noqa: E402, F401
from app.web.rrhh import offboarding         # noqa: E402, F401
