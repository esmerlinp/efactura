"""RRHH module — Horas Extras."""

from datetime import date, datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.overtime_service import OvertimeService
from app.services.payroll_overtime_calculator import PayrollOvertimeCalculator


# ═══════════════════════════════════════════════════════════════════════════
# HORAS EXTRAS — Listado
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/overtime")
def overtime_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    records = OvertimeService.list_records(owner_uid, sandbox=sandbox)
    records.sort(key=lambda r: r.get("registeredAt", ""), reverse=True)

    # Seed tipos por defecto si no existen
    types = hr.get_overtime_types(owner_uid, sandbox=sandbox)
    if not types:
        OvertimeService.seed_default_types(owner_uid, sandbox=sandbox)

    # Filtros
    status_filter = request.args.get("status", "")
    if status_filter:
        records = [r for r in records if r.get("status") == status_filter]

    emp_filter = request.args.get("employee", "")
    if emp_filter:
        records = [r for r in records if r.get("employeeId") == emp_filter]

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    overtime_types = hr.get_overtime_types(owner_uid, sandbox=sandbox)

    return render_template(
        "rrhh/overtime/list.html",
        active_page="rrhh_overtime",
        records=records,
        employees=employees,
        overtime_types=overtime_types,
        status_filter=status_filter,
        emp_filter=emp_filter,
    )


# ═══════════════════════════════════════════════════════════════════════════
# HORAS EXTRAS — Nuevo registro
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/overtime/new", methods=["GET", "POST"])
def overtime_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    active_emps = [e for e in employees if e.get("status") == "activo"]
    overtime_types = hr.get_overtime_types(owner_uid, sandbox=sandbox)

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        emp = hr.get_employee(owner_uid, emp_id, sandbox=sandbox) if emp_id else None
        if not emp:
            flash("Empleado no encontrado.", "error")
            return render_template("rrhh/overtime/form.html", ...)

        # Recolectar detalles de la tabla
        detail_dates = request.form.getlist("detail_date[]")
        detail_from = request.form.getlist("detail_from[]")
        detail_to = request.form.getlist("detail_to[]")
        detail_minutes = request.form.getlist("detail_minutes[]")

        details = []
        total_minutes = 0
        for i in range(len(detail_dates)):
            mins = int(detail_minutes[i]) if i < len(detail_minutes) and detail_minutes[i] else 0
            details.append({
                "date": detail_dates[i] if i < len(detail_dates) else "",
                "fromTime": detail_from[i] if i < len(detail_from) else "",
                "toTime": detail_to[i] if i < len(detail_to) else "",
                "minutes": mins,
            })
            total_minutes += mins

        data = {
            "employeeId": emp_id,
            "employeeCode": emp.get("code", ""),
            "employeeName": emp.get("fullName", ""),
            "companyCode": request.form.get("companyCode", ""),
            "departmentCode": emp.get("department", ""),
            "payrollCode": request.form.get("payrollCode", ""),
            "date": request.form.get("date", ""),
            "overtimeTypeCode": request.form.get("overtimeTypeCode", ""),
            "totalMinutes": total_minutes,
            "comment": request.form.get("comment", ""),
            "source": request.form.get("source", "manual"),
            "sourceReference": request.form.get("sourceReference", ""),
            "details": details,
        }

        record = OvertimeService.create_record(owner_uid, data, user_email, sandbox=sandbox)
        flash(f"Hora extra {record['number']} creada exitosamente.", "success")
        return redirect(url_for("web_rrhh.overtime_list"))

    return render_template(
        "rrhh/overtime/form.html",
        active_page="rrhh_overtime",
        employees=active_emps,
        overtime_types=overtime_types,
        record=None,
        today=date.today().isoformat(),
        PayrollOvertimeCalculator=PayrollOvertimeCalculator,
    )


# ═══════════════════════════════════════════════════════════════════════════
# HORAS EXTRAS — Vista detalle
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/overtime/<record_id>")
def overtime_view(record_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    record = OvertimeService.get_record(owner_uid, record_id, sandbox=sandbox)
    if not record:
        flash("Registro no encontrado.", "error")
        return redirect(url_for("web_rrhh.overtime_list"))

    employee = hr.get_employee(owner_uid, record.get("employeeId", ""), sandbox=sandbox)
    otype = hr.get_overtime_type(owner_uid, record.get("overtimeTypeCode", ""), sandbox=sandbox)
    payroll_links = OvertimeService.get_links_for_payroll(owner_uid, record.get("processedPayrollId", ""), sandbox=sandbox) if record.get("processedPayrollId") else []

    return render_template(
        "rrhh/overtime/view.html",
        active_page="rrhh_overtime",
        record=record,
        employee=employee,
        otype=otype,
        payroll_links=payroll_links,
    )


# ═══════════════════════════════════════════════════════════════════════════
# FLUJO DE APROBACIÓN
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/overtime/<record_id>/submit", methods=["POST"])
def overtime_submit(record_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    result = OvertimeService.submit_for_approval(owner_uid, record_id, user_email, sandbox=sandbox)
    if isinstance(result, tuple):
        flash(result[0].get("error", "Error al enviar a aprobación."), "error")
    else:
        flash(f"HE {result.get('number', record_id)} enviada a aprobación.", "success")
    return redirect(url_for("web_rrhh.overtime_view", record_id=record_id))


@web_rrhh_bp.route("/rrhh/overtime/<record_id>/approve", methods=["POST"])
def overtime_approve(record_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    result = OvertimeService.approve(owner_uid, record_id, user_email, sandbox=sandbox)
    if isinstance(result, tuple):
        flash(result[0].get("error", "Error al aprobar."), "error")
    else:
        flash(f"HE {result.get('number', record_id)} aprobada.", "success")
    return redirect(url_for("web_rrhh.overtime_view", record_id=record_id))


@web_rrhh_bp.route("/rrhh/overtime/<record_id>/reject", methods=["POST"])
def overtime_reject(record_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")
    reason = request.form.get("reason", "").strip()

    result = OvertimeService.reject(owner_uid, record_id, user_email, reason, sandbox=sandbox)
    if isinstance(result, tuple):
        flash(result[0].get("error", "Error al rechazar."), "error")
    else:
        flash(f"HE {result.get('number', record_id)} rechazada.", "success")
    return redirect(url_for("web_rrhh.overtime_view", record_id=record_id))


@web_rrhh_bp.route("/rrhh/overtime/<record_id>/reset", methods=["POST"])
def overtime_reset(record_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    result = OvertimeService.reset_to_draft(owner_uid, record_id, user_email, sandbox=sandbox)
    if isinstance(result, tuple):
        flash(result[0].get("error", "Error al devolver a borrador."), "error")
    else:
        flash(f"HE {result.get('number', record_id)} devuelta a borrador.", "success")
    return redirect(url_for("web_rrhh.overtime_view", record_id=record_id))


# ═══════════════════════════════════════════════════════════════════════════
# BANDEJA DE PENDIENTES
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/overtime/pending")
def overtime_pending():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    pending = OvertimeService.list_by_status(owner_uid, "pending", sandbox=sandbox)
    pending.sort(key=lambda r: r.get("registeredAt", ""), reverse=True)

    employees_map = {}
    for r in pending:
        snap = r.get("employeeSnapshot", {})
        employees_map[r["employeeId"]] = snap.get("name", r["employeeId"])

    overtime_types = hr.get_overtime_types(owner_uid, sandbox=sandbox)
    types_map = {t["code"]: t["name"] for t in overtime_types}

    return render_template(
        "rrhh/overtime/pending.html",
        active_page="rrhh_overtime",
        records=pending,
        employees_map=employees_map,
        types_map=types_map,
    )


# ═══════════════════════════════════════════════════════════════════════════
# TIPOS DE HORAS EXTRAS — Catálogo
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/overtime/types")
def overtime_types_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    types = hr.get_overtime_types(owner_uid, sandbox=sandbox)
    from app.services.payroll_concept_engine import get_concepts
    concepts = get_concepts(owner_uid, sandbox=sandbox)
    concepts_map = {c["code"]: c["name"] for c in concepts}

    return render_template(
        "rrhh/overtime/types/list.html",
        active_page="rrhh_overtime",
        types=types,
        concepts_map=concepts_map,
    )


@web_rrhh_bp.route("/rrhh/overtime/types/new", methods=["GET", "POST"])
def overtime_types_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    from app.services.payroll_concept_engine import get_concepts
    concepts = get_concepts(owner_uid, sandbox=sandbox)

    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        if hr.get_overtime_type(owner_uid, code, sandbox=sandbox):
            flash(f"El código {code} ya existe.", "error")
            return render_template("rrhh/overtime/types/form.html", ...)

        data = {
            "code": code,
            "name": request.form.get("name", "").strip(),
            "factor": float(request.form.get("factor", 1.35) or 1.35),
            "conceptCode": request.form.get("conceptCode", ""),
            "active": True,
        }
        hr.save_overtime_type(owner_uid, code, data, sandbox=sandbox)
        flash(f"Tipo de hora extra {code} creado.", "success")
        return redirect(url_for("web_rrhh.overtime_types_list"))

    return render_template(
        "rrhh/overtime/types/form.html",
        active_page="rrhh_overtime",
        otype=None,
        concepts=concepts,
    )


@web_rrhh_bp.route("/rrhh/overtime/types/<code>/edit", methods=["GET", "POST"])
def overtime_types_edit(code):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    otype = hr.get_overtime_type(owner_uid, code, sandbox=sandbox)
    if not otype:
        flash("Tipo no encontrado.", "error")
        return redirect(url_for("web_rrhh.overtime_types_list"))

    from app.services.payroll_concept_engine import get_concepts
    concepts = get_concepts(owner_uid, sandbox=sandbox)

    if request.method == "POST":
        otype["name"] = request.form.get("name", "").strip()
        otype["factor"] = float(request.form.get("factor", 1.35) or 1.35)
        otype["conceptCode"] = request.form.get("conceptCode", "")
        hr.save_overtime_type(owner_uid, code, otype, sandbox=sandbox)
        flash("Tipo actualizado.", "success")
        return redirect(url_for("web_rrhh.overtime_types_list"))

    return render_template(
        "rrhh/overtime/types/form.html",
        active_page="rrhh_overtime",
        otype=otype,
        concepts=concepts,
    )


@web_rrhh_bp.route("/rrhh/overtime/types/<code>/toggle", methods=["POST"])
def overtime_types_toggle(code):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    otype = hr.get_overtime_type(owner_uid, code, sandbox=sandbox)
    if otype:
        otype["active"] = not otype.get("active", True)
        hr.save_overtime_type(owner_uid, code, otype, sandbox=sandbox)
        flash(f"Tipo {'activado' if otype['active'] else 'desactivado'}.", "success")
    return redirect(url_for("web_rrhh.overtime_types_list"))


# ═══════════════════════════════════════════════════════════════════════════
# AJAX — Calcular previsualización
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/overtime/preview-calculation", methods=["POST"])
def overtime_preview_calculation():
    if _login_required():
        return {"error": "No autorizado"}, 401
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    try:
        data = request.get_json(force=True)
    except Exception:
        return {"error": "JSON inválido"}, 400

    emp_id = data.get("employeeId", "")
    minutes = int(data.get("minutes", 0) or 0)
    type_code = data.get("overtimeTypeCode", "")

    emp = hr.get_employee(owner_uid, emp_id, sandbox=sandbox) if emp_id else None
    if not emp:
        return {"error": "Empleado no encontrado"}, 404

    otype = hr.get_overtime_type(owner_uid, type_code, sandbox=sandbox) if type_code else None
    factor = float(otype.get("factor", 1.35)) if otype else 1.35

    base = float(emp.get("baseSalary", emp.get("salary", 0)))
    hourly = PayrollOvertimeCalculator.calculate_hourly_rate(base)
    amount = PayrollOvertimeCalculator.calculate_pay(hourly, minutes, factor)
    hours = PayrollOvertimeCalculator.hours_from_minutes(minutes)

    return {
        "hourlyRate": round(hourly, 2),
        "factor": factor,
        "hours": hours,
        "minutes": minutes,
        "amount": amount,
    }
