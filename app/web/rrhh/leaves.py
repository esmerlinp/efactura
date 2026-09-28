"""RRHH module — auto-extracted."""

import uuid
from datetime import date, datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


LEAVE_TYPE_LABELS = {
    "licencia_medica": "Licencia Médica",
    "enfermedad": "Licencia Médica",
    "permiso_personal": "Permiso Personal",
    "maternidad": "Maternidad",
    "paternidad": "Paternidad",
    "luto": "Luto",
    "estudios": "Estudios",
    "voluntaria": "Licencia Voluntaria",
    "discapacidad": "Lic. Discapacidad",
    "sindical": "Sindical",
    "otro": "Otro",
}


# ═══════════════════════════════════════════════════════════════════════════
# PERMISOS / LICENCIAS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/leaves")
def leave_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    # Auto-sanación: sincronizar estados antes de mostrar (idempotente)
    try:
        from app.services.employee_status_service import EmployeeStatusService
        EmployeeStatusService.sync_employee_statuses(company_id, sandbox=sandbox,
                                                     actor="Sistema (auto-sync)")
    except Exception:
        pass

    requests = hr.get_leave_requests(company_id, sandbox=sandbox)
    requests.sort(key=lambda r: r.get("startDate", "") or r.get("createdDate", ""),
                  reverse=True)

    today_iso = date.today().isoformat()

    def _in_range(r):
        return (r.get("status") == "aprobada"
                and r.get("startDate", "") <= today_iso <= r.get("endDate", ""))

    def _concluida(r):
        return (r.get("status") == "aprobada"
                and r.get("endDate", "") and r.get("endDate", "") < today_iso)

    status_counts = {
        "total": len(requests),
        "pendiente": sum(1 for r in requests if r.get("status") == "pendiente"),
        "en_curso": sum(1 for r in requests if _in_range(r)),
        "concluidas": sum(1 for r in requests if _concluida(r)),
        "rechazada": sum(1 for r in requests if r.get("status") == "rechazada"),
    }

    all_years = sorted({(r.get("startDate", "") or "")[:4]
                        for r in requests if r.get("startDate")}, reverse=True)
    all_types = sorted({(r.get("leaveType", "") or "").strip()
                        for r in requests if (r.get("leaveType", "") or "").strip()})

    # Filtros
    q = request.args.get("q", "").strip().lower()
    filter_status = request.args.get("status", "").strip()
    filter_year = request.args.get("year", "").strip()
    filter_type = request.args.get("type", "").strip()

    if q:
        requests = [r for r in requests
                    if q in (r.get("employeeName", "") or "").lower()]
    if filter_status == "en_curso":
        requests = [r for r in requests if _in_range(r)]
    elif filter_status == "concluidas":
        requests = [r for r in requests if _concluida(r)]
    elif filter_status:
        requests = [r for r in requests if r.get("status", "") == filter_status]
    if filter_year:
        requests = [r for r in requests
                    if (r.get("startDate", "") or "").startswith(filter_year)]
    if filter_type:
        requests = [r for r in requests
                    if (r.get("leaveType", "") or "").strip() == filter_type]

    filtered_total = len(requests)

    # Paginación
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(10, min(100000, int(request.args.get("per_page", 25))))
    except (TypeError, ValueError):
        page, per_page = 1, 25
    if filtered_total == 0:
        page, per_page = 1, 25
    elif per_page >= filtered_total:
        per_page = filtered_total
        page = 1
    total_pages = max(1, (filtered_total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    paged = requests[start:start + per_page]

    # Adjuntos solo de las solicitudes de la página visible
    import json as _json
    attachments_by_request = {}
    for r in paged:
        for a in hr.get_request_attachments(company_id, request_id=r.get("id"),
                                            request_type="leave", sandbox=sandbox):
            attachments_by_request.setdefault(a.get("requestId"), []).append({
                "id": a.get("id"),
                "name": a.get("name"),
                "size": a.get("size", 0),
                "uploadedAt": a.get("uploadedAt", ""),
                "download": url_for("web_rrhh.leave_attachment_download",
                                    request_id=a.get("requestId"), doc_id=a.get("id")),
                "delete": url_for("web_rrhh.leave_attachment_delete",
                                  request_id=a.get("requestId"), doc_id=a.get("id")),
            })

    return render_template("rrhh/leave_list.html", active_page="rrhh_leaves",
                           requests=paged, today=today_iso,
                           attachments_json=_json.dumps(attachments_by_request),
                           status_counts=status_counts, all_years=all_years,
                           all_types=all_types, leave_type_labels=LEAVE_TYPE_LABELS,
                           q=request.args.get("q", ""),
                           filter_status=filter_status, filter_year=filter_year,
                           filter_type=filter_type,
                           page=page, total_pages=total_pages,
                           filtered_total=filtered_total, per_page=per_page)


@web_rrhh_bp.route("/rrhh/leaves/new", methods=["GET", "POST"])
def leave_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    from app.utils.hr_utils import is_active_equivalent
    employees = [e for e in hr.get_employees(company_id, sandbox=sandbox)
                 if is_active_equivalent(e.get("status", ""))]

    if request.method == "POST":
        emp_id = request.form.get("employeeId", "")
        employee = hr.get_employee(company_id, emp_id, sandbox=sandbox)
        if not employee:
            flash("Empleado no encontrado.", "error")
            return redirect(url_for("web_rrhh.leave_list"))

        start_date = request.form.get("startDate", "")
        end_date = request.form.get("endDate", "")
        leave_type = request.form.get("leaveType", "otro")
        if leave_type == "maternidad" and start_date and not end_date:
            from datetime import timedelta
            end_date = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(weeks=14)).strftime("%Y-%m-%d")
        days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days + 1

        req_id = str(uuid.uuid4())
        _ctr_id = ""
        try:
            _act = hr.get_active_contract_for_employee(company_id, emp_id, sandbox=sandbox)
            _ctr_id = (_act.get("id", "") if _act else hr.resolve_employee_contract_id(employee))
        except Exception:
            _ctr_id = hr.resolve_employee_contract_id(employee)
        hr.save_leave_request(company_id, req_id, {
            "id": req_id,
            "employeeId": emp_id,
            "contractId": _ctr_id,
            "employeeName": employee.get("fullName", ""),
            "leaveType": request.form.get("leaveType", "otro"),
            "startDate": start_date,
            "endDate": end_date,
            "days": days,
            "status": "pendiente",
            "notes": request.form.get("notes", "").strip(),
            "paidByPayroll": request.form.get("paidByPayroll") == "on",
        }, sandbox=sandbox)

        from app.web.rrhh.request_attachments import save_uploaded_files
        save_uploaded_files(company_id, req_id, "leave", sandbox)

        try:
            from app.services.payroll_audit_service import log_employee_action
            log_employee_action(
                company_id, emp_id, "leave_request_created",
                comment=f"Licencia {request.form.get('leaveType', 'otro')}: {days} días",
                changes={
                    "leaveType": request.form.get("leaveType", "otro"),
                    "startDate": start_date, "endDate": end_date, "days": days,
                },
                user_email=session.get("user", {}).get("email", ""), sandbox=sandbox,
            )
        except Exception as e:
            print(f"⚠️ leaves.log_employee_action: {e}")

        flash("Permiso registrado.", "success")
        return redirect(url_for("web_rrhh.leave_list"))

    return render_template("rrhh/leave_form.html", active_page="rrhh_leaves", employees=employees)


@web_rrhh_bp.route("/rrhh/leaves/<request_id>/<action>", methods=["POST"])
def leave_action(request_id, action):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    req = hr.get_leave_request(company_id, request_id, sandbox=sandbox)
    if not req:
        flash("Permiso no encontrado.", "error")
        return redirect(url_for("web_rrhh.leave_list"))

    if action in ("approve", "rechazar"):
        req["status"] = "aprobada" if action == "approve" else "rechazada"
        req["approvedBy"] = session["user"].get("email", "")
        hr.save_leave_request(company_id, request_id, req, sandbox=sandbox)

        try:
            from app.services.payroll_audit_service import log_employee_action
            log_employee_action(
                company_id, req.get("employeeId", ""),
                "leave_approved" if action == "approve" else "leave_rejected",
                comment=f"Licencia {req.get('leaveType', 'otro')} {req.get('days', 0)} días "
                        f"({req.get('startDate', '')} → {req.get('endDate', '')})",
                changes={"requestId": request_id, "status": req["status"],
                         "leaveType": req.get("leaveType", "otro"),
                         "days": req.get("days", 0)},
                user_email=req["approvedBy"], sandbox=sandbox,
            )
        except Exception as e:
            print(f"⚠️ leaves.log_employee_action (action): {e}")

        if action == "approve":
            try:
                employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
                if employee:
                    from app.services.hr_notifications import notify_leave_approved
                    notify_leave_approved(employee, req)
                    # Regla: licencia gana — revocar vacaciones solapadas y
                    # sincronizar el estado (si está en rango → "licencia").
                    from app.services.employee_status_service import EmployeeStatusService
                    revoked = EmployeeStatusService.revoke_overlapping_vacations(
                        company_id, req, actor=session["user"].get("email", ""),
                        sandbox=sandbox)
                    if revoked:
                        flash(f"{len(revoked)} vacación(es) solapada(s) revocada(s) "
                              f"y días devueltos al balance.", "info")
                    EmployeeStatusService.sync_employee(
                        company_id, employee.get("id", ""), sandbox=sandbox,
                        actor=session["user"].get("email", ""))
            except Exception:
                pass

        flash(f"Permiso {'aprobado' if action == 'approve' else 'rechazado'}.", "success")

    return redirect(url_for("web_rrhh.leave_list"))


