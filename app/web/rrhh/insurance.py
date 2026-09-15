"""Administracion web de proveedores, planes y afiliaciones de seguro."""

from datetime import date

from flask import flash, redirect, render_template, request, session, url_for

from app.services import insurance_enrollment_service as enrollments
from app.services import insurance_plan_service as plans
from app.services import insurance_provider_service as providers
from app.services.payroll_audit_service import log_action
from app.web.rrhh import _get_owner_uid_and_sandbox, _login_required, web_rrhh_bp


def _actor():
    return session.get("user", {}).get("email", "")


def _context():
    _, sandbox, company_id = _get_owner_uid_and_sandbox()
    return company_id, sandbox


@web_rrhh_bp.route("/rrhh/insurance/providers")
def insurance_provider_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox = _context()
    return render_template("rrhh/insurance/providers/list.html", providers=providers.list_providers(company_id, sandbox=sandbox), active_page="rrhh_insurance_providers")


@web_rrhh_bp.route("/rrhh/insurance/providers/new", methods=["GET", "POST"])
def insurance_provider_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox = _context()
    if request.method == "POST":
        provider = providers.save_provider(company_id, {"name": request.form.get("name", "").strip(), "description": request.form.get("description", "").strip()}, _actor(), sandbox)
        log_action(company_id, "insurance_provider_created", "insurance_provider", provider["id"], _actor(), after=provider, sandbox=sandbox)
        flash("Proveedor creado.", "success")
        return redirect(url_for("web_rrhh.insurance_provider_list"))
    return render_template("rrhh/insurance/providers/form.html", provider=None, active_page="rrhh_insurance_providers")


@web_rrhh_bp.route("/rrhh/insurance/plans")
def insurance_plan_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox = _context()
    plan_list = plans.list_plans(company_id, sandbox=sandbox)
    provider_names = {
        provider.get("id", ""): provider.get("name", "")
        for provider in providers.list_providers(company_id, sandbox=sandbox)
    }
    return render_template(
        "rrhh/insurance/plans/list.html",
        plans=plan_list,
        provider_names=provider_names,
        active_page="rrhh_insurance_plans",
    )


@web_rrhh_bp.route("/rrhh/insurance/plans/new", methods=["GET", "POST"])
def insurance_plan_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox = _context()
    provider_list = providers.list_providers(company_id, sandbox=sandbox)
    from app.services.payroll_concept_engine import get_concepts
    concept_list = sorted(
        [c for c in get_concepts(company_id, sandbox=sandbox) if c.get("active", True)],
        key=lambda c: (c.get("name", "").lower(), c.get("code", "")),
    )
    if request.method == "POST":
        data = _plan_form_data()
        try:
            plan = plans.save_plan(company_id, data, _actor(), sandbox, concepts=concept_list)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("rrhh/insurance/plans/form.html", plan=data, providers=provider_list, concepts=concept_list, active_page="rrhh_insurance_plans")
        log_action(company_id, "insurance_plan_created", "insurance_plan", plan["id"], _actor(), after=plan, sandbox=sandbox)
        flash("Plan creado.", "success")
        return redirect(url_for("web_rrhh.insurance_plan_list"))
    return render_template("rrhh/insurance/plans/form.html", plan=None, providers=provider_list, concepts=concept_list, active_page="rrhh_insurance_plans")


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/insurance", methods=["GET", "POST"])
def employee_insurance(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox = _context()
    if request.method == "POST":
        try:
            enrollment = enrollments.create_enrollment(company_id, {
                "employeeId": employee_id,
                "dependentId": request.form.get("dependentId", "").strip(),
                "planId": request.form.get("planId", "").strip(),
                "coverageType": request.form.get("coverageType", "primary"),
                "startDate": request.form.get("startDate", "").strip(),
            }, _actor(), sandbox)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("web_rrhh.employee_insurance", employee_id=employee_id))
        log_action(company_id, "insurance_enrollment_created", "insurance_enrollment", enrollment["id"], _actor(), after=enrollment, sandbox=sandbox)
        flash("Afiliacion creada.", "success")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id, tab="insurance"))
    from app.services import hr_data_service as hr
    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox) or {}
    dependents = hr.get_employee_dependents_active(company_id, employee_id, sandbox=sandbox)
    plan_list = plans.list_plans(company_id, sandbox)
    provider_list = providers.list_providers(company_id, sandbox=sandbox)
    return render_template(
        "rrhh/insurance/enrollments/list.html",
        employee=employee,
        dependents=dependents,
        employee_id=employee_id,
        enrollments=enrollments.list_enrollments(company_id, employee_id, sandbox),
        plans=plan_list,
        plan_names={p.get("id"): p.get("name", "") for p in plan_list},
        provider_names={p.get("id"): p.get("name", "") for p in provider_list},
        active_page="rrhh_insurance",
    )


@web_rrhh_bp.route("/rrhh/insurance/enrollments/<enrollment_id>/cancel", methods=["POST"])
def insurance_enrollment_cancel(enrollment_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox = _context()
    employee_id = request.form.get("employeeId", "")
    enrollments.cancel_enrollment(company_id, enrollment_id, request.form.get("endDate") or date.today().isoformat(), _actor(), sandbox)
    log_action(company_id, "insurance_enrollment_cancelled", "insurance_enrollment", enrollment_id, _actor(), sandbox=sandbox)
    flash("Afiliacion cancelada.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id, tab="insurance"))


def _plan_form_data():
    def rule(prefix):
        kind = request.form.get(f"{prefix}Type", "percentage")
        value = request.form.get(f"{prefix}Value", "0") or "0"
        return {"type": kind, "value": value if kind != "remainder" else None}
    return {
        "providerId": request.form.get("providerId", "").strip(),
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip(),
        "baseAmount": request.form.get("baseAmount", "0"),
        "companyContribution": rule("companyContribution"),
        "employeeContribution": rule("employeeContribution"),
        "payrollConceptId": request.form.get("payrollConceptId", "SEGURO").strip() or "SEGURO",
        "prorationPolicy": request.form.get("prorationPolicy", "none"),
        "currency": request.form.get("currency", "DOP"),
    }
