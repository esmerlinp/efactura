"""RRHH module — Configuración de nómina (solo cuentas contables y centros de costo).

Las tasas, topes y tabla ISR ahora se gestionan en /rrhh/legal-parameters
con vigencia histórica y versionado.
"""

from datetime import date
from flask import render_template, request, redirect, url_for, session, flash
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService
from types import SimpleNamespace


def _parse_cost_center_accounts(form) -> dict:
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

    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    config_updated = False

    if request.method == "POST":
        action = request.form.get("action", "save")

        new_freq = request.form.get("payroll_frequency", "")
        if new_freq in ("quincenal", "mensual"):
            config["payrollFrequency"] = new_freq
            hr.save_payroll_config(owner_uid, config, sandbox=sandbox)

        if action == "save":
            hr.save_tax_rates(owner_uid, {
                "year": date.today().year,
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
        default_rates = PayrollService.get_rates({})
        rates = {
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

    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)

    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))
    all_employees = hr.get_employees(owner_uid, sandbox=sandbox)
    unassigned_employees = [e for e in all_employees if e.get("status") == "activo"
                            and not any(gid in e.get("payrollGroupIds", []) for gid in [g["id"] for g in payroll_groups])]

    return render_template("rrhh/settings.html", active_page="rrhh_settings",
                           tax_rates=SimpleNamespace(**rates), config_updated=config_updated,
                           payroll_frequency=config.get("payrollFrequency", "mensual"),
                           payroll_groups=payroll_groups,
                           unassigned_employees=unassigned_employees,
                           group_employee_counts={g["id"]: len([e for e in all_employees if g["id"] in e.get("payrollGroupIds", [])]) for g in payroll_groups},
                           )


@web_rrhh_bp.route("/rrhh/payroll/settings/tax-history")
def tax_rates_history_view():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    from app.services.legal_parameter_resolver import get_parameter_history
    from app.models.legal_parameter import PARAM_TYPES, get_default_params

    params = get_default_params()
    return render_template("rrhh/settings_tax_history.html", active_page="rrhh_settings",
                           history=[], current=params)


@web_rrhh_bp.route("/rrhh/payroll/fiscal-closing-validation")
def fiscal_closing_validation():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    year = int(request.args.get("year", date.today().year))
    result = PayrollService.validate_payroll_for_fiscal_closing(owner_uid, year=year, sandbox=sandbox)

    return render_template("rrhh/fiscal_closing_validation.html", active_page="rrhh_reports",
                           result=result, year=year)


@web_rrhh_bp.route("/rrhh/payroll/generate-periods", methods=["POST"])
def payroll_generate_periods():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    months = int(request.form.get("months", 6))
    result = PayrollService.generate_upcoming_periods(owner_uid, months_ahead=months, sandbox=sandbox)

    if result["errors"]:
        for err in result["errors"]:
            flash(err, "error")
    else:
        flash(f"Se generaron {result['created']} períodos nuevos ({result['skipped']} ya existían).", "success")
    return redirect(url_for("web_rrhh.payroll_settings"))