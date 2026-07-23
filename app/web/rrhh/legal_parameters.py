"""RRHH module — Parámetros Legales con vigencia histórica (TSS, ISR, topes salariales, límites)."""

from datetime import date, datetime, timezone

from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
)
from app.services import hr_data_service as hr
from app.models.legal_parameter import PARAM_TYPES, get_default_params

PARAM_TYPE_LABELS = {
    "afp_employee_rate": "Tasa AFP Empleado",
    "afp_employer_rate": "Tasa AFP Empleador",
    "sfs_employee_rate": "Tasa SFS Empleado",
    "sfs_employer_rate": "Tasa SFS Empleador",
    "srl_employer_rate": "Tasa SRL Empleador",
    "infotep_rate": "Tasa INFOTEP",
    "afp_salary_cap": "Tope AFP (RD$ mensual)",
    "sfs_salary_cap": "Tope SFS (RD$ mensual)",
    "min_salary": "Salario Mínimo Nacional (RD$)",
    "education_deduction": "Deducción Max. Educación (RD$ anual)",
    "overtime_rate": "Multiplicador Hora Extra",
    "working_days_per_month": "Días Laborables / Mes",
    "working_hours_per_day": "Horas Laborables / Día",
    "infotep_threshold_multiplier": "Multiplicador Umbral INFOTEP",
    "deduction_max_pct": "% Máximo Total Deducciones",
    "protected_income_pct": "% Protegido del Salario",
    "pension_max_pct": "% Máximo Pensión Alimenticia",
    "judicial_max_pct": "% Máximo Embargo Judicial",
    "loan_max_pct": "% Máximo Préstamo",
    "cooperative_max_pct": "% Máximo Cooperativa",
    "isr_annual_table": "Tabla ISR Anual",
}


@web_rrhh_bp.route("/rrhh/legal-parameters")
def legal_parameters_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    param_type = request.args.get("parameter_type", "")
    parameters = hr.get_legal_parameters(company_id, parameter_type=param_type, sandbox=sandbox)

    # Agrupar por tipo para vista compacta
    from collections import defaultdict
    grouped = defaultdict(list)
    for p in parameters:
        grouped[p.get("parameterType", "")].append(p)

    param_types = list(PARAM_TYPES.keys())

    # Obtener defaults para mostrar parámetros no configurados
    defaults = get_default_params() if not param_type or param_type == "" else {}

    return render_template(
        "rrhh/legal_parameters/list.html",
        active_page="rrhh_legal_params",
        parameters=parameters,
        grouped=dict(grouped),
        param_types=param_types,
        PARAM_TYPE_LABELS=PARAM_TYPE_LABELS,
        selected_type=param_type,
        default_params=defaults,
    )


@web_rrhh_bp.route("/rrhh/legal-parameters/new", methods=["GET", "POST"])
def legal_parameter_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    if request.method == "POST":
        param_type = request.form.get("parameterType", "")
        if param_type not in PARAM_TYPES:
            flash("Tipo de parámetro inválido.", "error")
            return redirect(url_for("web_rrhh.legal_parameter_new"))

        value = _parse_param_value(param_type, request.form.get("value", ""), form=request.form)
        effective_from = request.form.get("effectiveFrom", "")
        effective_to = request.form.get("effectiveTo", "") or ""

        from app.services.legal_parameter_resolver import set_parameter
        user_email = session.get("user", {}).get("email", "")
        new_id = set_parameter(
            company_id=company_id,
            parameter_type=param_type,
            value=value,
            effective_from=effective_from,
            effective_to=effective_to,
            user_email=user_email,
            notes=request.form.get("notes", ""),
            sandbox=sandbox,
        )

        if new_id:
            flash("Parámetro legal creado exitosamente.", "success")
        else:
            flash("Error al crear el parámetro legal.", "error")

        return redirect(url_for("web_rrhh.legal_parameters_list"))

    return render_template(
        "rrhh/legal_parameters/form.html",
        active_page="rrhh_legal_params",
        parameter=None,
        param_types=PARAM_TYPES,
        PARAM_TYPE_LABELS=PARAM_TYPE_LABELS,
        INFINITY=float('inf'),
        display_value="",
    )


@web_rrhh_bp.route("/rrhh/legal-parameters/<param_id>/edit", methods=["GET", "POST"])
def legal_parameter_edit(param_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    parameter = hr.get_legal_parameter(company_id, param_id, sandbox=sandbox)
    if not parameter:
        flash("Parámetro no encontrado.", "error")
        return redirect(url_for("web_rrhh.legal_parameters_list"))

    if request.method == "POST":
        param_type = parameter.get("parameterType", "")
        parameter["value"] = _parse_param_value(param_type, request.form.get("value", ""), form=request.form)
        parameter["effectiveFrom"] = request.form.get("effectiveFrom", parameter.get("effectiveFrom", ""))
        parameter["effectiveTo"] = request.form.get("effectiveTo", parameter.get("effectiveTo", ""))
        parameter["notes"] = request.form.get("notes", parameter.get("notes", ""))
        parameter["updatedBy"] = session.get("user", {}).get("email", "")
        parameter["updatedAt"] = datetime.now(timezone.utc).isoformat()

        hr.save_legal_parameter(company_id, param_id, parameter, sandbox=sandbox)
        flash("Parámetro legal actualizado.", "success")
        return redirect(url_for("web_rrhh.legal_parameters_list"))

    display_value = ""
    if parameter and parameter.get("value") is not None:
        v = parameter["value"]
        if not isinstance(v, (dict, list, tuple)):
            display_value = str(v)

    return render_template(
        "rrhh/legal_parameters/form.html",
        active_page="rrhh_legal_params",
        parameter=parameter,
        param_types=PARAM_TYPES,
        PARAM_TYPE_LABELS=PARAM_TYPE_LABELS,
        INFINITY=float('inf'),
        display_value=display_value,
    )


@web_rrhh_bp.route("/rrhh/legal-parameters/<param_id>/history")
def legal_parameter_history(param_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    parameter = hr.get_legal_parameter(company_id, param_id, sandbox=sandbox)
    if not parameter:
        flash("Parámetro no encontrado.", "error")
        return redirect(url_for("web_rrhh.legal_parameters_list"))

    from app.services.legal_parameter_resolver import get_parameter_history
    history = get_parameter_history(
        owner_uid,
        parameter.get("parameterType", ""),
        sandbox=sandbox,
    )

    return render_template(
        "rrhh/legal_parameters/history.html",
        active_page="rrhh_legal_params",
        parameter=parameter,
        history=history,
        PARAM_TYPE_LABELS=PARAM_TYPE_LABELS,
    )


@web_rrhh_bp.route("/rrhh/legal-parameters/<param_id>/delete", methods=["POST"])
def legal_parameter_delete(param_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    parameter = hr.get_legal_parameter(company_id, param_id, sandbox=sandbox)
    if not parameter:
        flash("Parámetro no encontrado.", "error")
        return redirect(url_for("web_rrhh.legal_parameters_list"))

    # Marcar como inactivo en lugar de eliminar (para mantener historial)
    parameter["isActive"] = False
    parameter["updatedBy"] = session.get("user", {}).get("email", "")
    parameter["updatedAt"] = datetime.now(timezone.utc).isoformat()
    hr.save_legal_parameter(company_id, param_id, parameter, sandbox=sandbox)

    flash("Parámetro legal desactivado.", "success")
    return redirect(url_for("web_rrhh.legal_parameters_list"))


def _parse_param_value(param_type: str, raw_value: str, form=None):
    param_info = PARAM_TYPES.get(param_type, {})
    ptype = param_info.get("type", str)

    if param_type == "isr_annual_table":
        return _parse_isr_table(form or request.form)

    if ptype == float:
        return float(raw_value or 0)
    elif ptype == int:
        return int(raw_value or 0)
    return raw_value


def _parse_isr_table(form) -> list:
    table = []
    i = 0
    while True:
        desde_key = f"isr_from_{i}"
        if not form or not form.get(desde_key):
            break
        desde = float(form.get(desde_key, 0) or 0)
        hasta_raw = form.get(f"isr_to_{i}", "0")
        tasa = float(form.get(f"isr_rate_{i}", 0) or 0) / 100.0
        deduction = float(form.get(f"isr_fixed_{i}", 0) or 0)
        if hasta_raw in ("999999999", "inf", ""):
            hasta = 999999999.0
        else:
            hasta = float(hasta_raw or 0)
        table.append([desde, hasta, tasa, deduction])
        i += 1
    if not table:
        return []
    return table