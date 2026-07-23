"""RRHH module — Movimientos Recurrentes de Nómina (Préstamos, Embargos, Ahorros, Ingresos recurrentes, etc.)."""

import uuid
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
)
from app.services import hr_data_service as hr


MOVEMENT_TYPES = {
    "deduction": "Deducción",
    "earning": "Ingreso",
    "employer_contrib": "Aporte Empleador",
}

AMOUNT_TYPES = {
    "fixed": "Monto Fijo",
    "percentage": "Porcentaje",
    "formula": "Fórmula",
}

DEDUCTION_TYPES = {
    "fixed": "Monto Fijo",
    "percentage": "Porcentaje",
    "max_of_legal": "Máximo Legal",
}

DEDUCTION_SUBTYPE = {
    "regular": "Descuento Regular",
    "loan": "Préstamo",
    "garnishment": "Embargo Judicial",
}

STATUS_OPTS = {
    "scheduled": "Programado",
    "active": "Activo",
    "paused": "Pausado",
    "completed": "Completado",
    "cancelled": "Cancelado",
}

FREQUENCY_OPTS = {
    "every_period": "Cada Período",
    "monthly": "Mensual",
    "specific_months": "Meses Específicos",
}


@web_rrhh_bp.route("/rrhh/recurring")
def recurring_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    employee_id = request.args.get("employee_id", "")
    status_filter = request.args.get("status", "")
    movement_type = request.args.get("movement_type", "")

    movements = hr.get_recurring_movements(
        company_id,
        employee_id=employee_id,
        status=status_filter,
        movement_type=movement_type,
        sandbox=sandbox,
    )
    movements.sort(key=lambda m: (m.get("employeeName", ""), m.get("priority", 50)))

    employees = hr.get_employees(company_id, sandbox=sandbox)
    employees.sort(key=lambda e: e.get("fullName", e.get("firstName", "")))

    return render_template(
        "rrhh/recurring/list.html",
        active_page="rrhh_recurring",
        movements=movements,
        employees=employees,
        STATUS_OPTS=STATUS_OPTS,
        MOVEMENT_TYPES=MOVEMENT_TYPES,
        filters={"employee_id": employee_id, "status": status_filter, "movement_type": movement_type},
    )


@web_rrhh_bp.route("/rrhh/recurring/new", methods=["GET", "POST"])
def recurring_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    employees = hr.get_employees(company_id, sandbox=sandbox)
    employees.sort(key=lambda e: e.get("fullName", e.get("firstName", "")))

    from app.services.payroll_concept_engine import get_concepts
    concepts = get_concepts(company_id, sandbox=sandbox)

    if request.method == "POST":
        data = _parse_recurring_form(request.form)
        data["id"] = str(uuid.uuid4())
        data["createdBy"] = session.get("user", {}).get("email", "")
        data["status"] = data.get("status", "active")
        hr.save_recurring_movement(company_id, data["id"], data, sandbox=sandbox)
        flash("Movimiento recurrente creado exitosamente.", "success")
        return redirect(url_for("web_rrhh.recurring_list"))

    return render_template(
        "rrhh/recurring/form.html",
        active_page="rrhh_recurring",
        movement=None,
        employees=employees,
        concepts=concepts,
        payroll_groups=hr.get_payroll_groups(company_id, sandbox=sandbox),
        MOVEMENT_TYPES=MOVEMENT_TYPES,
        AMOUNT_TYPES=AMOUNT_TYPES,
        DEDUCTION_TYPES=DEDUCTION_TYPES,
        DEDUCTION_SUBTYPE=DEDUCTION_SUBTYPE,
        STATUS_OPTS=STATUS_OPTS,
        FREQUENCY_OPTS=FREQUENCY_OPTS,
    )


@web_rrhh_bp.route("/rrhh/recurring/<movement_id>/edit", methods=["GET", "POST"])
def recurring_edit(movement_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    movement = hr.get_recurring_movement(company_id, movement_id, sandbox=sandbox)
    if not movement:
        flash("Movimiento recurrente no encontrado.", "error")
        return redirect(url_for("web_rrhh.recurring_list"))

    employees = hr.get_employees(company_id, sandbox=sandbox)
    employees.sort(key=lambda e: e.get("fullName", e.get("firstName", "")))

    from app.services.payroll_concept_engine import get_concepts
    concepts = get_concepts(company_id, sandbox=sandbox)

    if request.method == "POST":
        if movement.get("status") in ("completed", "cancelled"):
            flash("No se puede editar un movimiento completado o cancelado.", "error")
            return redirect(url_for("web_rrhh.recurring_edit", movement_id=movement_id))

        data = _parse_recurring_form(request.form, existing=movement)
        data["updatedBy"] = session.get("user", {}).get("email", "")
        hr.save_recurring_movement(company_id, movement_id, data, sandbox=sandbox)
        flash("Movimiento recurrente actualizado.", "success")
        return redirect(url_for("web_rrhh.recurring_list"))

    return render_template(
        "rrhh/recurring/form.html",
        active_page="rrhh_recurring",
        movement=movement,
        employees=employees,
        concepts=concepts,
        payroll_groups=hr.get_payroll_groups(company_id, sandbox=sandbox),
        MOVEMENT_TYPES=MOVEMENT_TYPES,
        AMOUNT_TYPES=AMOUNT_TYPES,
        DEDUCTION_TYPES=DEDUCTION_TYPES,
        DEDUCTION_SUBTYPE=DEDUCTION_SUBTYPE,
        STATUS_OPTS=STATUS_OPTS,
        FREQUENCY_OPTS=FREQUENCY_OPTS,
    )


@web_rrhh_bp.route("/rrhh/recurring/<movement_id>/toggle-status", methods=["POST"])
def recurring_toggle_status(movement_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    movement = hr.get_recurring_movement(company_id, movement_id, sandbox=sandbox)
    if not movement:
        flash("Movimiento no encontrado.", "error")
        return redirect(url_for("web_rrhh.recurring_list"))

    new_status = request.form.get("new_status", "")
    if new_status not in STATUS_OPTS:
        flash("Estado inválido.", "error")
        return redirect(url_for("web_rrhh.recurring_list"))

    movement["status"] = new_status
    movement["updatedBy"] = session.get("user", {}).get("email", "")
    hr.save_recurring_movement(company_id, movement_id, movement, sandbox=sandbox)
    flash(f"Movimiento cambiado a '{STATUS_OPTS[new_status]}'.", "success")
    return redirect(url_for("web_rrhh.recurring_list"))


@web_rrhh_bp.route("/rrhh/recurring/<movement_id>/delete", methods=["POST"])
def recurring_delete(movement_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    movement = hr.get_recurring_movement(company_id, movement_id, sandbox=sandbox)
    if movement and movement.get("status") in ("active", "scheduled"):
        flash("No se puede eliminar un movimiento activo o programado. Cámbielo a cancelado primero.", "error")
        return redirect(url_for("web_rrhh.recurring_list"))

    hr.delete_recurring_movement(company_id, movement_id, sandbox=sandbox)
    flash("Movimiento recurrente eliminado.", "success")
    return redirect(url_for("web_rrhh.recurring_list"))


@web_rrhh_bp.route("/rrhh/recurring/<movement_id>/applications")
def recurring_applications(movement_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    movement = hr.get_recurring_movement(company_id, movement_id, sandbox=sandbox)
    if not movement:
        flash("Movimiento no encontrado.", "error")
        return redirect(url_for("web_rrhh.recurring_list"))

    from app.services.recurring_service import get_applications_by_period
    from app.services import hr_data_service as hr

    # Get all applications related to this movement via period lookups
    all_apps = []
    periods = hr.get_payroll_periods(company_id, sandbox=sandbox)
    for p in periods:
        apps = get_applications_by_period(company_id, p.get("id", ""), sandbox=sandbox)
        for a in apps:
            if a.get("recurringMovementId") == movement_id:
                a["periodLabel"] = p.get("label", p.get("periodKey", ""))
                all_apps.append(a)

    all_apps.sort(key=lambda a: a.get("appliedAt", ""), reverse=True)

    return render_template(
        "rrhh/recurring/history.html",
        active_page="rrhh_recurring",
        movement=movement,
        applications=all_apps,
        STATUS_OPTS=STATUS_OPTS,
    )


def _parse_recurring_form(form, existing=None):
    """Parsea el formulario de movimiento recurrente."""
    emp_id = form.get("employeeId", "")
    contract_id = form.get("contractId", "")

    # Resolve employee name
    employee_name = ""
    if emp_id and existing and existing.get("employeeId") == emp_id:
        employee_name = existing.get("employeeName", "")
    elif emp_id:
        owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
        emp = hr.get_employee(company_id, emp_id, sandbox=sandbox)
        if emp:
            employee_name = emp.get("fullName", emp.get("firstName", "") + " " + emp.get("lastName", ""))

    sub_type = form.get("deductionSubType", "regular")
    movement_type = form.get("movementType", "deduction")
    if movement_type != "deduction":
        sub_type = "regular"
    is_loan = (sub_type == "loan")
    is_garnishment = (sub_type == "garnishment")

    data = {
        "employeeId": emp_id,
        "contractId": contract_id,
        "employeeName": employee_name,
        "conceptCode": form.get("conceptCode", ""),
        "movementType": form.get("movementType", "deduction"),
        "description": form.get("description", ""),
        "payrollGroupIds": form.getlist("payrollGroupIds"),
        "amountType": form.get("amountType", "fixed"),
        "amount": float(form.get("amount", 0) or 0),
        "percentage": float(form.get("percentage", 0) or 0),
        "formula": form.get("formula", ""),
        "isLoan": is_loan,
        "isGarnishment": is_garnishment,
        "startDate": form.get("startDate", ""),
        "endDate": form.get("endDate", "") if not form.get("indefinite") else "",
        "indefinite": form.get("indefinite") == "on",
        "applyFrequency": form.get("applyFrequency", "every_period"),
        "applyMonths": [int(m) for m in form.getlist("applyMonths")] if form.get("applyFrequency") == "specific_months" else [],
        "priority": int(form.get("priority", 50) or 50),
        "status": form.get("status", "active"),
        "notes": form.get("notes", ""),
    }

    if is_loan:
        data["totalAmount"] = float(form.get("totalAmount", 0) or 0)
        data["installmentAmount"] = float(form.get("installmentAmount", 0) or 0)
        data["totalInstallments"] = int(form.get("totalInstallments", 0) or 0)
        data["remainingBalance"] = float(form.get("remainingBalance", 0) or data["totalAmount"])
        data["paidInstallments"] = int(form.get("paidInstallments", 0) or 0)
        data["autoComplete"] = form.get("autoComplete") == "on"
    else:
        data["totalAmount"] = 0.0
        data["installmentAmount"] = 0.0
        data["totalInstallments"] = 0
        data["remainingBalance"] = 0.0
        data["paidInstallments"] = 0
        data["autoComplete"] = True

    if is_garnishment:
        data["garnishmentType"] = form.get("garnishmentType", "")
        data["referenceNumber"] = form.get("referenceNumber", "")
        data["issuingEntity"] = form.get("issuingEntity", "")
        data["beneficiaryName"] = form.get("beneficiaryName", "")
        data["beneficiaryAccount"] = form.get("beneficiaryAccount", "")
        data["deductionType"] = form.get("deductionType", "fixed")
        data["deductionPercent"] = float(form.get("deductionPercent", 0) or 0)
        data["maxLegalRate"] = float(form.get("maxLegalRate", 0) or 0)
    else:
        data["garnishmentType"] = ""
        data["referenceNumber"] = ""
        data["issuingEntity"] = ""
        data["beneficiaryName"] = ""
        data["beneficiaryAccount"] = ""
        data["deductionType"] = "fixed"
        data["deductionPercent"] = 0.0
        data["maxLegalRate"] = 0.0

    return data