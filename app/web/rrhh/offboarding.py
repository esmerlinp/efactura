"""RRHH Offboarding — Controlador web para gestión de salida de empleados.

Reemplaza la funcionalidad actual de termination.py y liquidacion.py
con un flujo estructurado de 12 estados, aprobaciones, SOD y checklist.
"""

import io
from datetime import datetime, timezone
from collections import Counter
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role,
)
from app.services import hr_data_service as hr
from app.services.offboarding_service import OffboardingService
from app.services.payroll_audit_service import log_action
from app.models.offboarding import OFFBOARDING_STATES
from app.services.liquidacion_service import LiquidacionService
from app.services.recurring_service import get_recurring_movements


# ── Helpers ────────────────────────────────────────────────────────────────

def _service():
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    return OffboardingService(owner_uid, sandbox), owner_uid, sandbox


def _user():
    return session.get("user", {})


def _email():
    return _user().get("email", "")


def _role():
    return _user().get("role", "")


def _ctx(**kw):
    kw.setdefault("active_page", "rrhh_employees")
    kw.setdefault("states", OFFBOARDING_STATES)
    return kw


# ── Dashboard ───────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/dashboard")
def offboarding_dashboard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()

    all_requests = svc.list_requests(limit=500)
    today = datetime.now(timezone.utc)

    active = [r for r in all_requests if r.get("status") not in ("completed", "cancelled", "rejected")]
    completed = [r for r in all_requests if r.get("status") == "completed"]

    total_cost = 0.0
    for r in completed:
        if r.get("settlementId"):
            s = svc.get_settlement(r["settlementId"])
            if s:
                total_cost += float(s.get("montoNetoAPagar", 0) or 0)

    month_active = [r for r in active if (r.get("createdAt") or "").startswith(today.strftime("%Y-%m"))]
    this_month_completed = [r for r in completed if (r.get("closedAt") or "").startswith(today.strftime("%Y-%m"))]

    from collections import Counter
    reasons = Counter(r.get("terminationType", "otro") for r in all_requests if r.get("terminationType"))
    reason_labels = list(reasons.keys())
    reason_data = list(reasons.values())

    monthly_trend = {}
    for r in completed:
        key = (r.get("closedAt") or "")[:7]
        if key:
            monthly_trend[key] = monthly_trend.get(key, 0) + 1
    trend_labels = sorted(monthly_trend.keys())
    trend_data = [monthly_trend[k] for k in trend_labels]

    type_cost = {}
    for r in completed:
        if r.get("settlementId"):
            s = svc.get_settlement(r["settlementId"])
            if s:
                t = r.get("terminationType", "otro")
                type_cost[t] = type_cost.get(t, 0) + float(s.get("montoNetoAPagar", 0) or 0)
    cost_labels = list(type_cost.keys())
    cost_data = [round(type_cost[k], 2) for k in cost_labels]

    status_count = Counter(r.get("status", "") for r in all_requests if r.get("status"))
    pipeline = [
        {"key": k, "count": v}
        for k, v in status_count.most_common()
    ]

    return render_template("rrhh/offboarding/dashboard.html",
                           active_page="rrhh_offboarding",
                           active_count=len(active),
                           completed_count=len(completed),
                           total_cost=total_cost,
                           month_active=len(month_active),
                           this_month_completed=len(this_month_completed),
                           total_requests=len(all_requests),
                           reason_labels=reason_labels,
                           reason_data=reason_data,
                           trend_labels=trend_labels,
                           trend_data=trend_data,
                           cost_labels=cost_labels,
                           cost_data=cost_data,
                           pipeline=pipeline,
                           recent=all_requests[:10],
                           states=OFFBOARDING_STATES,
                           )


# ── List ───────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding")
def offboarding_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    status_filter = request.args.get("status", "")
    search = request.args.get("search", "").strip().lower()
    requests = svc.list_requests()

    if search:
        requests = [r for r in requests
                    if search in (r.get("employeeName", "") or "").lower()
                    or search in (r.get("requestNumber", "") or "").lower()
                    or search in (r.get("id", "") or "").lower()]

    if status_filter:
        requests = [r for r in requests if r.get("status") == status_filter]

    total = len(requests)
    all_requests = svc.list_requests()
    counts = Counter(r.get("status", "") for r in all_requests)

    pending_statuses = {"pending_supervisor_approval", "pending_hr_approval", "approved",
                        "pending_settlement", "pending_assets", "pending_payment",
                        "pending_documents", "pending_tss"}
    summary = {
        "total": total,
        "pending": sum(1 for r in requests if r.get("status") in pending_statuses),
        "completed": sum(1 for r in requests if r.get("status") == "completed"),
        "cancelled": sum(1 for r in requests if r.get("status") == "cancelled"),
    }

    return render_template("rrhh/offboarding_list.html",
                           **_ctx(requests=requests, status_filter=status_filter,
                                  search=search, total=total, counts=dict(counts),
                                  summary=summary,
                                  active_page="rrhh_offboarding"))


# ── Create ─────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/new", methods=["GET", "POST"])
def offboarding_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()

    if request.method == "POST":
        employee_id = request.form.get("employeeId", "").strip()
        employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
        if not employee:
            flash("Empleado no encontrado.", "error")
            return redirect(url_for("web_rrhh.offboarding_new"))

        if employee.get("status") != "activo":
            flash("El empleado ya está inactivo.", "warning")
            return redirect(url_for("web_rrhh.offboarding_list"))

        data = {
            "employeeId": employee_id,
            "employeeName": employee.get("fullName", ""),
            "cedula": employee.get("cedula", ""),
            "departmentId": employee.get("departmentId", ""),
            "positionId": employee.get("positionId", ""),
            "supervisorId": employee.get("supervisorId", ""),
            "requestDate": request.form.get("requestDate", "").strip(),
            "effectiveDate": request.form.get("effectiveDate", "").strip(),
            "lastWorkDate": request.form.get("lastWorkDate", "").strip(),
            "terminationType": request.form.get("terminationType", "renuncia_voluntaria").strip(),
            "terminationReason": request.form.get("terminationReason", "").strip(),
            "detailedReason": request.form.get("detailedReason", "").strip(),
            "initiatedBy": _email(),
            "initiatedByRole": _role(),
            "noticePeriodDays": int(request.form.get("noticePeriodDays", "0") or 0),
        }

        req = svc.create_request(data, _email())
        svc.init_checklist(req.id, employee_id)

        flash("Solicitud de offboarding creada exitosamente.", "success")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=req.id))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    active_employees = [e for e in employees if e.get("status") == "activo"]
    preselected_id = request.args.get("employee_id", "")
    return render_template("rrhh/offboarding_form.html",
                           **_ctx(employees=active_employees, request_data=None,
                                  preselected_id=preselected_id,
                                  active_page="rrhh_offboarding"))


# ── Edit ────────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/edit", methods=["GET", "POST"])
def offboarding_edit(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    if req.get("status") not in ("draft",):
        flash("Solo se puede editar una solicitud en estado Borrador.", "warning")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    if request.method == "POST":
        update_fields = [
            "terminationType", "terminationReason", "detailedReason",
            "effectiveDate", "lastWorkDate", "noticePeriodDays",
        ]
        for field in update_fields:
            val = request.form.get(field)
            if val is not None:
                if field == "noticePeriodDays":
                    req[field] = int(val) if val else 0
                else:
                    req[field] = val.strip() if val else ""

        req["updatedBy"] = _email()
        svc.save_request_raw(request_id, req, _email())
        svc.save_version(request_id, req, _email(), reason="Edición de solicitud")

        flash("Solicitud actualizada.", "success")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    active_employees = [e for e in employees if e.get("status") == "activo"]
    return render_template("rrhh/offboarding_form.html",
                           **_ctx(employees=active_employees, request_data=req,
                                  preselected_id=req.get("employeeId", ""),
                                  is_edit=True, active_page="rrhh_offboarding"))


# ── Cancel ──────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/cancel", methods=["POST"])
def offboarding_cancel(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    terminal = ("completed", "cancelled", "rejected")
    if req.get("status") in terminal:
        flash("La solicitud ya está en un estado terminal.", "warning")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    reason = request.form.get("reason", "").strip() or "Cancelación solicitada"
    try:
        svc.transition(request_id, "cancelled", _email(), _role(), reason)
        flash("Solicitud cancelada.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


# ── Detail ─────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>")
def offboarding_detail(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    tab = request.args.get("tab", "overview")
    extra = {}

    if tab == "settlement":
        if req.get("settlementId"):
            extra["settlement"] = svc.get_settlement(req["settlementId"])
        extra["employee"] = hr.get_employee(owner_uid, req.get("employeeId", ""), sandbox=sandbox)

    elif tab == "checklist":
        if req.get("checklistId"):
            extra["checklist"] = svc.get_checklist(req["checklistId"])

    elif tab == "documents":
        extra["documents"] = svc.get_documents(request_id)

    elif tab == "payment":
        extra["payments"] = svc.get_payments(request_id)

    elif tab == "interview":
        extra["interviews"] = svc.get_interviews(request_id)
        extra["interviews"] = svc.get_interviews(request_id)

    elif tab == "risk":
        ra_id = req.get("riskAssessmentId")
        if ra_id:
            extra["risk"] = svc.get_risk_assessment(ra_id)

    elif tab == "legal":
        lc_id = req.get("legalCaseId")
        if lc_id:
            extra["legal"] = svc.get_legal_case(lc_id)

    transitions = svc.allowed_transitions(req.get("status", ""))
    extra["allowed_transitions"] = transitions

    return render_template("rrhh/offboarding_detail.html",
                           **_ctx(req=req, tab=tab, active_page="rrhh_offboarding",
                                  **extra))


# ── Transition (POST) ─────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/transition", methods=["POST"])
def offboarding_transition(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()

    new_status = request.form.get("newStatus", "").strip()
    comment = request.form.get("comment", "").strip()

    try:
        old_req = svc.get_request(request_id)
        old_status = old_req.get("status", "") if old_req else ""
        svc.transition(request_id, new_status, _email(), _role(), comment)

        from app.services.offboarding_notifications import notify_transition
        from flask import current_app
        app = current_app._get_current_object()
        if app:
            req_data = svc.get_request(request_id)
            notify_transition(app, owner_uid, sandbox, req_data or {},
                              old_status, new_status, _email())
            if old_status == "pending_hr_approval" and new_status == "pending_settlement":
                notify_transition(app, owner_uid, sandbox, req_data or {},
                                  "pending_hr_approval", "approved", _email())

        flash(f"Solicitud actualizada a: {OFFBOARDING_STATES.get(new_status, {}).get('label', new_status)}", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


# ── Approval (POST) ──────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/approve", methods=["POST"])
def offboarding_approve(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()

    decision = request.form.get("decision", "").strip()
    comment = request.form.get("comment", "").strip()
    level = int(request.form.get("level", "1") or 1)

    svc.add_approval(request_id, _email(),
                     _user().get("name", _email()),
                     _role(), decision, comment, level)

    flash(f"Decisión registrada: {decision}", "success")
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


# ── Access Revocation (POST) ───────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/revoke-access", methods=["POST"])
def offboarding_revoke_access(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()

    revoke = request.form.get("action") == "revoke"
    try:
        svc.revoke_access(request_id, _email(), revoke=revoke)
        if revoke:
            flash("Accesos del empleado desactivados.", "success")
            from app.services.offboarding_notifications import notify_transition
            from flask import current_app
            app = current_app._get_current_object()
            if app:
                req_data = svc.get_request(request_id)
                notify_transition(app, owner_uid, sandbox, req_data or {},
                                  "", "access_revoked", _email())
        else:
            flash("Desactivación de accesos revertida.", "info")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


# ── Calculate Settlement (AJAX + POST) ────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/settlement/calculate", methods=["POST"])
def offboarding_settlement_calculate(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    employee = hr.get_employee(owner_uid, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    termination_date = req.get("effectiveDate", "")
    hire_date = employee.get("hireDate", "")
    base_salary = float(employee.get("baseSalary", 0) or 0)
    salary_frequency = employee.get("paymentFrequency", "") or "mensual"
    termination_type = req.get("terminationType", "renuncia_voluntaria")

    preaviso_trabajado = request.form.get("preavisoTrabajado") == "on"
    vacation_pending_complete = int(request.form.get("vacationPendingCompleteYears", "0") or 0)
    vacation_taken_current = int(request.form.get("vacationTakenCurrentPeriod", "0") or 0)

    salaries_12 = [base_salary]
    try:
        salary_history = hr.get_salary_history(owner_uid, req.get("employeeId", ""), sandbox=sandbox)
        if salary_history:
            recent = sorted(salary_history, key=lambda x: x.get("effectiveDate", ""), reverse=True)[:12]
            salaries_12 = [s.get("amount", base_salary) for s in recent if s.get("amount")]
            if not salaries_12:
                salaries_12 = [base_salary]
    except Exception:
        salaries_12 = [base_salary]

    from datetime import datetime
    try:
        td = datetime.strptime(termination_date, "%Y-%m-%d") if termination_date else datetime.now()
        months_ytd = td.month
    except ValueError:
        months_ytd = datetime.now().month
    salaries_ytd = [base_salary] * max(1, months_ytd)

    employee_id = req.get("employeeId", "")
    recurring_movements = get_recurring_movements(owner_uid, employee_id=employee_id, sandbox=sandbox)

    result = LiquidacionService.calcular_liquidacion(
        employee_id=employee_id,
        employee_name=employee.get("fullName", ""),
        cedula=employee.get("cedula", ""),
        hire_date=hire_date,
        termination_date=termination_date,
        termination_type=termination_type,
        last_base_salary=base_salary,
        salary_frequency=salary_frequency,
        monthly_salaries_last_12=salaries_12,
        monthly_salaries_ytd=salaries_ytd,
        preaviso_trabajado=preaviso_trabajado,
        vacation_pending_complete_years=vacation_pending_complete,
        vacation_taken_current_period=vacation_taken_current,
        recurring_movements=recurring_movements,
        notes=request.form.get("notes", ""),
        created_by=_email(),
    )

    totales = result.get("totales", {})

    settlement_data = {
        "requestId": request_id,
        "employeeId": employee_id,
        "hireDate": hire_date,
        "terminationDate": termination_date,
        "terminationType": termination_type,
        "baseSalary": base_salary,
        "salaryFrequency": salary_frequency,
        "monthlySalariesLast12": salaries_12,
        "monthlySalariesYTD": salaries_ytd,
        "preavisoTrabajado": preaviso_trabajado,
        "vacationPendingCompleteYears": vacation_pending_complete,
        "vacationTakenCurrentPeriod": vacation_taken_current,
        "conceptos": result.get("conceptos", {}),
        "totales": totales,
        "antiguedad": result.get("antiguedad", {}),
        "salarioDiarioPromedio": totales.get("salarioDiarioPromedio", 0),
        "salarioPendiente": totales.get("salarioPendiente", 0),
        "comisionesPendientes": 0.0,
        "bonificacionesPendientes": 0.0,
        "horasExtrasPendientes": 0.0,
        "loanDeductions": totales.get("loanDeductions", 0),
        "advanceDeductions": totales.get("advanceDeductions", 0),
        "otherDeductions": totales.get("otherDeductions", 0),
        "descuentos": totales.get("montoDescuentos", 0),
        "montoNetoAPagar": totales.get("montoNetoAPagar", 0),
        "status": "calculada",
    }

    settlement_id = svc.save_settlement(settlement_data, _email())
    flash("Liquidación calculada y guardada.", "success")
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="settlement"))


# ── Approve Settlement ────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/settlement/approve", methods=["POST"])
def offboarding_settlement_approve(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    s_id = request.form.get("settlementId", "")
    comment = request.form.get("comment", "")
    if s_id:
        svc.approve_settlement(s_id, _email(), comment)
        flash("Liquidación aprobada.", "success")
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="settlement"))


# ── Checklist (POST) ──────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/checklist/toggle", methods=["POST"])
def offboarding_checklist_toggle(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    checklist_id = request.form.get("checklistId", "")
    item_id = request.form.get("itemId", "")
    completed = request.form.get("completed") == "1"

    updates = {"completed": completed}
    signed_employee = request.form.get("signedByEmployee")
    signed_hr = request.form.get("signedByHR")
    if signed_employee is not None:
        updates["signedByEmployee"] = signed_employee == "1"
    if signed_hr is not None:
        updates["signedByHR"] = signed_hr == "1"
    notes = request.form.get("notes")
    if notes is not None:
        updates["notes"] = notes

    svc.update_checklist_item(checklist_id, item_id, updates, _email())
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="checklist"))


# ── Interview (POST) ──────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/interview", methods=["POST"])
def offboarding_interview(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)

    data = {
        "requestId": request_id,
        "employeeId": req.get("employeeId", ""),
        "interviewDate": request.form.get("interviewDate", "").strip(),
        "interviewerName": request.form.get("interviewerName", "").strip(),
        "interviewerEmail": request.form.get("interviewerEmail", _email()),
        "primaryReason": request.form.get("primaryReason", "").strip(),
        "secondaryReasons": request.form.getlist("secondaryReasons"),
        "workEnvironment": int(request.form.get("workEnvironment", 3)),
        "compensation": int(request.form.get("compensation", 3)),
        "management": int(request.form.get("management", 3)),
        "growth": int(request.form.get("growth", 3)),
        "workLifeBalance": int(request.form.get("workLifeBalance", 3)),
        "whatWentWell": request.form.get("whatWentWell", "").strip(),
        "whatCouldImprove": request.form.get("whatCouldImprove", "").strip(),
        "wouldReturn": request.form.get("wouldReturn") == "1",
        "wouldRecommend": request.form.get("wouldRecommend") == "1",
        "recommendations": request.form.get("recommendations", "").strip(),
    }

    svc.save_interview(data, _email())
    flash("Entrevista de salida guardada.", "success")
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="interview"))


# ── Register Payment ──────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/payment", methods=["POST"])
def offboarding_payment(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()

    data = {
        "requestId": request_id,
        "paymentMethod": request.form.get("paymentMethod", "payroll").strip(),
        "paymentDate": request.form.get("paymentDate", "").strip(),
        "paymentReference": request.form.get("paymentReference", "").strip(),
        "totalAmount": float(request.form.get("totalAmount", "0") or 0),
        "bankName": request.form.get("bankName", "").strip(),
        "accountNumber": request.form.get("accountNumber", "").strip(),
        "transferReference": request.form.get("transferReference", "").strip(),
        "notes": request.form.get("notes", "").strip(),
        "approvedBy": _email(),
        "approvedAt": "",
    }

    svc.save_payment(data, _email())
    flash("Pago registrado.", "success")
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="payment"))


# ── Risk Assessment (POST) ────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/risk", methods=["POST"])
def offboarding_risk(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()

    data = {
        "requestId": request_id,
        "riskLevel": request.form.get("riskLevel", "low").strip(),
        "riskScore": int(request.form.get("riskScore", "0") or 0),
        "recommendedActions": request.form.getlist("recommendedActions"),
        "reviewNotes": request.form.get("reviewNotes", "").strip(),
    }

    ra_id = svc.save_risk_assessment(data, _email())
    req = svc.get_request(request_id)
    if req:
        req["riskAssessmentId"] = ra_id
        svc.save_request_raw(request_id, req, _email())

    flash("Evaluación de riesgo guardada.", "success")
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="risk"))


# ── Signed Document Upload/Download ────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/documents/upload", methods=["POST"])
def offboarding_upload_document(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    doc_type = request.form.get("documentType", "").strip()
    notes = request.form.get("notes", "").strip()
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debes seleccionar un archivo.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="documents"))

    import base64, uuid
    content = base64.b64encode(file.read()).decode("utf-8")
    max_size = 10 * 1024 * 1024
    if len(content) > max_size * 1.4:
        flash("El archivo excede el tamaño máximo de 10MB.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="documents"))

    doc_id = str(uuid.uuid4())
    doc_data = {
        "id": doc_id,
        "requestId": request_id,
        "documentType": doc_type or "other",
        "title": file.filename,
        "fileUrl": f"data:application/pdf;base64,{content}",
        "fileSize": len(content),
        "mimeType": file.content_type or "application/pdf",
        "notes": notes,
        "uploadedBy": _email(),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
        "signedByEmployee": request.form.get("signedByEmployee") == "1",
        "signedByEmployer": request.form.get("signedByEmployer") == "1",
        "generatedBy": _email(),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    svc.save_document(doc_data, _email())
    flash("Documento firmado subido exitosamente.", "success")
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="documents"))


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/documents/<doc_id>/download")
def offboarding_download_document(request_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    docs = svc.get_documents(request_id)
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if not doc or not doc.get("fileUrl"):
        flash("Documento no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="documents"))

    import base64
    raw = doc["fileUrl"]
    if raw.startswith("data:"):
        _, b64 = raw.split(",", 1)
    else:
        b64 = raw
    try:
        pdf_bytes = base64.b64decode(b64)
    except Exception:
        flash("Error al decodificar el documento.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="documents"))

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype=doc.get("mimeType", "application/pdf"),
        as_attachment=True,
        download_name=doc.get("title", f"documento_{doc_id[:8]}.pdf"),
    )


# ── Rehire ──────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/rehire", methods=["GET", "POST"])
def offboarding_rehire(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    if request.method == "POST":
        new_employee_id = request.form.get("newEmployeeId", "").strip()
        new_hire_date = request.form.get("newHireDate", "").strip()
        new_position = request.form.get("newPosition", "").strip()
        new_department = request.form.get("newDepartment", "").strip()
        new_salary = float(request.form.get("newSalary", "0") or 0)
        preserves_seniority = request.form.get("preservesSeniority") == "1"
        continuous_date = request.form.get("continuousSeniorityDate", "").strip()

        data = {
            "originalRequestId": request_id,
            "originalEmployeeId": req.get("employeeId", ""),
            "newEmployeeId": new_employee_id,
            "newHireDate": new_hire_date,
            "newPosition": new_position,
            "newDepartment": new_department,
            "newSalary": new_salary,
            "preservesSeniority": preserves_seniority,
            "previousSeniorityDays": 0,
            "continuousSeniorityDate": continuous_date if preserves_seniority else "",
            "status": "approved",
            "approvedBy": _email(),
            "approvedAt": datetime.now(timezone.utc).isoformat(),
        }

        rehire_id = svc.save_rehire(data, _email())
        req["rehireId"] = rehire_id
        svc.save_request_raw(request_id, req, _email())

        if new_employee_id:
            new_emp = hr.get_employee(owner_uid, new_employee_id, sandbox=sandbox)
            if new_emp:
                new_emp["status"] = "activo"
                new_emp["hireDate"] = new_hire_date or new_emp.get("hireDate", "")
                new_emp["position"] = new_position or new_emp.get("position", "")
                new_emp["departmentId"] = new_department or new_emp.get("departmentId", "")
                if new_salary > 0:
                    new_emp["baseSalary"] = new_salary
                hr.save_employee(owner_uid, new_employee_id, new_emp, sandbox=sandbox)
                log_action(owner_uid, "rehire", "employee", new_employee_id,
                           _email(), {"offboardingId": request_id}, sandbox=sandbox)
                flash("Empleado recontratado exitosamente.", "success")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="overview"))

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    return render_template("rrhh/offboarding/rehire_form.html",
                           **_ctx(req=req, employees=employees,
                                  active_page="rrhh_offboarding"))


# ── PDF Generation ─────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/pdf/letter")
def offboarding_pdf_letter(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    employee = hr.get_employee(owner_uid, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    try:
        from app.services.offboarding_document_service import generate_termination_letter, _company_data
        from app.models.offboarding import SettlementStatus
        company = _company_data(owner_uid, sandbox)

        settlement_completed = False
        settlement_id = req.get("settlementId", "")
        if settlement_id:
            settlement = svc.get_settlement(settlement_id)
            if settlement and settlement.get("status") == SettlementStatus.PAGADA.value:
                settlement_completed = True

        pdf_bytes = generate_termination_letter(
            req, employee, company, request.host_url,
            settlement_completed=settlement_completed,
        )
        filename = f"carta_desvinculacion_{request_id[:8]}.pdf"
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"Error generando PDF carta desvinculación: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/pdf/settlement")
def offboarding_pdf_settlement(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    settlement = None
    if req.get("settlementId"):
        settlement = svc.get_settlement(req["settlementId"])
    if not settlement:
        flash("Liquidación no encontrada. Calcule la liquidación primero.", "warning")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="settlement"))

    employee = hr.get_employee(owner_uid, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    try:
        from app.services.offboarding_document_service import generate_settlement_acta, _company_data
        from app.models.offboarding import SettlementStatus
        company = _company_data(owner_uid, sandbox)

        settlement_completed = settlement.get("status") == SettlementStatus.PAGADA.value if settlement else False

        pdf_bytes = generate_settlement_acta(
            req, settlement, employee, company, request.host_url,
            settlement_completed=settlement_completed,
        )
        filename = f"acta_liquidacion_{request_id[:8]}.pdf"
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"Error generando PDF acta liquidación: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


# ── TSS Notification ───────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/tss/download")
def offboarding_tss_download(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    employee = hr.get_employee(owner_uid, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    try:
        from app.services.offboarding_tss_service import generate_tss_baja, get_tss_baja_filename
        from app.services.db_service import DatabaseService
        profile = DatabaseService.get_company_profile(owner_uid) or {}
        company_rnc = profile.get("rnc", "")

        content = generate_tss_baja(req, employee, company_rnc)
        filename = get_tss_baja_filename(company_rnc)

        if not req.get("tssNotifiedAt"):
            req["tssNotifiedAt"] = datetime.now(timezone.utc).isoformat()
            svc.save_request_raw(request_id, req, _email())

        return send_file(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/plain",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        print(f"Error generando archivo TSS: {e}")
        flash("Error al generar la notificación TSS.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


# ── Migration (admin) ──────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/migrate", methods=["POST"])
def offboarding_migrate():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    if not _is_hr_role():
        flash("Solo RRHH puede ejecutar la migración.", "error")
        return redirect(url_for("web_rrhh.offboarding_dashboard"))

    dry_run = request.form.get("dry_run") == "1"
    try:
        from app.services.offboarding_migration import migrate_inactive_employees
        stats = migrate_inactive_employees(owner_uid, sandbox=sandbox,
                                           user_email=_email(), dry_run=dry_run)
        if dry_run:
            flash(f"Dry-run: {stats['migrated']} empleados se migrarían, "
                  f"{stats['already_migrated']} ya migrados, "
                  f"{stats['skipped_no_date']} sin fecha, {stats['errors']} errores.", "info")
        else:
            flash(f"Migración completada: {stats['migrated']} migrados, "
                  f"{stats['already_migrated']} ya existentes, "
                  f"{stats['skipped_no_date']} sin fecha, {stats['errors']} errores.", "success")
    except Exception as e:
        flash(f"Error en migración: {e}", "error")
    return redirect(url_for("web_rrhh.offboarding_dashboard"))


# ── Fix Employee Status (admin) ─────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/fix-status", methods=["POST"])
def offboarding_fix_status():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    if not _is_hr_role():
        flash("Solo RRHH puede ejecutar esta acción.", "error")
        return redirect(url_for("web_rrhh.offboarding_dashboard"))

    dry_run = request.form.get("dry_run") == "1"
    svc = OffboardingService(owner_uid, sandbox)
    all_requests = svc.list_requests(limit=1000)
    completed = [r for r in all_requests if r.get("status") == "completed"]

    fixed = 0
    skipped = 0
    errors = 0
    details = []

    for req in completed:
        emp_id = req.get("employeeId", "")
        if not emp_id:
            skipped += 1
            continue
        try:
            emp = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
            if not emp:
                details.append(f"{req.get('employeeName','?')}: empleado no encontrado")
                errors += 1
                continue
            if emp.get("status") == "inactivo":
                skipped += 1
                continue
            if not dry_run:
                emp["status"] = "inactivo"
                emp["terminationDate"] = req.get("effectiveDate", "")
                emp["terminationType"] = req.get("terminationType", "")
                hr.save_employee(owner_uid, emp_id, emp, sandbox=sandbox)
                log_action(owner_uid, "employee_marked_inactive", "employee",
                           emp_id, _email(),
                           {"offboardingId": req.get("id", ""),
                            "terminationType": req.get("terminationType", "")},
                           sandbox=sandbox)
            fixed += 1
            details.append(f"{emp.get('fullName','?')}: {'✅ listo' if not dry_run else '🔍 se corregiría'}")
        except Exception as e:
            details.append(f"{req.get('employeeName','?')}: error {e}")
            errors += 1

    if dry_run:
        flash(f"Dry-run: {fixed} empleados se corregirían, {skipped} ya inactivos, {errors} errores.", "info")
    else:
        flash(f"Corregidos: {fixed} empleados marcados como inactivos, {skipped} ya inactivos, {errors} errores.", "success")

    return redirect(url_for("web_rrhh.offboarding_dashboard"))


# ── Legal Case ──────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/legal", methods=["POST"])
def offboarding_legal_save(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    data = {
        "requestId": request_id,
        "employeeId": req.get("employeeId", ""),
        "hasLawsuit": request.form.get("hasLawsuit") == "1",
        "lawsuitStatus": request.form.get("lawsuitStatus", "").strip(),
        "lawsuitDetails": request.form.get("lawsuitDetails", "").strip(),
        "lawsuitNumber": request.form.get("lawsuitNumber", "").strip(),
        "lawsuitCourt": request.form.get("lawsuitCourt", "").strip(),
        "lawsuitDate": request.form.get("lawsuitDate", "").strip(),
        "legalCounselName": request.form.get("legalCounselName", "").strip(),
        "legalCounselEmail": request.form.get("legalCounselEmail", "").strip(),
        "resolutionDate": request.form.get("resolutionDate", "").strip(),
        "resolutionAmount": float(request.form.get("resolutionAmount", "0") or 0),
        "resolutionNotes": request.form.get("resolutionNotes", "").strip(),
    }

    existing_id = req.get("legalCaseId")
    if existing_id:
        data["id"] = existing_id
        existing = svc.get_legal_case(existing_id)
        if existing:
            data["createdAt"] = existing.get("createdAt")
            data["createdBy"] = existing.get("createdBy")

    lc_id = svc.save_legal_case(data, _email())

    if not req.get("legalCaseId"):
        req["legalCaseId"] = lc_id
        svc.save_request_raw(request_id, req, _email())
        svc.save_version(request_id, req, _email(), reason="Caso legal creado")

    flash("Caso legal guardado exitosamente.", "success")
    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="legal"))


# ── API: get employee data for settlement ─────────────────────────────────

@web_rrhh_bp.route("/api/rrhh/offboarding/<request_id>/employee-data")
def offboarding_employee_data(request_id):
    if _login_required():
        return {"error": "No autorizado"}, 401
    svc, owner_uid, sandbox = _service()
    req = svc.get_request(request_id)
    if not req:
        return {"error": "No encontrada"}, 404
    employee = hr.get_employee(owner_uid, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        return {"error": "Empleado no encontrado"}, 404
    return jsonify({
        "hireDate": employee.get("hireDate", ""),
        "baseSalary": employee.get("baseSalary", 0),
        "paymentFrequency": employee.get("paymentFrequency", "mensual"),
        "fullName": employee.get("fullName", ""),
        "cedula": employee.get("cedula", ""),
    })
