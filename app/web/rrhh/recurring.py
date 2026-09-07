"""RRHH module — Movimientos Recurrentes de Nómina (Préstamos, Embargos, Ahorros, Ingresos recurrentes, etc.)."""

import io
import uuid
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.utils import secure_filename
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
)
from app.services import hr_data_service as hr
from app.services.db_service import DatabaseService, firebase_storage_bucket, _invalidate_storage_cache
from app.web.rrhh.work_certificate import _get_company_data, _today_es

MAX_AUTHORIZATION_SIZE = 10 * 1024 * 1024  # 10MB


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


def _safe_next(request):
    """Retorna la URL de retorno (next) si es una ruta local válida."""
    nxt = request.args.get("next", "") or request.form.get("next", "")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return ""


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
    employee_codes = {e.get("id"): e.get("code", "") for e in employees}
    employee_names = {
        e.get("id"): " ".join(p for p in [e.get("firstName", ""),
                                          e.get("firstLastName", "") or e.get("lastName", "")] if p)
                    or e.get("fullName", "")
        for e in employees
    }

    return render_template(
        "rrhh/recurring/list.html",
        active_page="rrhh_recurring",
        movements=movements,
        employees=employees,
        employee_codes=employee_codes,
        employee_names=employee_names,
        STATUS_OPTS=STATUS_OPTS,
        MOVEMENT_TYPES=MOVEMENT_TYPES,
        filters={"employee_id": employee_id, "status": status_filter, "movement_type": movement_type},
    )


@web_rrhh_bp.route("/rrhh/recurring/new", methods=["GET", "POST"])
def recurring_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    next_url = _safe_next(request)

    employees = hr.get_employees(company_id, sandbox=sandbox)
    employees.sort(key=lambda e: e.get("fullName", e.get("firstName", "")))

    from app.services.payroll_concept_engine import get_concepts
    concepts = get_concepts(company_id, sandbox=sandbox)

    preset_concept = request.args.get("concept", "")
    preset_group = request.args.get("group", "")

    if request.method == "POST":
        data = _parse_recurring_form(request.form)
        data["id"] = str(uuid.uuid4())
        data["createdBy"] = session.get("user", {}).get("email", "")
        data["status"] = data.get("status", "active")
        hr.save_recurring_movement(company_id, data["id"], data, sandbox=sandbox)

        try:
            from app.services.payroll_audit_service import log_employee_action
            mtype = data.get("movementType", "deduction")
            mtype_label = MOVEMENT_TYPES.get(mtype, mtype)
            log_employee_action(
                company_id, data.get("employeeId", ""), "recurring_movement_created",
                comment=f"Movimiento recurrente ({mtype_label}): {data.get('description', '')}",
                changes={
                    "movementId": data.get("id", ""),
                    "movementType": mtype,
                    "conceptCode": data.get("conceptCode", ""),
                    "amount": data.get("amount", 0),
                    "description": data.get("description", ""),
                },
                user_email=data["createdBy"], sandbox=sandbox,
            )
        except Exception as e:
            print(f"⚠️ recurring.log_employee_action: {e}")

        flash("Movimiento recurrente creado exitosamente.", "success")
        if next_url:
            return redirect(next_url)
        return redirect(url_for("web_rrhh.recurring_list"))

    return render_template(
        "rrhh/recurring/form.html",
        active_page="rrhh_recurring",
        movement=None,
        employees=employees,
        concepts=concepts,
        payroll_groups=hr.get_payroll_groups(company_id, sandbox=sandbox),
        preset_concept=preset_concept,
        preset_group=preset_group,
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

    from app.services.deduction_authorization_service import can_generate_authorization
    authorization_docs = []
    can_authorize = can_generate_authorization(movement)
    if can_authorize:
        authorization_docs = hr.get_deduction_authorization_docs(company_id, movement_id, sandbox=sandbox)

    if request.method == "POST":
        if movement.get("status") in ("completed", "cancelled"):
            flash("No se puede editar un movimiento completado o cancelado.", "error")
            return redirect(url_for("web_rrhh.recurring_edit", movement_id=movement_id))

        data = _parse_recurring_form(request.form, existing=movement)
        data["updatedBy"] = session.get("user", {}).get("email", "")
        hr.save_recurring_movement(company_id, movement_id, data, sandbox=sandbox)
        flash("Movimiento recurrente actualizado.", "success")
        if _safe_next(request):
            return redirect(_safe_next(request))
        return redirect(url_for("web_rrhh.recurring_list"))

    return render_template(
        "rrhh/recurring/form.html",
        active_page="rrhh_recurring",
        movement=movement,
        employees=employees,
        concepts=concepts,
        payroll_groups=hr.get_payroll_groups(company_id, sandbox=sandbox),
        authorization_docs=authorization_docs,
        can_authorize=can_authorize,
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
    if _safe_next(request):
        return redirect(_safe_next(request))
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


def _delete_authorization_blob(storage_path: str, owner_uid: str):
    if not storage_path or storage_path.startswith("/uploads/"):
        return
    try:
        if firebase_storage_bucket:
            firebase_storage_bucket.blob(storage_path).delete()
        if owner_uid:
            _invalidate_storage_cache(owner_uid)
    except Exception as e:
        print(f"⚠️ Error al eliminar autorización de storage: {e}")


@web_rrhh_bp.route("/rrhh/recurring/<movement_id>/authorization/pdf")
def recurring_authorization_pdf(movement_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    movement = hr.get_recurring_movement(company_id, movement_id, sandbox=sandbox)
    if not movement:
        return "", 404

    from app.services.deduction_authorization_service import can_generate_authorization
    if not can_generate_authorization(movement):
        flash("La Autorización de Descuento solo aplica a deducciones regulares o préstamos.", "error")
        return redirect(url_for("web_rrhh.recurring_list"))

    employee = hr.get_employee(company_id, movement.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        return "", 404

    company = _get_company_data(owner_uid, company_id)

    try:
        from app.services.deduction_authorization_service import generate_authorization_pdf
        pdf_bytes = generate_authorization_pdf(movement, employee, company, request.host_url, today_es=_today_es())
        safe_emp = (employee.get("fullName") or employee.get("firstName", "") or "empleado").replace(" ", "_")
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=f"autorizacion_descuento_{safe_emp}.pdf")
    except Exception as e:
        print(f"Error generando autorización de descuento: {e}")
        flash("Error al generar la autorización.", "error")
        return redirect(url_for("web_rrhh.recurring_edit", movement_id=movement_id))


@web_rrhh_bp.route("/rrhh/recurring/<movement_id>/authorization/upload", methods=["POST"])
def recurring_authorization_upload(movement_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    movement = hr.get_recurring_movement(company_id, movement_id, sandbox=sandbox)
    if not movement:
        flash("Movimiento no encontrado.", "error")
        return redirect(url_for("web_rrhh.recurring_list"))

    employee_id = movement.get("employeeId", "")
    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox) if employee_id else None
    if not employee:
        flash("El movimiento no tiene un empleado válido asociado. Corrige el movimiento e intenta de nuevo.", "error")
        return redirect(url_for("web_rrhh.recurring_edit", movement_id=movement_id))
    employee_id = employee.get("id", employee_id)

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debes seleccionar un archivo.", "error")
        return redirect(url_for("web_rrhh.recurring_edit", movement_id=movement_id))

    file_data = file.read()
    if len(file_data) > MAX_AUTHORIZATION_SIZE:
        flash("El archivo excede el tamaño máximo de 10MB.", "error")
        return redirect(url_for("web_rrhh.recurring_edit", movement_id=movement_id))

    mime_type = file.content_type or "application/octet-stream"
    safe_name = secure_filename(file.filename) or "autorizacion"
    destination_path = f"users/{owner_uid}/employee_documents/{employee_id}/{uuid.uuid4().hex[:8]}_{safe_name}"
    url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)

    hr.save_employee_document(company_id, {
        "id": str(uuid.uuid4()),
        "employeeId": employee_id,
        "recurringMovementId": movement_id,
        "documentType": "payroll_authorization",
        "category": "authorization",
        "signed": True,
        "name": file.filename,
        "size": len(file_data),
        "contentType": mime_type,
        "url": url,
        "storagePath": destination_path,
        "uploadedBy": session.get("user", {}).get("email", ""),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
    }, sandbox=sandbox)

    flash("Documento firmado subido y asociado al movimiento.", "success")
    return redirect(url_for("web_rrhh.recurring_edit", movement_id=movement_id))


@web_rrhh_bp.route("/rrhh/recurring/<movement_id>/authorization/<doc_id>/delete", methods=["POST"])
def recurring_authorization_delete(movement_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    docs = hr.get_deduction_authorization_docs(company_id, movement_id, sandbox=sandbox)
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if doc:
        _delete_authorization_blob(doc.get("storagePath", ""), owner_uid)

    hr.delete_employee_document(company_id, doc_id, sandbox=sandbox)
    flash("Documento eliminado.", "success")
    return redirect(url_for("web_rrhh.recurring_edit", movement_id=movement_id))


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
    is_deduction_regular = (movement_type == "deduction" and sub_type == "regular")

    # ── Monto: leer la sección visible según tipo/subtipo ──
    # El formulario envía ambas secciones (ingresos + deducción); los inputs de la
    # sección oculta (display:none) también se envían y form.get() devolvería la
    # primera ocurrencia del DOM → monto 0. Por eso la sección de deducción
    # regular usa nombres dedicados (ded*).
    if is_deduction_regular:
        amount_type = form.get("dedAmountType", "fixed")
        amount = float(form.get("dedAmount", 0) or 0)
        percentage = float(form.get("dedPercentage", 0) or 0)
        formula = form.get("dedFormula", "")
    elif is_loan:
        # El monto por período de un préstamo es la cuota; se refleja en "amount"
        # para que listas y consumidores genéricos lo muestren correctamente.
        installment = float(form.get("installmentAmount", 0) or 0)
        amount_type = "fixed"
        amount = installment
        percentage = 0.0
        formula = ""
    else:
        amount_type = form.get("amountType", "fixed")
        amount = float(form.get("amount", 0) or 0)
        percentage = float(form.get("percentage", 0) or 0)
        formula = form.get("formula", "")

    data = {
        "employeeId": emp_id,
        "contractId": contract_id,
        "employeeName": employee_name,
        "conceptCode": form.get("conceptCode", ""),
        "movementType": form.get("movementType", "deduction"),
        "description": form.get("description", ""),
        "payrollGroupIds": form.getlist("payrollGroupIds"),
        "amountType": amount_type,
        "amount": amount,
        "percentage": percentage,
        "formula": formula,
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