"""RRHH module — auto-extracted."""

from datetime import datetime, timezone
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


# ═══════════════════════════════════════════════════════════════════════════
# ONBOARDING — Frecuencia de pago
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/onboarding")
def onboarding_guide():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    config = hr.get_payroll_config(company_id, sandbox=sandbox)
    employees = hr.get_employees(company_id, sandbox=sandbox)
    periods = hr.get_payroll_periods(company_id, sandbox=sandbox)
    positions = hr.get_catalog(company_id, "positions", sandbox=sandbox)
    departments = hr.get_catalog(company_id, "departments", sandbox=sandbox)

    step1_done = bool(config.get("payrollFrequency"))
    step2_done = len(positions) > 0 and len(departments) > 0
    step3_done = len([e for e in employees if e.get("status") == "activo"]) > 0
    step4_done = True  # Concepts have defaults, always seeded
    step5_done = len(periods) > 0

    steps = [
        {"number": 1, "done": step1_done,
         "title": "Frecuencia de pago", "description": "Define si pagas nómina quincenal o mensual.",
         "url": url_for("web_rrhh.payroll_setup"), "action": "Configurar frecuencia"},
        {"number": 2, "done": step2_done,
         "title": "Catálogos", "description": "Define las posiciones (cargos) y departamentos de tu empresa.",
         "url": url_for("web_rrhh.position_list"), "action": "Configurar catálogos"},
        {"number": 3, "done": step3_done,
         "title": "Primer empleado", "description": "Registra la información de las personas de tu equipo.",
         "url": url_for("web_rrhh.employee_new"), "action": "Agregar empleado"},
        {"number": 4, "done": step4_done,
         "title": "Conceptos de nómina", "description": "Revisa ingresos, deducciones y aportes configurados.",
         "url": url_for("web_rrhh.concept_list"), "action": "Revisar conceptos"},
        {"number": 5, "done": step5_done,
         "title": "Procesar nómina", "description": "Procesa tu primer período de nómina.",
         "url": url_for("web_rrhh.payroll_new"), "action": "Procesar nómina"},
    ]

    all_done = all(s["done"] for s in steps)
    next_step = next((s["number"] for s in steps if not s["done"]), None)

    return render_template("rrhh/onboarding_guide.html", active_page="rrhh_dashboard",
                           steps=steps, all_done=all_done, next_step=next_step)


@web_rrhh_bp.route("/rrhh/payroll/setup", methods=["GET", "POST"])
def payroll_setup():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from uuid import uuid4

    if request.method == "POST":
        selection = request.form.get("payroll_type", "")
        config = hr.get_payroll_config(company_id, sandbox=sandbox)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        user_email = session.get("user", {}).get("email", "")

        if selection == "mensual":
            config["payrollFrequency"] = "mensual"
            hr.save_payroll_config(company_id, config, sandbox=sandbox)
            gid = str(uuid4())
            hr.save_payroll_group(company_id, gid, {
                "id": gid, "name": "Nómina Mensual", "description": "",
                "frequency": "mensual", "isActive": True,
                "createdAt": now_iso, "updatedAt": now_iso, "createdBy": user_email,
            }, sandbox=sandbox)
            flash("Grupo «Nómina Mensual» creado.", "success")

        elif selection == "quincenal":
            config["payrollFrequency"] = "quincenal"
            hr.save_payroll_config(company_id, config, sandbox=sandbox)
            gid = str(uuid4())
            hr.save_payroll_group(company_id, gid, {
                "id": gid, "name": "Nómina Quincenal", "description": "",
                "frequency": "quincenal", "isActive": True,
                "createdAt": now_iso, "updatedAt": now_iso, "createdBy": user_email,
            }, sandbox=sandbox)
            flash("Grupo «Nómina Quincenal» creado.", "success")

        elif selection == "ambos":
            config["payrollFrequency"] = "mensual"
            hr.save_payroll_config(company_id, config, sandbox=sandbox)
            gid1 = str(uuid4())
            hr.save_payroll_group(company_id, gid1, {
                "id": gid1, "name": "Nómina Mensual", "description": "",
                "frequency": "mensual", "isActive": True,
                "createdAt": now_iso, "updatedAt": now_iso, "createdBy": user_email,
            }, sandbox=sandbox)
            gid2 = str(uuid4())
            hr.save_payroll_group(company_id, gid2, {
                "id": gid2, "name": "Nómina Quincenal", "description": "",
                "frequency": "quincenal", "isActive": True,
                "createdAt": now_iso, "updatedAt": now_iso, "createdBy": user_email,
            }, sandbox=sandbox)
            flash("Grupos «Nómina Mensual» y «Nómina Quincenal» creados.", "success")

        else:
            flash("Selecciona una opción válida.", "error")
            return redirect(url_for("web_rrhh.payroll_setup"))

        config["onboardingCompleted"] = True
        hr.save_payroll_config(company_id, config, sandbox=sandbox)
        flash("¡Configuración de nómina guardada exitosamente!", "success")
        return redirect(url_for("web_rrhh.onboarding_guide"))

    return render_template("rrhh/payroll_onboarding.html", active_page="rrhh_dashboard")


