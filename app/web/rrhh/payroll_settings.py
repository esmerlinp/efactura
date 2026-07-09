"""RRHH module — auto-extracted."""

from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService
from types import SimpleNamespace


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

def _parse_cost_center_accounts(form) -> dict:
    """Parsea las cuentas de centro de costo desde el formulario."""
    accounts = {}
    i = 0
    while True:
        name_key = f"cc_name_{i}"
        code_key = f"cc_code_{i}"
        name = form.get(name_key, "").strip()
        code = form.get(code_key, "").strip()
        if not name or not code:
            break
        accounts[name] = code
        i += 1
    if not accounts:
        accounts = {
            "General": "6.2.1.01",
            "Ventas": "6.2.1.01.01",
            "Produccion": "6.2.1.01.02",
            "Administrativa": "6.2.1.01.03",
        }
    return accounts


@web_rrhh_bp.route("/rrhh/payroll/settings", methods=["GET", "POST"])
def payroll_settings():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    rates = hr.get_tax_rates(owner_uid, sandbox=sandbox)
    default_rates = PayrollService.get_rates({})
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    config_updated = False

    if request.method == "POST":
        action = request.form.get("action", "save")

        # ── Guardar frecuencia por defecto (solo se usa como fallback) ──
        new_freq = request.form.get("payroll_frequency", "")
        if new_freq in ("quincenal", "mensual"):
            config["payrollFrequency"] = new_freq
            hr.save_payroll_config(owner_uid, config, sandbox=sandbox)

        if action == "reset":
            hr.save_tax_rates(owner_uid, {
                "year": date.today().year,
                "afpEmployeeRate": default_rates["afp_employee_rate"],
                "afpEmployerRate": default_rates["afp_employer_rate"],
                "sfsEmployeeRate": default_rates["sfs_employee_rate"],
                "sfsEmployerRate": default_rates["sfs_employer_rate"],
                "srlEmployerRate": default_rates["srl_employer_rate"],
                "infotepRate": default_rates["infotep_rate"],
                "afpSalaryCap": default_rates["afp_salary_cap"],
                "sfsSalaryCap": default_rates["sfs_salary_cap"],
                "minSalary": default_rates["min_salary"],
                "educationDeduction": default_rates["education_deduction"],
                "isrAnnualTable": default_rates["isr_table"],
                "overtimeRate": default_rates["overtime_rate"],
                "workingDaysPerMonth": default_rates["working_days_per_month"],
                "workingHoursPerDay": default_rates["working_hours_per_day"],
                "infotepThresholdMultiplier": default_rates["infotep_threshold_multiplier"],
                "accountSalariesPayable": default_rates["account_salaries_payable"],
                "accountAfpEmployee": default_rates["account_afp_employee"],
                "accountSfsEmployee": default_rates["account_sfs_employee"],
                "accountIsrEmployee": default_rates["account_isr_employee"],
                "accountAfpEmployer": default_rates["account_afp_employer"],
                "accountSfsEmployer": default_rates["account_sfs_employer"],
                "accountSrlEmployer": default_rates["account_srl_employer"],
                "accountInfotepEmployer": default_rates["account_infotep_employer"],
                "costCenterAccounts": default_rates["cost_center_accounts"],
                "updatedBy": session.get("user", {}).get("email", ""),
            }, sandbox=sandbox)
        else:
            isr_table = []
            i = 0
            while True:
                desde_key = f"isr_from_{i}"
                if not request.form.get(desde_key):
                    break
                desde = float(request.form.get(desde_key, 0) or 0)
                hasta_raw = request.form.get(f"isr_to_{i}", "0")
                tasa = float(request.form.get(f"isr_rate_{i}", 0) or 0) / 100.0
                fija = float(request.form.get(f"isr_fixed_{i}", 0) or 0)
                # Ultima fila: el "hasta" puede venir como hidden "999999999" o como "inf"
                if hasta_raw in ("999999999", "inf", ""):
                    hasta = float("inf")
                else:
                    hasta = float(hasta_raw or 0)
                isr_table.append([desde, hasta, tasa, fija])
                i += 1
            hr.save_tax_rates(owner_uid, {
                "year": date.today().year,
                "afpEmployeeRate": float(request.form.get("afpEmployeeRate", 0) or 0) / 100.0,
                "afpEmployerRate": float(request.form.get("afpEmployerRate", 0) or 0) / 100.0,
                "sfsEmployeeRate": float(request.form.get("sfsEmployeeRate", 0) or 0) / 100.0,
                "sfsEmployerRate": float(request.form.get("sfsEmployerRate", 0) or 0) / 100.0,
                "srlEmployerRate": float(request.form.get("srlEmployerRate", 0) or 0) / 100.0,
                "infotepRate": float(request.form.get("infotepRate", 0) or 0) / 100.0,
                "afpSalaryCap": float(request.form.get("afpSalaryCap", 0) or 0),
                "sfsSalaryCap": float(request.form.get("sfsSalaryCap", 0) or 0),
                "minSalary": float(request.form.get("minSalary", 0) or 0),
                "educationDeduction": float(request.form.get("educationDeduction", 0) or 0),
                "isrAnnualTable": isr_table,
                "overtimeRate": float(request.form.get("overtimeRate", 135) or 135) / 100.0,
                "workingDaysPerMonth": float(request.form.get("workingDaysPerMonth", 23.83) or 23.83),
                "workingHoursPerDay": float(request.form.get("workingHoursPerDay", 8) or 8),
                "infotepThresholdMultiplier": float(request.form.get("infotepThresholdMultiplier", 5) or 5),
                "accountSalariesPayable": request.form.get("accountSalariesPayable", "2.1.2.1.02").strip(),
                "accountAfpEmployee": request.form.get("accountAfpEmployee", "2.1.2.1.05").strip(),
                "accountSfsEmployee": request.form.get("accountSfsEmployee", "2.1.2.1.06").strip(),
                "accountIsrEmployee": request.form.get("accountIsrEmployee", "2.1.2.1.08").strip(),
                "accountAfpEmployer": request.form.get("accountAfpEmployer", "2.1.2.1.10").strip(),
                "accountSfsEmployer": request.form.get("accountSfsEmployer", "2.1.2.1.09").strip(),
                "accountSrlEmployer": request.form.get("accountSrlEmployer", "2.1.2.1.11").strip(),
                "accountInfotepEmployer": request.form.get("accountInfotepEmployer", "2.1.2.1.12").strip(),
                "costCenterAccounts": _parse_cost_center_accounts(request.form),
                "updatedBy": session.get("user", {}).get("email", ""),
            }, sandbox=sandbox)
        config_updated = True
        rates = hr.get_tax_rates(owner_uid, sandbox=sandbox)

    if not rates:
        rates = {
            "year": date.today().year,
            "afpEmployeeRate": default_rates["afp_employee_rate"],
            "afpEmployerRate": default_rates["afp_employer_rate"],
            "sfsEmployeeRate": default_rates["sfs_employee_rate"],
            "sfsEmployerRate": default_rates["sfs_employer_rate"],
            "srlEmployerRate": default_rates["srl_employer_rate"],
            "infotepRate": default_rates["infotep_rate"],
            "afpSalaryCap": default_rates["afp_salary_cap"],
            "sfsSalaryCap": default_rates["sfs_salary_cap"],
            "minSalary": default_rates["min_salary"],
            "educationDeduction": default_rates["education_deduction"],
            "isrAnnualTable": default_rates["isr_table"],
            "overtimeRate": default_rates["overtime_rate"],
            "workingDaysPerMonth": default_rates["working_days_per_month"],
            "workingHoursPerDay": default_rates["working_hours_per_day"],
            "infotepThresholdMultiplier": default_rates["infotep_threshold_multiplier"],
            "accountSalariesPayable": default_rates["account_salaries_payable"],
            "accountAfpEmployee": default_rates["account_afp_employee"],
            "accountSfsEmployee": default_rates["account_sfs_employee"],
            "accountIsrEmployee": default_rates["account_isr_employee"],
            "accountAfpEmployer": default_rates["account_afp_employer"],
            "accountSfsEmployer": default_rates["account_sfs_employer"],
            "accountSrlEmployer": default_rates["account_srl_employer"],
            "accountInfotepEmployer": default_rates["account_infotep_employer"],
            "costCenterAccounts": default_rates["cost_center_accounts"],
            "updatedAt": "",
            "updatedBy": "",
        }

    # Recargar config después de posibles cambios
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    # Asegurar que todos los campos tengan valores por defecto
    rates.setdefault("overtimeRate", default_rates["overtime_rate"])
    rates.setdefault("workingDaysPerMonth", default_rates["working_days_per_month"])
    rates.setdefault("workingHoursPerDay", default_rates["working_hours_per_day"])
    rates.setdefault("infotepThresholdMultiplier", default_rates["infotep_threshold_multiplier"])
    rates.setdefault("accountSalariesPayable", default_rates["account_salaries_payable"])
    rates.setdefault("accountAfpEmployee", default_rates["account_afp_employee"])
    rates.setdefault("accountSfsEmployee", default_rates["account_sfs_employee"])
    rates.setdefault("accountIsrEmployee", default_rates["account_isr_employee"])
    rates.setdefault("accountAfpEmployer", default_rates["account_afp_employer"])
    rates.setdefault("accountSfsEmployer", default_rates["account_sfs_employer"])
    rates.setdefault("accountSrlEmployer", default_rates["account_srl_employer"])
    rates.setdefault("accountInfotepEmployer", default_rates["account_infotep_employer"])
    rates.setdefault("costCenterAccounts", default_rates["cost_center_accounts"])
    from types import SimpleNamespace
    # ── Grupos de nómina para integrar en settings ──
    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))
    all_employees = hr.get_employees(owner_uid, sandbox=sandbox)
    assigned_group_ids = set()
    for emp in all_employees:
        for gid in emp.get("payrollGroupIds", []):
            assigned_group_ids.add(gid)
    unassigned_employees = [e for e in all_employees if e.get("status") == "activo"
                            and not any(gid in e.get("payrollGroupIds", []) for gid in [g["id"] for g in payroll_groups])]
    return render_template("rrhh/settings.html", active_page="rrhh_settings",
                           tax_rates=SimpleNamespace(**rates), config_updated=config_updated,
                           payroll_frequency=config.get("payrollFrequency", "mensual"),
                           payroll_groups=payroll_groups,
                           unassigned_employees=unassigned_employees,
                            group_employee_counts={g["id"]: len([e for e in all_employees if g["id"] in e.get("payrollGroupIds", [])]) for g in payroll_groups})


# ═══════════════════════════════════════════════════════════════════════════
# HISTORIAL DE TASAS IMPOSITIVAS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/settings/tax-history")
def tax_rates_history_view():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    history = hr.get_tax_rates_history(owner_uid, sandbox=sandbox)
    current = hr.get_tax_rates(owner_uid, sandbox=sandbox)

    return render_template("rrhh/settings_tax_history.html", active_page="rrhh_settings",
                           history=history, current=current)


# ═══════════════════════════════════════════════════════════════════════════
# VALIDACIÓN PRE-CIERRE FISCAL
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/fiscal-closing-validation")
def fiscal_closing_validation():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_service import PayrollService
    from datetime import date

    year = int(request.args.get("year", date.today().year))
    result = PayrollService.validate_payroll_for_fiscal_closing(owner_uid, year=year, sandbox=sandbox)

    return render_template("rrhh/fiscal_closing_validation.html", active_page="rrhh_reports",
                           result=result, year=year)


# ═══════════════════════════════════════════════════════════════════════════
# AUTO-GENERACIÓN DE PERÍODOS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/generate-periods", methods=["POST"])
def payroll_generate_periods():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services.payroll_service import PayrollService

    months = int(request.form.get("months", 6))
    result = PayrollService.generate_upcoming_periods(owner_uid, months_ahead=months, sandbox=sandbox)

    if result["errors"]:
        for err in result["errors"]:
            flash(err, "error")
    else:
        flash(f"Se generaron {result['created']} períodos nuevos ({result['skipped']} ya existían).", "success")
    return redirect(url_for("web_rrhh.payroll_settings"))


