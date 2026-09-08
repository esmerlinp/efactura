"""RRHH Offboarding — Controlador web para gestión de salida de empleados.

Reemplaza la funcionalidad actual de termination.py y liquidacion.py
con un flujo estructurado de 12 estados, aprobaciones, SOD y checklist.
"""

import io
import uuid
from datetime import datetime, timezone
from collections import Counter
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.utils import secure_filename
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
from app.utils.hr_utils import is_active_equivalent


# ── Helpers ────────────────────────────────────────────────────────────────

def _service():
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    offboarding_mode = "simple"
    return OffboardingService(company_id, sandbox, offboarding_mode=offboarding_mode), owner_uid, sandbox, company_id


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


# ── Gate de autorización (modo simple) ────────────────────────────────────

def _has_termination_rule(company_id: str, sandbox: bool) -> bool:
    """True si existe una regla de autorización activa para desvinculación."""
    try:
        rules = hr.get_authorization_rules(company_id, sandbox=sandbox)
    except Exception:
        return False
    return any(
        r.get("docType") == "termination"
        and r.get("isActive", True)
        and r.get("approvers")
        for r in (rules or [])
    )


def _prestaciones_metadata(settlement: dict, req: dict) -> dict:
    """Construye el resumen de prestaciones para la solicitud de autorización.

    El metadata viaja con la autorización para que quien apruebe tenga el
    esquema completo (totales, conceptos que aplican, antigüedad) sin tener
    que abrir el wizard, y pueda devolver para corrección si es necesario.
    """
    settlement = settlement or {}
    req = req or {}
    totales = settlement.get("totales", {}) or {}
    antigen = settlement.get("antiguedad", {}) or {}
    conceptos_src = settlement.get("conceptos", {}) or {}
    conceptos = []
    for key, c in (conceptos_src.items() if isinstance(conceptos_src, dict) else []):
        if not isinstance(c, dict) or not c.get("aplica"):
            continue
        try:
            conceptos.append({
                "key": key,
                "monto": float(c.get("monto", 0) or 0),
                "dias": c.get("dias", 0) or 0,
                "baseLegal": c.get("baseLegal", "") or "",
            })
        except (TypeError, ValueError):
            continue
    adicionales = []
    for ac in (settlement.get("conceptosAdicionales", []) or []):
        if not isinstance(ac, dict):
            continue
        try:
            adicionales.append({
                "name": ac.get("name", "") or "",
                "type": ac.get("type", "") or "",
                "monto": float(ac.get("monto", 0) or 0),
                "comment": ac.get("comment", "") or "",
            })
        except (TypeError, ValueError):
            continue
    descuentos = []
    for d in (settlement.get("descuentosDetalle", []) or []):
        if not isinstance(d, dict):
            continue
        try:
            descuentos.append({
                "name": d.get("name", "") or "",
                "monto": float(d.get("monto", 0) or 0),
            })
        except (TypeError, ValueError):
            continue
    try:
        monto_total = float(totales.get("montoTotal", 0) or 0)
        monto_neto = float(totales.get("montoNetoAPagar", monto_total) or 0)
        monto_prest = float(totales.get("montoPrestaciones", 0) or 0)
        monto_der = float(totales.get("montoDerechosAdquiridos", 0) or 0)
        monto_desc = float(totales.get("montoDescuentos", 0) or 0)
        monto_exento = float(totales.get("montoExento", 0) or 0)
    except (TypeError, ValueError):
        monto_total = monto_neto = monto_prest = monto_der = monto_desc = monto_exento = 0.0
    try:
        sdp = float(settlement.get("salarioDiarioPromedio", 0) or 0)
    except (TypeError, ValueError):
        sdp = 0.0
    # Bloque de corrección: si esta versión nace de una reapertura, el
    # aprobador ve el motivo y los montos de la versión invalidada.
    correction = None
    corr = req.get("lastCorrection") or {}
    if isinstance(corr, dict) and corr:
        try:
            correction = {
                "reason": corr.get("reason", "") or "",
                "by": corr.get("by", "") or "",
                "at": corr.get("at", "") or "",
                "previousVersion": int(corr.get("previousVersion", 0) or 0),
                "previousTotal": float(corr.get("previousTotal", 0) or 0),
                "previousNeto": float(corr.get("previousNeto", 0) or 0),
            }
        except (TypeError, ValueError):
            correction = None
    return {
        "employeeName": req.get("employeeName", "") or "",
        "terminationType": settlement.get("terminationType", "") or req.get("terminationType", "") or "",
        "terminationDate": settlement.get("terminationDate", "") or req.get("effectiveDate", "") or "",
        "montoTotal": round(monto_total, 2),
        "montoNetoAPagar": round(monto_neto, 2),
        "montoPrestaciones": round(monto_prest, 2),
        "montoDerechosAdquiridos": round(monto_der, 2),
        "montoDescuentos": round(monto_desc, 2),
        "montoExento": round(monto_exento, 2),
        "antiguedad": {
            "years": antigen.get("years", 0) or 0,
            "months": antigen.get("months", 0) or 0,
            "days": antigen.get("days", 0) or 0,
        },
        "salarioDiarioPromedio": round(sdp, 2),
        "conceptos": conceptos,
        "conceptosAdicionales": adicionales,
        "descuentos": descuentos,
        "correction": correction,
    }


def _termination_auth_gate(svc, request_id: str, company_id: str,
                           owner_uid: str, sandbox: bool,
                           metadata: dict | None = None) -> dict:
    """Aplica el gate de autorización de desvinculación (modo simple).

    Sin regla activa -> {"approved": True, "isFallback": True}: el llamador
    sigue el flujo actual (inactivar + avanzar a liquidación).
    Con regla -> crea la solicitud de autorización (pending) y retorna
    {"approved": False, ...}: el llamador NO debe inactivar ni avanzar.
    El ``metadata`` (resumen de prestaciones) viaja en la solicitud para
    que el aprobador vea el esquema completo.
    """
    user = _user()
    if not _has_termination_rule(company_id, sandbox):
        return {"approved": True, "isFallback": True, "request": None}
    from app.services.hr_authorization_service import create_authorization_request
    req = svc.get_request(request_id) or {}
    result = create_authorization_request(
        company_id, "termination", request_id,
        doc_number=req.get("employeeName", "") or req.get("employeeId", "") or request_id,
        entity_type="offboarding",
        created_by_uid=user.get("uid", ""),
        created_by_email=user.get("email", ""),
        created_by_name=user.get("name", ""),
        sandbox=sandbox,
        link=url_for("web_rrhh.offboarding_wizard", request_id=request_id),
        owner_uid=owner_uid,
        metadata=metadata or {},
    )
    auth_req = result.get("request", {}) or {}
    # Respaldo: el estampado del motor ya guarda authorizationRequestId,
    # pero se asegura aquí por si el estampado falló silenciosamente.
    req = svc.get_request(request_id) or {}
    if auth_req.get("id") and not req.get("authorizationRequestId"):
        req["authorizationRequestId"] = auth_req["id"]
        svc.save_request_raw(request_id, req, user.get("email", ""))
    return {"approved": bool(result.get("approved")),
            "isFallback": bool(result.get("isFallback")),
            "request": auth_req}


# ── Inmutabilidad de la liquidación autorizada ─────────────────────────────

# Estados de liquidación que congelan los montos.
LOCKED_SETTLEMENT_STATUSES = frozenset({"aprobada", "pendiente_pago", "pagada"})

# Estados de autorización que congelan los montos.
LOCKED_AUTH_STATUSES = frozenset({"approved", "rejected"})


def _settlement_recalc_blocked(req: dict | None, settlement: dict | None,
                               company_id: str, sandbox: bool) -> str | None:
    """Retorna el motivo de bloqueo si NO se permite recalcular, o None si sí.

    Regla central: una liquidación autorizada es inmutable. Solo se puede
    recalcular cuando no hay autorización aprobada/rechazada y el settlement
    no está en estado final (aprobada/pendiente_pago/pagada).
    """
    req = req or {}
    auth_id = req.get("authorizationRequestId", "")
    if auth_id:
        try:
            auth = hr.get_authorization_request(company_id, auth_id, sandbox=sandbox)
        except Exception:
            auth = None
        if auth and auth.get("status") in LOCKED_AUTH_STATUSES:
            return ("La liquidación ya fue autorizada y sus montos están "
                    "congelados. Para modificarlos debe retirarse la "
                    "autorización y enviarse nuevamente a revisión.")
    if (settlement or {}).get("status", "") in LOCKED_SETTLEMENT_STATUSES:
        return ("La liquidación está en estado "
                f"'{(settlement or {}).get('status', '')}' y sus montos están "
                "congelados. No se puede recalcular.")
    return None


def _refresh_pending_auth_metadata(company_id: str, auth_id: str,
                                   settlement: dict, req: dict,
                                   sandbox: bool) -> bool:
    """Refresca el metadata de una autorización pendiente con el último cálculo.

    Evita que el aprobador vea cifras distintas a las guardadas cuando se
    recalcula mientras la solicitud sigue en la cola. Retorna True si se
    actualizó.
    """
    if not auth_id or not settlement:
        return False
    try:
        auth = hr.get_authorization_request(company_id, auth_id, sandbox=sandbox)
    except Exception:
        return False
    if not auth or auth.get("status") != "pending":
        return False
    auth["metadata"] = _prestaciones_metadata(settlement, req or {})
    hr.save_authorization_request(company_id, auth["id"], auth, sandbox=sandbox)
    return True


# ── Dashboard ───────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/dashboard")
def offboarding_dashboard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox, company_id = _service()

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
                           is_simple=svc.is_simple,
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
    svc, owner_uid, sandbox, company_id = _service()
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
    svc, owner_uid, sandbox, company_id = _service()

    if request.method == "POST":
        employee_id = request.form.get("employeeId", "").strip()
        employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
        if not employee:
            flash("Empleado no encontrado.", "error")
            return redirect(url_for("web_rrhh.offboarding_new"))

        if not is_active_equivalent(employee.get("status", "")):
            flash("El empleado ya está inactivo.", "warning")
            return redirect(url_for("web_rrhh.offboarding_list"))

        existing = svc.get_active_request_for_employee(employee_id)
        if existing:
            flash("El empleado ya tiene un proceso de desvinculación abierto.", "error")
            return redirect(url_for("web_rrhh.offboarding_wizard", request_id=existing.get("id", "")))

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
            "keepInCurrentPayroll": request.form.get("keepInCurrentPayroll") == "1",
        }

        req = svc.create_request(data, _email())
        svc.init_checklist(req.id, employee_id)

        # La autorización se solicita EXPLÍCITAMENTE desde el Paso 1 del
        # wizard (botón "Enviar a autorización"), una vez calculadas las
        # prestaciones. Aquí solo se crea el borrador y se redirige al
        # wizard para completar los datos y el cálculo.
        flash("Solicitud de desvinculación creada. Complete el Paso 1 "
              "(cálculo de prestaciones) para enviarla a autorización.", "success")
        return redirect(url_for("web_rrhh.offboarding_wizard", request_id=req.id))

    employees = hr.get_employees(company_id, sandbox=sandbox)
    active_employees = [e for e in employees if is_active_equivalent(e.get("status", ""))]
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
    svc, owner_uid, sandbox, company_id = _service()
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

        req["keepInCurrentPayroll"] = request.form.get("keepInCurrentPayroll") == "1"

        req["updatedBy"] = _email()
        svc.save_request_raw(request_id, req, _email())
        svc.save_version(request_id, req, _email(), reason="Edición de solicitud")
        svc.deactivate_employee(req)

        flash("Solicitud actualizada.", "success")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    employees = hr.get_employees(company_id, sandbox=sandbox)
    active_employees = [e for e in employees if is_active_equivalent(e.get("status", ""))]
    return render_template("rrhh/offboarding_form.html",
                           **_ctx(employees=active_employees, request_data=req,
                                  preselected_id=req.get("employeeId", ""),
                                  is_edit=True, active_page="rrhh_offboarding"))


# ── Cancel ──────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/cancel", methods=["POST"])
def offboarding_cancel(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox, company_id = _service()
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
        # Si había una autorización pendiente/devuelta, cancelarla también
        # para no dejar solicitudes huérfanas en la cola.
        auth_id = (svc.get_request(request_id) or {}).get("authorizationRequestId", "")
        if auth_id:
            try:
                from app.services.hr_authorization_service import cancel_authorization
                cancel_authorization(company_id, auth_id, cancelled_by=_email(), sandbox=sandbox)
            except Exception:
                pass
        flash("Solicitud cancelada.", "success")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


# ── Withdraw from authorization queue ─────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/authorization/withdraw", methods=["POST"])
def offboarding_authorization_withdraw(request_id):
    """Retira la autorización de la cola para corregir y reenviar.

    Solo el creador (u owner) puede retirarla y solo si aún no fue
    resuelta (pending/returned). La desvinculación sigue en borrador con
    su liquidación calculada; el vínculo se limpia vía _stamp_offboarding
    (rama cancelled+draft), levantando el hold del wizard.
    Las firmas parciales ya registradas se descartan (se reenvía desde cero).
    """
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    back = url_for("web_rrhh.offboarding_wizard", request_id=request_id)
    auth_id = req.get("authorizationRequestId", "")
    if not auth_id:
        flash("No hay ninguna solicitud en la cola de autorizaciones.", "info")
        return redirect(back)

    auth = hr.get_authorization_request(company_id, auth_id, sandbox=sandbox)
    if not auth or auth.get("status") not in ("pending", "returned"):
        flash("La solicitud ya fue resuelta y no puede retirarse de la cola.", "error")
        return redirect(back)

    user = _user()
    is_creator = (
        (auth.get("createdByUid") and auth.get("createdByUid") == user.get("uid", "")) or
        (auth.get("createdByEmail") and auth.get("createdByEmail") == user.get("email", ""))
    )
    if not is_creator and user.get("role") != "owner":
        flash("Solo el creador de la solicitud puede retirarla de la cola.", "error")
        return redirect(back)

    try:
        from app.services.hr_authorization_service import cancel_authorization
        result = cancel_authorization(
            company_id, auth_id, cancelled_by=_email(), sandbox=sandbox)
        if not result.get("success"):
            raise ValueError(result.get("error", "No se pudo retirar."))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(back)

    flash("Solicitud retirada de la cola de autorizaciones. "
          "Corrige lo necesario y vuelve a enviar.", "success")
    return redirect(back)


# ── Request correction of an authorized settlement ─────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/settlement/request-correction", methods=["POST"])
def offboarding_settlement_request_correction(request_id):
    """Solicita corrección de una liquidación ya autorizada.

    Solo owner/RRHH. La versión aprobada se preserva como snapshot
    histórico (``reemplazada``), se invalida la autorización y la solicitud
    vuelve a borrador para recalcular y reenviar a una NUEVA autorización.
    Si ya fue pagada, se rechaza (requiere ajuste separado).
    """
    if _login_required():
        return redirect(url_for("web_auth.login"))
    back = url_for("web_rrhh.offboarding_wizard", request_id=request_id)
    if not _is_hr_role():
        flash("Solo RRHH puede solicitar correcciones de liquidación.", "error")
        return redirect(back)
    svc, owner_uid, sandbox, company_id = _service()
    reason = request.form.get("reason", "").strip()
    try:
        svc.request_settlement_correction(request_id, reason, _email())
    except ValueError as e:
        flash(str(e), "error")
        return redirect(back)
    flash("Autorización invalidada para corrección. Recalcule los montos y "
          "vuelva a enviar a autorización.", "success")
    return redirect(back)


# ── Detail ─────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>")
def offboarding_detail(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return redirect(url_for("web_rrhh.offboarding_wizard", request_id=request_id))


# ── Transition (POST) ─────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/transition", methods=["POST"])
def offboarding_transition(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox, company_id = _service()

    new_status = request.form.get("newStatus", "").strip()
    comment = request.form.get("comment", "").strip()

    try:
        old_req = svc.get_request(request_id)
        old_status = old_req.get("status", "") if old_req else ""
        svc.transition(request_id, new_status, _email(), _role(), comment)

        if new_status == "pending_hr_approval" and not svc.is_simple:
            from app.services.hr_authorization_service import create_authorization_request
            req_data = svc.get_request(request_id)
            result = create_authorization_request(
                company_id, "termination", request_id,
                doc_number=req_data.get("employeeName", "") or req_data.get("employeeId", "") or request_id,
                entity_type="offboarding",
                created_by_uid=_user().get("uid", ""),
                created_by_email=_email(),
                created_by_name=_user().get("name", ""),
                sandbox=sandbox,
                link=url_for("web_rrhh.offboarding_detail", request_id=request_id),
                owner_uid=owner_uid,
            )
            if not req_data.get("authorizationRequestId"):
                req_data["authorizationRequestId"] = result["request"]["id"]
                svc.save_request_raw(request_id, req_data, _email())

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
    svc, owner_uid, sandbox, company_id = _service()

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
    svc, owner_uid, sandbox, company_id = _service()

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
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    # Inmutabilidad: una liquidación autorizada no puede recalcularse
    # (misma regla que el wizard; esta es la ruta legacy/alterna).
    _existing_legacy = (svc.get_settlement(req.get("settlementId", ""))
                        if req.get("settlementId") else None)
    _locked_legacy = _settlement_recalc_blocked(
        req, _existing_legacy, company_id, sandbox)
    if _locked_legacy:
        try:
            log_action(company_id, "settlement_recalc_blocked", "offboarding",
                       request_id, _email(),
                       changes={"reason": _locked_legacy,
                                "route": "offboarding_settlement_calculate"},
                       sandbox=sandbox)
        except Exception:
            pass
        flash(_locked_legacy, "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="settlement"))

    termination_date = req.get("effectiveDate", "")
    employee_id = req.get("employeeId", "")

    # Contexto laboral del contrato que se liquida (no el snapshot actual).
    from app.services.employment_context_service import (
        EmploymentContextError, build_context, filter_movements,
        get_transactions_for_context, resolve_for_employee,
    )
    try:
        _s_ctx = resolve_for_employee(company_id, employee, termination_date, sandbox=sandbox)
    except EmploymentContextError as e:
        flash(str(e), "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))
    except Exception:
        _s_ctx = None
    if _s_ctx is None:
        _s_ctx = build_context(employee, None)
    _s_cid = _s_ctx.get("contractId", "")
    hire_date = _s_ctx.get("seniorityBaseDate") or employee.get("hireDate", "")
    base_salary = float(_s_ctx.get("salary", 0) or employee.get("baseSalary", 0) or 0)
    salary_frequency = employee.get("paymentFrequency", "") or "mensual"
    termination_type = req.get("terminationType", "renuncia_voluntaria")

    preaviso_trabajado = request.form.get("preavisoTrabajado") == "on"
    vacation_pending_complete = int(request.form.get("vacationPendingCompleteYears", "0") or 0)
    vacation_taken_current = int(request.form.get("vacationTakenCurrentPeriod", "0") or 0)


    # Salario promedio real aislado al contrato que se liquida.
    promedio_mensual = float(employee.get("averageSalary", 0) or 0)
    salaries_12 = [base_salary]
    salaries_ytd = [base_salary]
    _s_txs = []
    try:
        _s_txs = get_transactions_for_context(company_id, employee_id, _s_ctx, sandbox=sandbox)
        prom = LiquidacionService.calcular_salario_promedio_mensual(
            _s_txs, contract_id=_s_cid,
            start_date=_s_ctx.get("startDate", ""), end_date=_s_ctx.get("endDate", ""))
        if prom.get("promedio_mensual", 0) > 0:
            promedio_mensual = prom["promedio_mensual"]
            salaries_12 = prom.get("monthly_totals_last_12") or [promedio_mensual]
            ytd = prom.get("monthly_salaries_ytd") or []
            if ytd:
                salaries_ytd = ytd
    except Exception:
        pass
    if promedio_mensual <= 0:
        promedio_mensual = base_salary
        salaries_12 = [base_salary]

    recurring_movements = filter_movements(get_recurring_movements(
        company_id, employee_id=employee_id, sandbox=sandbox), _s_ctx)

    from app.web.rrhh.liquidacion import _parse_additional_concepts, _parse_deductions
    additional_rows = _parse_additional_concepts(request.form)
    dd_present = request.form.get("dd_present") == "1"
    deduction_rows = _parse_deductions(request.form)

    result = LiquidacionService.calcular_liquidacion(
        employee_id=employee_id,
        employee_name=employee.get("fullName", ""),
        cedula=employee.get("cedula", ""),
        hire_date=hire_date,
        termination_date=termination_date,
        termination_type=termination_type,
        last_base_salary=base_salary,
        contract_id=_s_cid,
        employment_context=_s_ctx,
        salary_transactions_used=_s_txs,
        salary_frequency=salary_frequency,
        is_variable_salary=employee.get("isVariableSalary", False),
        monthly_salaries_last_12=salaries_12,
        monthly_salaries_ytd=salaries_ytd,
        preaviso_trabajado=preaviso_trabajado,
        vacation_pending_complete_years=vacation_pending_complete,
        vacation_taken_current_period=vacation_taken_current,
        dias_adeudados=int(request.form.get("diasAdeudados", "0") or 0),
        recurring_movements=None if dd_present else recurring_movements,
        recurring_deductions=deduction_rows if dd_present else None,
        additional_concepts=additional_rows,
        notes=request.form.get("notes", ""),
        created_by=_email(),
    )

    totales = result.get("totales", {})

    settlement_data = {
        "requestId": request_id,
        "employeeId": employee_id,
        "contractId": _s_cid,
        "contractPeriodNumber": _s_ctx.get("periodNumber", 0),
        "employmentStartDate": _s_ctx.get("startDate", ""),
        "employmentEndDate": _s_ctx.get("endDate", "") or termination_date,
        "seniorityBaseDate": _s_ctx.get("seniorityBaseDate", ""),
        "vacationBaseDate": _s_ctx.get("vacationBaseDate", ""),
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
        "conceptosAdicionales": result.get("conceptosAdicionales", []),
        "descuentosDetalle": result.get("descuentosDetalle", []),
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
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    hold = svc._check_auth_hold(req or {})
    if hold:
        flash(hold, "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="settlement"))
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
    svc, owner_uid, sandbox, company_id = _service()
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
    svc, owner_uid, sandbox, company_id = _service()
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
    svc, owner_uid, sandbox, company_id = _service()

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
    svc, owner_uid, sandbox, company_id = _service()

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
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    next_view = request.form.get("next", "").strip()

    def _back_url(tab="documents"):
        if next_view == "wizard":
            return url_for("web_rrhh.offboarding_wizard", request_id=request_id)
        return url_for("web_rrhh.offboarding_detail", request_id=request_id, tab=tab)

    doc_type = request.form.get("documentType", "").strip()
    notes = request.form.get("notes", "").strip()
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debes seleccionar un archivo.", "error")
        return redirect(_back_url())

    from app.services.db_service import DatabaseService

    file_data = file.read()
    max_size = 10 * 1024 * 1024
    if len(file_data) > max_size:
        flash("El archivo excede el tamaño máximo de 10MB.", "error")
        return redirect(_back_url())

    mime_type = file.content_type or "application/pdf"
    safe_name = secure_filename(file.filename) or "documento"
    destination_path = f"users/{owner_uid}/offboarding/{request_id}/{uuid.uuid4().hex[:8]}_{safe_name}"
    file_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)

    doc_id = str(uuid.uuid4())
    doc_data = {
        "id": doc_id,
        "requestId": request_id,
        "documentType": doc_type or "other",
        "title": file.filename,
        "fileUrl": file_url,
        "storagePath": destination_path,
        "fileSize": len(file_data),
        "mimeType": mime_type,
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
    return redirect(_back_url())


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/documents/<doc_id>/download")
def offboarding_download_document(request_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox, company_id = _service()
    docs = svc.get_documents(request_id)
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if not doc or not doc.get("fileUrl"):
        flash("Documento no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="documents"))

    raw = doc["fileUrl"]
    if raw.startswith("http") or raw.startswith("/uploads/"):
        return redirect(raw)

    import base64
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
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    if request.method == "POST":
        # Entrada compatible: delegar al dominio único (RehireService).
        # Si no se elige otro empleado, se reincorpora el mismo de la solicitud.
        from app.services.rehire_service import RehireService, RehireValidationError
        new_employee_id = request.form.get("newEmployeeId", "").strip() or req.get("employeeId", "")
        new_hire_date = request.form.get("newHireDate", "").strip()
        try:
            new_salary = float(request.form.get("newSalary", "0") or 0)
        except Exception:
            new_salary = 0
        preserves_seniority = request.form.get("preservesSeniority") == "1"
        continuous_date = request.form.get("continuousSeniorityDate", "").strip()

        data = {
            "originalRequestId": request_id,
            "originalEmployeeId": req.get("employeeId", ""),
            "newEmployeeId": new_employee_id,
            "newHireDate": new_hire_date,
            "newPosition": request.form.get("newPosition", "").strip(),
            "newDepartment": request.form.get("newDepartment", "").strip(),
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
            try:
                rehire_svc = RehireService(company_id, sandbox)
                rehire_svc.rehire_employee(
                    employee_id=new_employee_id, start_date=new_hire_date,
                    contract_data={
                        "position": request.form.get("newPosition", "").strip(),
                        "department": request.form.get("newDepartment", "").strip(),
                        "departmentId": request.form.get("newDepartment", "").strip(),
                        "salary": new_salary,
                    },
                    selected_movement_ids=[],
                    seniority_policy="preserve" if preserves_seniority else "reset",
                    vacation_policy="reset",
                    seniority_base_date=continuous_date if preserves_seniority else "",
                    vacation_base_date="",
                    rehire_request_id=rehire_id,
                    actor_email=_email(),
                )
                flash("Empleado recontratado exitosamente (nuevo período laboral).", "success")
            except RehireValidationError as ve:
                flash(str(ve), "error")
            except Exception as e:
                print(f"⚠️ offboarding_rehire: {e}")
                flash(f"No se pudo completar la reincorporación: {e}", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id, tab="overview"))

    employees = hr.get_employees(company_id, sandbox=sandbox)
    return render_template("rrhh/offboarding/rehire_form.html",
                           **_ctx(req=req, employees=employees,
                                  active_page="rrhh_offboarding"))


def _select_settlement_payment(payments: list, settlement: dict | None) -> dict | None:
    """Elige el pago vinculado a la liquidación/versión vigente.

    Prefiere el pago con ``settlementId`` (+ versión) coincidente; si no hay
    coincidencia, cae al último registro genérico.
    """
    payments = payments or []
    if not payments:
        return None
    if settlement:
        sid = settlement.get("id", "")
        try:
            sver = int(settlement.get("version", 0) or 0)
        except (TypeError, ValueError):
            sver = 0
        linked = [p for p in payments if sid and p.get("settlementId") == sid]
        if linked and sver:
            ver_match = [p for p in linked
                         if str(p.get("settlementVersion", "")) == str(sver)]
            if ver_match:
                linked = ver_match
        if linked:
            return linked[-1]
    return payments[-1]


# ── PDF Generation ─────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/pdf/letter")
def offboarding_pdf_letter(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
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
    svc, owner_uid, sandbox, company_id = _service()
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

    employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
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


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/pdf/finiquito")
def offboarding_pdf_finiquito(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox, company_id = _service()
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

    employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    # Fallback solo-visual para liquidaciones viejas guardadas sin baseSalary
    # (el wizard no lo persistía). No se escribe en Firestore.
    try:
        if settlement and not float(settlement.get("baseSalary", 0) or 0):
            settlement["baseSalary"] = float(employee.get("baseSalary", 0) or 0)
    except (TypeError, ValueError):
        pass

    try:
        from app.services.offboarding_document_service import generate_finiquito, _company_data
        from app.models.offboarding import SettlementStatus
        company = _company_data(owner_uid, sandbox)

        settlement_completed = settlement.get("status") == SettlementStatus.PAGADA.value if settlement else False

        payments = svc.get_payments(request_id) or []
        payment = _select_settlement_payment(payments, settlement)

        pdf_bytes = generate_finiquito(
            req, settlement, employee, company, request.host_url,
            payment=payment,
            settlement_completed=settlement_completed,
        )
        filename = f"acta_finiquito_{request_id[:8]}.pdf"
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"Error generando PDF acta de finiquito: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))


# ── TSS Notification ───────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/tss/download")
def offboarding_tss_download(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    svc = OffboardingService(company_id, sandbox, offboarding_mode="simple")
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.offboarding_detail", request_id=request_id))

    try:
        from app.services.offboarding_tss_service import generate_tss_baja, get_tss_baja_filename
        from app.services.db_service import DatabaseService
        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
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
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
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
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    if not _is_hr_role():
        flash("Solo RRHH puede ejecutar esta acción.", "error")
        return redirect(url_for("web_rrhh.offboarding_dashboard"))

    dry_run = request.form.get("dry_run") == "1"
    svc = OffboardingService(company_id, sandbox, offboarding_mode="simple")
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
            emp = hr.get_employee(company_id, emp_id, sandbox=sandbox)
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
                hr.save_employee(company_id, emp_id, emp, sandbox=sandbox)
                log_action(company_id, "employee_marked_inactive", "employee",
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
    svc, owner_uid, sandbox, company_id = _service()
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
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        return {"error": "No encontrada"}, 404
    employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        return {"error": "Empleado no encontrado"}, 404
    return jsonify({
        "hireDate": employee.get("hireDate", ""),
        "baseSalary": employee.get("baseSalary", 0),
        "paymentFrequency": employee.get("paymentFrequency", "mensual"),
        "fullName": employee.get("fullName", ""),
        "cedula": employee.get("cedula", ""),
    })


# ── Toggle offboarding mode (simple / full) ──────────────────────────────
# (Removed: the offboarding flow is always in "simple" mode now.)



# ═══════════════════════════════════════════════════════════════════════════
# WIZARD DE OFFBOARDING — 4 pasos lineales con auto-transición
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/wizard")
def offboarding_wizard(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.offboarding_list"))

    current_step = svc.wizard_get_step(request_id)
    employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
    settlement = None
    if req.get("settlementId"):
        settlement = svc.get_settlement(req["settlementId"])

    checklist = None
    if req.get("checklistId"):
        checklist = svc.get_checklist(req["checklistId"])

    documents = svc.get_documents(request_id)
    payments = svc.get_payments(request_id)
    payroll_groups = hr.get_payroll_groups(company_id, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    # ── Autorización vinculada (gate modo simple): aprobadores y firmas ──
    auth_request = None
    if req.get("authorizationRequestId"):
        try:
            auth_request = hr.get_authorization_request(
                company_id, req["authorizationRequestId"], sandbox=sandbox)
        except Exception:
            auth_request = None

    # ── Estado visual del encabezado: refleja la autorización vinculada ──
    # req.status sigue siendo la verdad operativa (draft permite editar y
    # retirar de la cola); el encabezado muestra el estado de autorización.
    _auth_status = (auth_request or {}).get("status", "")
    if _auth_status == "pending":
        header_status = {"key": "pending_authorization",
                         "label": "Pendiente de autorización",
                         "color": "warning"}
    elif _auth_status == "returned":
        header_status = {"key": "returned",
                         "label": "Devuelta para corrección",
                         "color": "warning"}
    else:
        header_status = None

    # ── Retiro de la cola: solo el creador (u owner) puede retirar una
    # autorización aún no resuelta para corregir y reenviar ──
    can_withdraw_auth = False
    if auth_request and auth_request.get("status") in ("pending", "returned"):
        _wu = _user()
        can_withdraw_auth = bool(
            (auth_request.get("createdByUid") and
             auth_request.get("createdByUid") == _wu.get("uid", "")) or
            (auth_request.get("createdByEmail") and
             auth_request.get("createdByEmail") == _wu.get("email", "")) or
            _wu.get("role") == "owner")

    # ── Solicitud de corrección: solo si hay algo autorizado que reabrir,
    # sin pago registrado y fuera de estados terminales. El permiso se
    # revalida en el endpoint POST. ──
    _corr_settlement = settlement or {}
    _corr_locked = (
        (_auth_status == "approved")
        or _corr_settlement.get("status") in ("aprobada", "pendiente_pago")
    )
    _corr_terminal = (
        req.get("status") in ("completed", "cancelled", "rejected")
        or _corr_settlement.get("status") == "pagada"
    )
    can_request_correction = bool(
        _corr_locked and not _corr_terminal and _is_hr_role())

    # ── Auto-calcular vacaciones pendientes ──
    vacation_pending = 0
    vacation_taken = 0
    vacation_total_taken = 0
    vacation_total_accrued = 0
    vacation_total_pendientes = 0
    try:
        if employee:
            hire_date = employee.get("hireDate", "")
            vac_requests = hr.get_vacation_requests(company_id, sandbox=sandbox)
            emp_vacs = [v for v in vac_requests
                        if v.get("employeeId") == employee.get("id", "")
                        and v.get("status") == "aprobada"]
            ant_approx = LiquidacionService.calcular_antiguedad(
                hire_date, req.get("effectiveDate", date.today().isoformat())
            )
            ant_years = ant_approx["years"]
            if ant_years > 0 and hire_date:
                aniversario_actual = date.today()
                try:
                    y = aniversario_actual.year
                    dt = datetime.strptime(hire_date[:10], "%Y-%m-%d").replace(year=y)
                    aniversario_actual = dt.date()
                except (ValueError, TypeError):
                    pass
                taken_before = 0
                taken_current = 0
                for v in emp_vacs:
                    v_start = v.get("startDate", "")
                    if v_start and v_start >= aniversario_actual.isoformat():
                        taken_current += v.get("days", 0)
                    else:
                        taken_before += v.get("days", 0)
                dias_por_anio = 18 if ant_years >= 5 else 14
                max_expected = ant_years * dias_por_anio
                if max_expected > taken_before:
                    vacation_pending = (max_expected - taken_before) // dias_por_anio
                vacation_taken = taken_current
                vacation_total_taken = sum(v.get("days", 0) for v in emp_vacs)
                vacation_total_accrued = max_expected
                vacation_total_pendientes = max(0, max_expected - vacation_total_taken)
    except Exception:
        pass

    # ── Conceptos adicionales y descuentos recurrentes (para el formulario) ──
    from app.web.rrhh.liquidacion import _concepts_available
    concepts_available = _concepts_available(company_id, sandbox)

    recurring_movements = []
    if employee:
        recurring_movements = get_recurring_movements(
            company_id, employee_id=employee.get("id", ""), sandbox=sandbox
        )

    if settlement and settlement.get("descuentosDetalle"):
        deduction_rows = [dict(d) for d in settlement.get("descuentosDetalle", [])]
    else:
        deduction_rows = LiquidacionService.build_recurring_deductions(recurring_movements)

    additional_rows = []
    if settlement and settlement.get("conceptosAdicionales"):
        additional_rows = [dict(a) for a in settlement.get("conceptosAdicionales", [])]

    return render_template("rrhh/offboarding_wizard.html",
                           **_ctx(req=req, employee=employee,
                                  settlement=settlement, checklist=checklist,
                                  documents=documents, payments=payments,
                                  current_step=current_step,
                                  payroll_groups=payroll_groups, is_simple=svc.is_simple,
                                   auth_request=auth_request,
                                   header_status=header_status,
                                   can_withdraw_auth=can_withdraw_auth,
                                   can_request_correction=can_request_correction,
                                   has_termination_rule=_has_termination_rule(company_id, sandbox),
                                  current_user_uid=_user().get("uid", ""),
                                  vacation_pending=vacation_pending,
                                  vacation_taken=vacation_taken,
                                  vacation_total_pendientes=vacation_total_pendientes,
                                  vacation_total_accrued=vacation_total_accrued,
                                  vacation_total_taken=vacation_total_taken,
                                  concepts_available=concepts_available,
                                  additional_rows=additional_rows,
                                  deduction_rows=deduction_rows))


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/wizard/step1", methods=["POST"])
def offboarding_wizard_step1(request_id):
    if _login_required():
        return jsonify({"success": False, "message": "No autenticado."}), 401
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        return jsonify({"success": False, "message": "Solicitud no encontrada."}), 404

    employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        return jsonify({"success": False, "message": "Empleado no encontrado."}), 404

    user_email = _email()
    termination_type = request.form.get("terminationType", req.get("terminationType", "renuncia_voluntaria")).strip()
    termination_date = request.form.get("terminationDate", req.get("effectiveDate", "")).strip()
    preaviso_trabajado = request.form.get("preavisoTrabajado") == "on"
    vacation_pending = int(request.form.get("vacationPendingCompleteYears", "0") or 0)
    vacation_taken = int(request.form.get("vacationTakenCurrentPeriod", "0") or 0)
    vacation_dias_pendientes_val = int(request.form.get("vacationDiasPendientes", "0") or 0)
    dias_adeudados = int(request.form.get("diasAdeudados", "0") or 0)
    if req.get("keepInCurrentPayroll"):
        dias_adeudados = 0

    # Contexto laboral del contrato que se liquida (no el snapshot actual).
    # Ambigüedad → se bloquea; sin contrato → fallback legacy.
    from app.services.employment_context_service import (
        EmploymentContextError, build_context, filter_movements,
        get_transactions_for_context, resolve_for_employee,
    )
    try:
        _off_ctx = resolve_for_employee(company_id, employee, termination_date, sandbox=sandbox)
    except EmploymentContextError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception:
        _off_ctx = None
    if _off_ctx is None:
        _off_ctx = build_context(employee, None)
    _off_contract_id = _off_ctx.get("contractId", "")
    _off_start = _off_ctx.get("startDate", "")
    _off_end = _off_ctx.get("endDate", "")
    _off_hire = _off_ctx.get("seniorityBaseDate") or employee.get("hireDate", "")

    base_salary = float(_off_ctx.get("salary", 0) or employee.get("baseSalary", 0) or 0)
    salary_frequency = employee.get("paymentFrequency", "") or "mensual"

    # Salario promedio real aislado al contrato que se liquida.
    promedio_mensual = float(employee.get("averageSalary", 0) or 0)
    salaries_12 = [base_salary]
    salaries_ytd = [base_salary]
    scoped_txs = []
    try:
        scoped_txs = get_transactions_for_context(
            company_id, employee["id"], _off_ctx, sandbox=sandbox)
        prom = LiquidacionService.calcular_salario_promedio_mensual(
            scoped_txs, contract_id=_off_contract_id, start_date=_off_start, end_date=_off_end)
        if prom.get("promedio_mensual", 0) > 0:
            promedio_mensual = prom["promedio_mensual"]
            salaries_12 = prom.get("monthly_totals_last_12") or [promedio_mensual]
            ytd = prom.get("monthly_salaries_ytd") or []
            if ytd:
                salaries_ytd = ytd
    except Exception:
        pass
    if promedio_mensual <= 0:
        promedio_mensual = base_salary
        salaries_12 = [base_salary]

    # ── Conceptos adicionales y descuentos recurrentes (filas editables) ──
    from app.web.rrhh.liquidacion import _parse_additional_concepts, _parse_deductions
    additional_rows = _parse_additional_concepts(request.form)
    dd_present = request.form.get("dd_present") == "1"
    deduction_rows = _parse_deductions(request.form)
    recurring_movements = filter_movements(get_recurring_movements(
        company_id, employee_id=employee["id"], sandbox=sandbox
    ), _off_ctx)

    calc_kwargs = dict(
        employee_id=employee["id"],
        employee_name=employee.get("fullName", ""),
        cedula=employee.get("cedula", ""),
        hire_date=_off_hire,
        termination_date=termination_date,
        termination_type=termination_type,
        last_base_salary=base_salary,
        contract_id=_off_contract_id,
        employment_context=_off_ctx,
        salary_transactions_used=scoped_txs,
        salary_frequency=salary_frequency,
        is_variable_salary=employee.get("isVariableSalary", False),
        monthly_salaries_last_12=salaries_12,
        monthly_salaries_ytd=salaries_ytd,
        preaviso_trabajado=preaviso_trabajado,
        vacation_pending_complete_years=vacation_pending,
        vacation_taken_current_period=vacation_taken,
        vacation_dias_pendientes=vacation_dias_pendientes_val,
        dias_adeudados=dias_adeudados,
        dias_extra_navidad=(
            int(termination_date[8:10]) if termination_date and len(termination_date) >= 10 else 0
        ),
        additional_concepts=additional_rows,
        created_by=user_email,
    )
    if dd_present:
        calc_kwargs["recurring_deductions"] = deduction_rows
    else:
        calc_kwargs["recurring_movements"] = recurring_movements

    result = LiquidacionService.calcular_liquidacion(**calc_kwargs)
    result["requestId"] = request_id
    result["terminationType"] = termination_type
    result["terminationDate"] = termination_date

    # Poblar campos legados (floats) para compatibilidad con la vista de detalle/PDF
    # baseSalary: calcular_liquidacion no lo devuelve; sin esto el acta sale en cero.
    result["baseSalary"] = float(base_salary or 0.0)
    result["salaryFrequency"] = salary_frequency
    _t = result.get("totales", {})
    result["descuentos"] = float(_t.get("montoDescuentos", 0.0))
    result["loanDeductions"] = float(_t.get("loanDeductions", 0.0))
    result["advanceDeductions"] = float(_t.get("advanceDeductions", 0.0))
    result["otherDeductions"] = float(_t.get("otherDeductions", 0.0))
    result["montoNetoAPagar"] = float(_t.get("montoNetoAPagar", 0.0))

    # ── Capture existing settlement data to preserve across recalculations ──
    existing = svc.get_settlement(req.get("settlementId", "")) if req.get("settlementId") else None
    prev_status = existing.get("status") if existing else None
    if existing:
        result["id"] = existing["id"]
        result["version"] = existing.get("version", 1) + 1
        result["previousVersionId"] = existing["id"]
        for field in ("assignedGroupId", "assignedGroupName", "assignedAt"):
            if existing.get(field):
                result[field] = existing[field]

    wizard_action = request.form.get("wizard_action", "").strip()

    if wizard_action == "submit_authorization":
        # Envío EXPLÍCITO a autorización: la liquidación ya está calculada
        # y visible en el wizard. No se aprueba ni se avanza; la solicitud
        # queda en borrador bloqueada hasta alcanzar el quórum.
        existing_settlement = existing or (
            svc.get_settlement(req.get("settlementId", ""))
            if req.get("settlementId") else None)
        if not existing_settlement:
            return jsonify({"success": False,
                            "message": "Debe calcular la liquidación antes de enviar a autorización."}), 400
        auth_id = req.get("authorizationRequestId", "")
        existing_auth = None
        if auth_id:
            try:
                existing_auth = hr.get_authorization_request(
                    company_id, auth_id, sandbox=sandbox)
            except Exception:
                existing_auth = None
        meta = _prestaciones_metadata(existing_settlement, req)
        if existing_auth and existing_auth.get("status") == "returned":
            # Devuelta para corrección: refrescar prestaciones y reenviar.
            existing_auth["metadata"] = meta
            hr.save_authorization_request(
                company_id, existing_auth["id"], existing_auth, sandbox=sandbox)
            from app.services.hr_authorization_service import resubmit_authorization
            res = resubmit_authorization(
                company_id, existing_auth["id"],
                resubmitted_by=user_email, sandbox=sandbox)
            if not res.get("success"):
                return jsonify({"success": False,
                                "message": res.get("error", "No se pudo reenviar.")}), 400
            return jsonify({"success": True, "resubmitted": True})
        if existing_auth and existing_auth.get("status") == "pending":
            # Ya enviada: refrescar prestaciones con el último cálculo.
            existing_auth["metadata"] = meta
            hr.save_authorization_request(
                company_id, existing_auth["id"], existing_auth, sandbox=sandbox)
            return jsonify({"success": True, "already_submitted": True})
        gate = _termination_auth_gate(
            svc, request_id, company_id, owner_uid, sandbox, metadata=meta)
        if gate["approved"]:
            # Sin regla activa: no hay nada que enviar; el flujo normal
            # continúa con "Aprobar liquidación y continuar".
            return jsonify({"success": True, "authorization": "fallback"})
        return jsonify({"success": True,
                        "authorization": (gate.get("request") or {}).get("id", "")})

    if wizard_action == "approve":
        if not existing:
            return jsonify({"success": False, "message": "No hay liquidación que aprobar."}), 400
        hold = svc._check_auth_hold(req or {})
        if hold:
            return jsonify({"success": False, "message": hold}), 400
        svc.approve_settlement(existing["id"], user_email)
    else:
        # Inmutabilidad: una liquidación autorizada no puede recalcularse.
        locked = _settlement_recalc_blocked(req, existing, company_id, sandbox)
        if locked:
            try:
                log_action(company_id, "settlement_recalc_blocked", "offboarding",
                           request_id, user_email,
                           changes={"reason": locked,
                                    "settlementId": (existing or {}).get("id", ""),
                                    "settlementStatus": (existing or {}).get("status", ""),
                                    "authorizationRequestId": req.get("authorizationRequestId", "")},
                           sandbox=sandbox)
            except Exception:
                pass
            return jsonify({"success": False, "message": locked}), 400
        svc.save_settlement(result, user_email)
        # Si la autorización sigue pendiente, sincronizar sus prestaciones
        # con el último cálculo para que el aprobador vea los números reales.
        try:
            _refresh_pending_auth_metadata(
                company_id, req.get("authorizationRequestId", ""),
                result, req, sandbox)
        except Exception:
            pass
        should_approve = (
            wizard_action == ""
            or (wizard_action != "" and prev_status == "pendiente_pago")
        )
        if should_approve:
            svc.approve_settlement(result["id"], user_email)

    # Re-read request after save_settlement (may have been mutated in Firestore)
    req = svc.get_request(request_id)
    if not req:
        return jsonify({"success": False, "message": "Solicitud no encontrada."}), 404

    current_status = svc._get_status_value(req)

    should_transition = wizard_action in ("approve", "")
    if should_transition:
        if current_status in ("draft", "pending_supervisor_approval",
                               "pending_hr_approval", "approved",
                               "pending_settlement", "pending_assets"):
            try:
                svc.wizard_transition(request_id, "pending_payment", user_email)
            except ValueError as e:
                return jsonify({"success": False, "message": str(e)}), 400
        elif current_status == "pending_payment":
            pass  # Already at the correct step
        else:
            return jsonify({
                "success": False,
                "message": f"No se puede avanzar desde el estado actual: {current_status}"
            }), 400

    return jsonify({"success": True, "settlement": result})


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/wizard/step2", methods=["POST"])
def offboarding_wizard_step2(request_id):
    if _login_required():
        return jsonify({"success": False, "message": "No autenticado."}), 401
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        return jsonify({"success": False, "message": "Solicitud no encontrada."}), 404

    user_email = _email()

    checklist = None
    if req.get("checklistId"):
        checklist = svc.get_checklist(req["checklistId"])
    if checklist:
        all_completed = request.form.get("checklistAllCompleted") == "1"
        item_updates = {}
        for key in request.form:
            if key.startswith("check_item_"):
                item_id = key.replace("check_item_", "")
                item_updates[item_id] = True
        for item in checklist.get("items", []):
            iid = item.get("id", "")
            if all_completed or iid in item_updates:
                item["completed"] = True
                item["completedBy"] = user_email
                item["completedAt"] = svc._now()
        completed = sum(1 for i in checklist.get("items", []) if i.get("completed"))
        checklist["completedItems"] = completed
        checklist["allCompleted"] = all_completed or completed >= checklist.get("totalItems", 0)
        from app.services.offboarding_data_service import save as ods_save
        ods_save("offboarding_checklists", checklist["id"], checklist, company_id, sandbox)

    payment_form = request.form.get("paymentMethod", "nomina").strip()
    payment_method = "payroll" if payment_form == "nomina" else "transfer"
    settlement = None
    if req.get("settlementId"):
        settlement = svc.get_settlement(req["settlementId"])

    if payment_form == "nomina":
        group_id = request.form.get("payrollGroupId", "").strip()
        new_group_name = request.form.get("newGroupName", "").strip()
        if not group_id and not new_group_name:
            return jsonify({"success": False, "message": "Debe seleccionar o crear un grupo de nómina para liquidados."}), 400
        if not group_id and new_group_name:
            from uuid import uuid4
            group_id = str(uuid4())
            hr.save_payroll_group(company_id, group_id, {
                "id": group_id, "name": new_group_name,
                "frequency": "mensual", "isActive": True,
                "createdAt": svc._now(), "createdBy": user_email,
            }, sandbox=sandbox)
        if group_id and settlement:
            employee = hr.get_employee(company_id, req.get("employeeId", ""), sandbox=sandbox)
            if employee:
                employee["payrollGroupIds"] = [group_id]
                hr.save_employee(company_id, employee["id"], employee, sandbox=sandbox)
            settlement["assignedGroupId"] = group_id
            group = hr.get_payroll_group(company_id, group_id, sandbox=sandbox)
            settlement["assignedGroupName"] = group.get("name", group_id) if group else group_id
            settlement["assignedAt"] = svc._now()
            from app.services.offboarding_data_service import save as ods_save
            ods_save("offboarding_settlements", settlement["id"], settlement, company_id, sandbox)

    settlement_amount = float(settlement.get("totales", {}).get("montoNetoAPagar", 0)) if settlement else 0

    payment_data = {
        "requestId": request_id,
        "settlementVersion": settlement.get("version", 1) if settlement else 1,
        "paymentMethod": payment_method,
        "paymentDate": request.form.get("paymentDate", svc._now()[:10]),
        "paymentReference": request.form.get("paymentReference", "").strip(),
        "totalAmount": float(request.form.get("totalAmount", settlement_amount)),
    }
    svc.save_payment(payment_data, user_email)

    if payment_form != "nomina" and req.get("settlementId"):
        try:
            svc.mark_settlement_paid(req["settlementId"], {
                "paymentDate": payment_data["paymentDate"],
                "payrollPeriodId": "",
                "payrollPeriodKey": "",
            }, user_email)
        except Exception:
            pass

    try:
        svc.wizard_transition(request_id, "pending_documents", user_email)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400

    return jsonify({"success": True})


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/wizard/back", methods=["POST"])
def offboarding_wizard_back(request_id):
    if _login_required():
        return jsonify({"success": False, "message": "No autenticado."}), 401
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        return jsonify({"success": False, "message": "Solicitud no encontrada."}), 404

    user_email = _email()
    current = svc._get_status_value(req)
    reverse = {
        "pending_payment": "pending_settlement",
        "pending_assets": "pending_settlement",
        "pending_documents": "pending_payment",
        "pending_tss": "pending_documents",
    }
    target = reverse.get(current)
    if not target:
        target = "pending_settlement"

    from app.models.offboarding import StatusChange
    timestamp = svc._now()
    req["status"] = target
    entry = StatusChange(
        fromStatus=current,
        toStatus=target,
        changedBy=user_email,
        changedAt=timestamp,
        comment="Wizard: retroceder un paso",
    ).model_dump()
    if "statusHistory" not in req or not isinstance(req.get("statusHistory"), list):
        req["statusHistory"] = []
    req["statusHistory"].append(entry)
    svc.save_request_raw(request_id, req, user_email)

    return jsonify({"success": True})


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/wizard/step3", methods=["POST"])
def offboarding_wizard_step3(request_id):
    if _login_required():
        return jsonify({"success": False, "message": "No autenticado."}), 401
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        return jsonify({"success": False, "message": "Solicitud no encontrada."}), 404

    user_email = _email()
    try:
        svc.wizard_transition(request_id, "pending_tss", user_email)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400

    return jsonify({"success": True})


@web_rrhh_bp.route("/rrhh/offboarding/<request_id>/wizard/step4", methods=["POST"])
def offboarding_wizard_step4(request_id):
    if _login_required():
        return jsonify({"success": False, "message": "No autenticado."}), 401
    svc, owner_uid, sandbox, company_id = _service()
    req = svc.get_request(request_id)
    if not req:
        return jsonify({"success": False, "message": "Solicitud no encontrada."}), 404

    user_email = _email()

    action = request.form.get("action", "").strip()
    if action == "tss":
        req["tssNotifiedAt"] = svc._now()
        svc.save_request_raw(request_id, req, user_email)
        return jsonify({"success": True})
    if action == "revoke_access":
        svc.revoke_access(request_id, user_email, revoke=True)
        return jsonify({"success": True})
    if action == "complete":
        if not req.get("tssNotifiedAt"):
            return jsonify({"success": False, "message": "Debe notificar la baja en TSS."}), 400
        if not req.get("accessRevokedAt"):
            return jsonify({"success": False, "message": "Debe revocar los accesos."}), 400
        settlement = None
        if req.get("settlementId"):
            settlement = svc.get_settlement(req["settlementId"])
        if settlement and settlement.get("status") != "pagada":
            return jsonify({"success": False, "message": "La liquidación aún no ha sido pagada. Si es por nómina, procese el pago del período de liquidados primero."}), 400
        try:
            svc.wizard_transition(request_id, "completed", user_email)
        except ValueError as e:
            return jsonify({"success": False, "message": str(e)}), 400
        return jsonify({"success": True})

    return jsonify({"success": False, "message": "Acción no reconocida."}), 400

