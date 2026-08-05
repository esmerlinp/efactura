"""RRHH module — auto-extracted."""

from datetime import date
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService
from app.utils.country_context import get_current_country
from app.services.payroll_audit_service import log_action
from app.services.payroll_async_service import create_job, update_job, get_job
from app.services.mailer import Mailer
import threading, io
from datetime import datetime, timezone, date


# ═══════════════════════════════════════════════════════════════════════════
# WORKFLOW DE APROBACIÓN Y CONTABILIZACIÓN
# ═══════════════════════════════════════════════════════════════════════════

_VALID_TRANSITIONS = {
    "borrador":      ["calculada", "cancelled"],
    "calculada":     ["validada", "borrador"],
    "validada":      ["aprobada", "calculada"],
    "aprobada":      ["contabilizada", "validada"],
    "contabilizada": ["pagada", "aprobada", "reopened"],
    "pagada":        ["cerrada", "contabilizada"],
    "cerrada":       ["reopened"],
    "reopened":      ["calculada"],
    "cancelled":     [],
}

STATUS_LABELS = {
    "borrador": "Borrador",
    "calculada": "Calculada",
    "validada": "Validada",
    "aprobada": "Aprobada",
    "contabilizada": "Contabilizada",
    "pagada": "Pagada",
    "cerrada": "Cerrada",
    "reopened": "Reabierta",
    "cancelled": "Cancelada",
}

IMMUTABLE_STATUSES = ("cerrada", "cancelled")


def _transition(period, to_status, comment="", owner_uid="", sandbox=True, skip_sod=False):
    user_email = session.get("user", {}).get("email", "")
    user_uid = session.get("user", {}).get("uid", "")
    user_role = session.get("user", {}).get("role", "")
    now_iso = datetime.now(timezone.utc).isoformat()
    from_status = period.get("status", "borrador")

    if to_status not in _VALID_TRANSITIONS.get(from_status, []):
        return False, f"Transición inválida: no se puede pasar de «{STATUS_LABELS.get(from_status, from_status)}» a «{STATUS_LABELS.get(to_status, to_status)}»."

    if not skip_sod and user_role != "owner":
        if to_status == "aprobada":
            calculator = period.get("calculatedBy", "")
            if calculator and calculator == user_email:
                return False, "Conflicto SoD: quien calculó la nómina no puede aprobarla. Otro miembro del equipo debe aprobar."
        elif to_status == "contabilizada":
            approver = period.get("approvedBy", "")
            if approver and approver == user_email:
                return False, "Conflicto SoD: quien aprobó la nómina no puede contabilizarla. Otro miembro del equipo debe contabilizar."
        elif to_status == "pagada":
            poster = period.get("postedBy", "")
            if poster and poster == user_email:
                return False, "Conflicto SoD: quien contabilizó la nómina no puede autorizar el pago. Otro miembro del equipo debe ejecutar el pago."

    period["status"] = to_status
    history = period.get("statusHistory", [])
    history.append({
        "from": from_status,
        "to": to_status,
        "by": user_email,
        "at": now_iso,
        "comment": comment,
    })
    period["statusHistory"] = history

    if to_status == "calculada":
        period["calculatedBy"] = user_email
        period["calculatedAt"] = now_iso
        # Incrementar revisión al recalcular
        period["revision"] = period.get("revision", 1)
        if from_status in ("reopened", "calculada"):
            period["revision"] = period.get("revision", 1) + 1
    elif to_status == "reopened":
        period["revision"] = period.get("revision", 1)  # Mantener revisión
    elif to_status == "validada":
        period["validatedBy"] = user_email
        period["validatedAt"] = now_iso
    elif to_status == "aprobada":
        period["approvedBy"] = user_email
        period["approvedAt"] = now_iso
    elif to_status == "contabilizada":
        period["postedBy"] = user_email
        period["postedAt"] = now_iso
    elif to_status == "pagada":
        period["paidBy"] = user_email
        period["paidAt"] = now_iso
    elif to_status == "cerrada":
        period["closedBy"] = user_email
        period["closedAt"] = now_iso

    # ── Snapshot de empleados para DGT-4 ──
    if to_status in ("calculada", "cerrada") and owner_uid:
        try:
            from app.services import hr_data_service as hr
            employees = hr.get_employees(owner_uid, sandbox=sandbox)
            snapshot = []
            for emp in employees:
                if emp.get("status") == "activo":
                    snapshot.append({
                        "employeeId": emp.get("id", ""),
                        "cedula": (emp.get("cedula") or emp.get("idNumber", "")).replace("-", ""),
                        "fullName": emp.get("fullName", ""),
                        "position": emp.get("position", ""),
                        "baseSalary": emp.get("baseSalary", emp.get("salary", 0)),
                        "contractType": emp.get("contractType", ""),
                        "status": emp.get("status", ""),
                        "hireDate": emp.get("hireDate", ""),
                        "terminationDate": emp.get("terminationDate", ""),
                    })
            period["employeeSnapshot"] = snapshot
        except Exception as e:
            print(f"⚠️ Error guardando snapshot empleados para DGT-4: {e}")

    if owner_uid:
        from app.services.payroll_audit_service import log_action
        log_action(owner_uid, to_status, "payroll_period", period.get("id", ""),
                   user_email, changes={"from": from_status, "to": to_status}, comment=comment, sandbox=sandbox)

    return True, "OK"


def _ensure_payroll_accounting_entry(period, period_id, owner_uid, company_id, sandbox) -> tuple:
    """Genera el asiento contable de nómina si aún no se generó. Retorna (ok, msg)."""
    if period.get("accountingEntryGenerated"):
        return True, "OK"
    from app.services.payroll_service import PayrollService
    try:
        from app.services.accounting_service import AccountingService
        from app.services.db_service import DatabaseService
        from app.services.hr_data_service import get_tax_rates_snapshot
        snapshot = get_tax_rates_snapshot(period)
        tax_rates_data = snapshot if isinstance(snapshot, dict) and snapshot else hr.get_tax_rates(company_id, sandbox=sandbox)
        now_str = date.today().isoformat()
        employees_list = hr.get_employees(company_id, sandbox=sandbox)
        emp_map = {e["id"]: e for e in employees_list}
        acct_lines = PayrollService.build_payroll_accounting_lines(period, employees=emp_map, tax_rates=tax_rates_data,
                                                                   company_id=company_id, sandbox=sandbox)
        if acct_lines:
            AccountingService.seed_default_accounts(company_id, country=get_current_country())
            accounts = DatabaseService.get_chart_of_accounts(owner_uid, company_id=company_id)
            full_lines = []
            for al in acct_lines:
                acc = next((a for a in accounts if a.get("code") == al["accountCode"]), None)
                if acc:
                    full_lines.append({
                        "accountId": acc["id"],
                        "accountCode": al["accountCode"],
                        "accountName": al["accountName"],
                        "debit": al["debit"],
                        "credit": al["credit"],
                        "description": al["description"],
                    })
            if full_lines:
                AccountingService.generate_entry(company_id, {
                    "entryType": "payroll",
                    "date": now_str,
                    "concept": f"Nómina período {period.get('periodRange') or period.get('periodKey')}",
                    "referenceType": "payroll",
                    "referenceId": period_id,
                    "referenceNumber": period.get("periodKey", ""),
                    "lines": full_lines,
                    "createdBy": session.get("user", {}).get("email", "system"),
                    "prefix": "NOM",
                }, sandbox=sandbox)
                period["accountingEntryGenerated"] = True
        else:
            return False, "No se generaron líneas contables para este período."
    except Exception as e:
        return False, f"Error al generar asiento contable: {e}"
    return True, "OK"


def apply_payroll_authorization(company_id, period_id, to_status, comment="",
                                owner_uid="", sandbox=True, skip_sod=False) -> tuple:
    """Aplica una autorizacion resuelta en la cola sobre el periodo de nomina.

    Maquina de estados de autorizacion de nomina
    =============================================

    La autorizacion controla el *avance* del flujo de nomina, NO el estado de
    negocio de la nomina en si.  El status principal del periodo solo cambia
    cuando la autorizacion es aprobada (avanza a la siguiente etapa); los
    rechazos y devoluciones dejan el status principal intacto y solo actualizan
    el ``authorizationStageHistory``.

    ┌────────────────────┬──────────────────┬──────────────────────────────────┐
    │ Tipo autorizacion  │ Estado nomina    │ Decision  →  Efecto              │
    ├────────────────────┼──────────────────┼──────────────────────────────────┤
    │ payroll_approval   │ validada         │ approved   → status = aprobada   │
    │ payroll_approval   │ validada         │ rejected   → permanece validada  │
    │                    │                  │              stage = rechazada    │
    │ payroll_approval   │ validada         │ returned   → permanece validada  │
    │                    │                  │              stage = devuelta     │
    ├────────────────────┼──────────────────┼──────────────────────────────────┤
    │ payroll_post_      │ aprobada         │ approved   → status =            │
    │ accounting         │                  │              contabilizada       │
    │ payroll_post_      │ aprobada         │ rejected   → permanece aprobada  │
    │ accounting         │                  │              stage = rechazada    │
    │ payroll_post_      │ aprobada         │ returned   → permanece aprobada  │
    │ accounting         │                  │              stage = devuelta     │
    └────────────────────┴──────────────────┴──────────────────────────────────┘

    La transicion del status principal (validada→aprobada→contabilizada) solo
    ocurre con decision ``approved``.  ``rejected`` y ``returned`` actualizan
    unicamente el stage dentro de ``authorizationStageHistory`` sin tocar
    ``status``.
    """
    from app.services import hr_data_service as hr
    from datetime import datetime, timezone

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        return False, "Periodo de nomina no encontrado"

    now = datetime.now(timezone.utc).isoformat()

    # ── Solo-stage: rechazada / devuelta ──
    if to_status in ("rechazada", "devuelta"):
        for stage in period.get("authorizationStageHistory", []):
            if stage.get("status") == "pending":
                stage["status"] = to_status
                stage["resolvedAt"] = now
                stage["resolvedBy"] = owner_uid
                break
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
        return True, "OK"

    # ── Transicion de status principal: aprobada / contabilizada ──
    for stage in period.get("authorizationStageHistory", []):
        if stage.get("status") == "pending":
            stage["status"] = to_status
            stage["resolvedAt"] = now
            stage["resolvedBy"] = owner_uid
            break

    if to_status == "contabilizada":
        ok, msg = _ensure_payroll_accounting_entry(period, period_id, owner_uid, company_id, sandbox)
        if not ok:
            return False, msg

    ok, msg = _transition(period, to_status, comment, sandbox=sandbox, skip_sod=skip_sod)
    if ok:
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
    return ok, msg


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/bank-export")
def payroll_bank_export(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.bank_export_service import generate_bank_file
    from app.services.db_service import _cached_company_profile, DatabaseService

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    # Asegurar que las líneas estén cargadas, ya que pueden estar en una subcolección
    period["lines"] = hr.get_payroll_lines_unified(period, company_id, sandbox=sandbox)

    # Obtener perfil de empresa para datos del header
    profile = _cached_company_profile(owner_uid, company_id=company_id)
    company_doc = DatabaseService.get_company(company_id) or {}
    
    # 1. Resolver el nombre de la empresa
    company_name = profile.get("companyName", "").strip()
    # Si está vacío o tiene nombres por defecto, buscar en company_doc
    if not company_name or company_name.upper() in ["MI EMPRESA SRL", "MI EMPRESA"]:
        company_name = company_doc.get("trade_name") or company_doc.get("name") or company_doc.get("businessName") or company_doc.get("tradeName") or "MI EMPRESA SRL"
        
    # 2. Resolver el RNC
    company_rnc = profile.get("companyRNC", "").strip()
    if not company_rnc or company_rnc == "132109122":
        company_rnc = company_doc.get("rnc") or company_doc.get("companyRNC") or ""
    company_rnc = company_rnc.replace("-", "")[:9]
    
    # Resolver código de contrato (si no hay rnc, cae al predeterminado de profile)
    company_code = company_rnc or _cached_company_profile.__wrapped__(owner_uid, company_id=company_id).get("company_code", "101003383")
    
    # 3. Resolver email
    company_email = profile.get("companyEmail", "").strip()
    if not company_email or company_email == "factura@miempresa.com.do":
        company_email = company_doc.get("email", "")
    # Si no hay RNC, usar código de contrato del banco (configurable)
    bank_contract = request.args.get("contract_code", company_code.zfill(9)[:9])

    bank = request.args.get("bank", "popular")
    employees_list = hr.get_employees(company_id, sandbox=sandbox)
    emp_map = {e["id"]: e for e in employees_list}
    content = generate_bank_file(period, emp_map, bank=bank,
                                 company_name=company_name,
                                 company_code=bank_contract,
                                 company_email=company_email)

    import io as _io
    buffer = _io.BytesIO(content)
    return send_file(buffer, mimetype="text/plain", as_attachment=True,
                     download_name=f"Nomina_{period.get('periodKey','')}_{bank}.txt")


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/validate", methods=["POST"])
def payroll_validate(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    ok, msg = _transition(period, "validada", request.form.get("comment", ""),
                          sandbox=sandbox)
    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
        flash("Nómina validada.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/approve", methods=["POST"])
def payroll_approve(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    period["lines"] = hr.get_payroll_lines_unified(period, company_id, sandbox=sandbox)

    from app.services.hr_authorization_service import create_authorization_request
    from datetime import datetime, timezone
    user = session.get("user", {})
    now = datetime.now(timezone.utc).isoformat()
    
    # Generate justification text
    justification_text = f"Nómina {period.get('periodRange') or period.get('periodKey')}\n"
    justification_text += f"Empleados: {len(period.get('lines', []))}\n"
    total_neto = float(period.get('totalNet', 0) or 0)
    total_bruto = float(period.get('totalGross', 0) or 0)
    justification_text += f"Total Bruto: RD$ {total_bruto:,.2f}\n"
    justification_text += f"Total Neto: RD$ {total_neto:,.2f}\n"
    
    # Find previous payroll
    all_periods = hr.get_payroll_periods(company_id, sandbox=sandbox)
    group_id = period.get("groupId")
    start_date = period.get("startDate", "")
    prev_periods = [p for p in all_periods if p.get("groupId") == group_id and p.get("startDate", "") < start_date and p.get("status") in ("aprobada", "contabilizada", "pagada")]
    prev_periods.sort(key=lambda x: x.get("startDate", ""), reverse=True)
    
    if prev_periods:
        prev = prev_periods[0]
        prev_neto = float(prev.get('totalNet', 0) or 0)
        if prev_neto:
            var_pct = ((total_neto - prev_neto) / prev_neto) * 100
            sign = "+" if var_pct > 0 else ""
            justification_text += f"Variación vs anterior: {sign}{var_pct:.2f}% (Anterior: RD$ {prev_neto:,.2f})"
        else:
            justification_text += f"Variación vs anterior: N/A (Anterior: RD$ {prev_neto:,.2f})"

    req_result = create_authorization_request(
        company_id,
        doc_type="payroll_approval",
        doc_id=period_id,
        doc_number=period.get("periodKey", ""),
        entity_type="payroll",
        created_by_uid=user.get("uid", ""),
        created_by_email=user.get("email", ""),
        created_by_name=user.get("name", ""),
        sandbox=sandbox,
        metadata={"periodKey": period.get("periodKey", ""), "justification": justification_text},
        link=f"/rrhh/payroll/{period_id}",
        owner_uid=owner_uid,
        justification=justification_text,
    )

    stage = {"stage": "payroll_approval", "requestId": req_result["request"]["id"],
             "status": "pending", "createdAt": now, "createdBy": user.get("email","")}
    period.setdefault("authorizationStageHistory", []).append(stage)

    if not req_result["approved"]:
        period["authorizationRequestId"] = req_result["request"]["id"]
        period["authorizationStatus"] = "pending"
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
        flash("Nomina enviada a la cola de autorizacion.", "success")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    stage["status"] = "approved"
    stage["resolvedAt"] = now
    stage["resolvedBy"] = user.get("email","")
    ok, msg = _transition(period, "aprobada", request.form.get("comment", ""),
                          sandbox=sandbox, skip_sod=req_result["request"].get("isFallback", False))
    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
        flash("Nomina aprobada.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/post", methods=["POST"])
def payroll_post(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    # Enviar a la cola de autorización antes de contabilizar
    from app.services.hr_authorization_service import create_authorization_request
    from datetime import datetime, timezone
    user = session.get("user", {})
    now = datetime.now(timezone.utc).isoformat()
    req_result = create_authorization_request(
        company_id,
        doc_type="payroll_post_accounting",
        doc_id=period_id,
        doc_number=period.get("periodKey", ""),
        entity_type="payroll",
        created_by_uid=user.get("uid", ""),
        created_by_email=user.get("email", ""),
        created_by_name=user.get("name", ""),
        sandbox=sandbox,
        metadata={"periodKey": period.get("periodKey", "")},
        link=f"/rrhh/payroll/{period_id}",
        owner_uid=owner_uid,
    )

    stage = {"stage": "payroll_post_accounting", "requestId": req_result["request"]["id"],
             "status": "pending", "createdAt": now, "createdBy": user.get("email","")}
    period.setdefault("authorizationStageHistory", []).append(stage)

    if not req_result["approved"]:
        period["authorizationRequestId"] = req_result["request"]["id"]
        period["authorizationStatus"] = "pending"
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
        flash("Contabilización enviada a la cola de autorización.", "success")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    stage["status"] = "approved"
    stage["resolvedAt"] = now
    stage["resolvedBy"] = user.get("email","")
    # Generar asiento contable
    ok, msg = _ensure_payroll_accounting_entry(period, period_id, owner_uid, company_id, sandbox)
    if not ok:
        flash(msg, "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    ok, msg = _transition(period, "contabilizada", request.form.get("comment", ""),
                          sandbox=sandbox, skip_sod=req_result["request"].get("isFallback", False))
    if not ok:
        flash(msg, "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
    flash("Nómina contabilizada exitosamente.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/pay", methods=["POST"])
def payroll_pay(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    ok, msg = _transition(period, "pagada", request.form.get("comment", ""),
                          sandbox=sandbox)
    if not ok:
        flash(msg, "error")
    else:
        period["paidDate"] = date.today().isoformat()
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
        flash("Nómina marcada como pagada.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/close", methods=["POST"])
def payroll_close(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    ok, msg = _transition(period, "cerrada", request.form.get("comment", ""),
                          sandbox=sandbox)
    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
        flash("Nómina cerrada. No se permiten más modificaciones.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/send-payslips", methods=["POST"])
def payroll_send_payslips(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    lines = PayrollService.get_period_lines(period, company_id=company_id, sandbox=sandbox)
    employees_list = hr.get_employees(company_id, sandbox=sandbox)
    emp_map = {e["id"]: e for e in employees_list}

    try:
        from app.services.mailer import Mailer
    except Exception as e:
        flash("Error al cargar dependencias de correo.", "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    period_label = period.get("periodRange") or period.get("periodKey", "")
    sent = 0
    skipped = 0
    errors = 0

    for line in lines:
        emp_id = line.get("employeeId", "")
        emp = emp_map.get(emp_id, {})
        email = (emp.get("email") or "").strip()
        if not email:
            skipped += 1
            continue
        try:
            html_body = render_template("rrhh/employee_payslip_email.html",
                                        employee=emp, period=period, line=line)
            subject = f"Volante de pago — {period_label}"
            Mailer.send(
                app=current_app._get_current_object(),
                to_email=email,
                subject=subject,
                html_body=html_body,
                from_name=current_app.config.get("COMPANY_NAME", ""),
                category="noreply",
            )
            sent += 1
        except Exception as e:
            print(f"⚠️ Error enviando volante a {email}: {e}")
            errors += 1

    period["payslipsSentAt"] = datetime.now(timezone.utc).isoformat()
    period["payslipsSentBy"] = session.get("user", {}).get("email", "")
    hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)

    if sent > 0 and errors == 0:
        flash(f"Volantes enviados a {sent} empleado(s). {skipped} omitido(s) sin email.", "success")
    elif sent > 0:
        flash(f"{sent} enviado(s), {errors} error(es), {skipped} omitido(s) sin email.", "warning")
    else:
        flash(f"No se envió ningún volante. {skipped} empleado(s) sin email.", "warning")

    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/send-payslips/async", methods=["POST"])
def payroll_send_payslips_async(period_id):
    if _login_required():
        return jsonify({"error": "unauthorized"}), 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_async_service import create_job, update_job

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        return jsonify({"error": "period not found"}), 404

    lines = PayrollService.get_period_lines(period, company_id=company_id, sandbox=sandbox)
    employees_list = hr.get_employees(company_id, sandbox=sandbox)
    emp_map = {e["id"]: e for e in employees_list}

    try:
        from app.services.mailer import Mailer
    except Exception as e:
        return jsonify({"error": "mailer unavailable"}), 500

    job_id = create_job(company_id, sandbox=sandbox)
    if not job_id:
        return jsonify({"error": "could not create job"}), 500

    period_label = period.get("periodRange") or period.get("periodKey", "")
    total = len(lines)

    update_job(company_id, job_id, {
        "status": "running",
        "progress": 0,
        "total": total,
        "message": "Iniciando envío de volantes...",
    }, sandbox=sandbox)

    def _send_worker():
        import flask
        sent = 0
        skipped = 0
        errors = 0
        for idx, line in enumerate(lines):
            emp_id = line.get("employeeId", "")
            emp = emp_map.get(emp_id, {})
            email = (emp.get("email") or "").strip()
            if not email:
                skipped += 1
                update_job(company_id, job_id, {
                    "progress": idx + 1,
                    "message": f"Omitido {idx+1}/{total}: {emp.get('fullName','')} sin email",
                }, sandbox=sandbox)
                continue
            try:
                with current_app.app_context():
                    html_body = flask.render_template("rrhh/employee_payslip_email.html",
                                                       employee=emp, period=period, line=line)
                    subject = f"Volante de pago — {period_label}"
                    Mailer.send(
                        app=current_app._get_current_object(),
                        to_email=email,
                        subject=subject,
                        html_body=html_body,
                        from_name=current_app.config.get("COMPANY_NAME", ""),
                        category="noreply",
                    )
                sent += 1
                update_job(company_id, job_id, {
                    "progress": idx + 1,
                    "message": f"Enviado {idx+1}/{total}: {emp.get('fullName','')}",
                }, sandbox=sandbox)
            except Exception as e:
                errors += 1
                print(f"⚠️ Error enviando volante a {email}: {e}")
                update_job(company_id, job_id, {
                    "progress": idx + 1,
                    "message": f"Error {idx+1}/{total}: {emp.get('fullName','')} — {e}",
                }, sandbox=sandbox)

        msg = f"Completado: {sent} enviado(s), {skipped} omitido(s), {errors} error(es)"
        update_job(company_id, job_id, {
            "status": "completed",
            "progress": total,
            "message": msg,
            "result": {"sent": sent, "skipped": skipped, "errors": errors},
        }, sandbox=sandbox)

        period["payslipsSentAt"] = datetime.now(timezone.utc).isoformat()
        period["payslipsSentBy"] = session.get("user", {}).get("email", "")
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)

    import threading
    t = threading.Thread(target=_send_worker, daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "status": "created"})


@web_rrhh_bp.route("/rrhh/payroll/jobs/<job_id>/status")
def payroll_job_status(job_id):
    if _login_required():
        return jsonify({"error": "unauthorized"}), 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.payroll_async_service import get_job
    job = get_job(company_id, job_id, sandbox=sandbox)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "total": job.get("totalItems", 0),
        "processedItems": job.get("processedItems", 0),
        "message": job.get("message", ""),
        "result": job.get("result"),
        "error": job.get("error"),
    })


@web_rrhh_bp.route("/rrhh/payroll/progress/<job_id>")
def payroll_progress(job_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/payroll_progress.html", active_page="rrhh_payroll", job_id=job_id)


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/recalculate", methods=["POST"])
def payroll_recalculate(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    status = period.get("status", "")
    if status == "cerrada":
        flash("No se puede modificar una nómina cerrada.", "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    # Confirmación requerida para estados avanzados
    confirm = request.form.get("confirm", "")
    target = "borrador"
    comment = "Recálculo solicitado"

    if status in ("contabilizada", "pagada"):
        # Revertir paso a paso con confirmación explícita
        if confirm != "RECALCULAR":
            flash("Para revertir una nómina contabilizada o pagada, debes escribir RECALCULAR en el campo de confirmación.", "warning")
            return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))
        comment = "Reversión forzada con confirmación explícita"
        # Primero revertir al estado anterior
        if status == "pagada":
            prev_ok, prev_msg = _transition(period, "contabilizada", "Reversión desde pagada",
                                            owner_uid=company_id, sandbox=sandbox)
            if not prev_ok:
                flash(prev_msg, "error")
                return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))
            status = "contabilizada"
        if status == "contabilizada":
            prev_ok, prev_msg = _transition(period, "aprobada", "Reversión desde contabilizada",
                                            owner_uid=company_id, sandbox=sandbox)
            if not prev_ok:
                flash(prev_msg, "error")
                return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))
        # Ahora a borrador
        ok, msg = _transition(period, "borrador", comment,
                              owner_uid=company_id, sandbox=sandbox)
    else:
        ok, msg = _transition(period, target, comment,
                              owner_uid=company_id, sandbox=sandbox)

    if not ok:
        flash(msg, "error")
    else:
        hr.save_payroll_period(company_id, period_id, period, sandbox=sandbox)
        period_key = period.get("periodKey", "")
        hr.delete_rule_logs_by_period_key(company_id, period_key, sandbox=sandbox)
        flash("Nómina revertida a borrador. Puede recalcularla desde «Procesar nómina».", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/delete", methods=["POST"])
def payroll_delete(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_audit_service import log_action

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    status = period.get("status", "")
    if status != "borrador":
        flash("Solo se pueden eliminar nóminas en estado borrador. Revierta la nómina primero.", "error")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    confirm = request.form.get("confirm", "")
    if confirm != "ELIMINAR":
        flash("Debes escribir ELIMINAR en el campo de confirmación para borrar definitivamente.", "warning")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    period_key = period.get("periodKey", "")
    period_range = period.get("periodRange", "")
    user_email = session.get("user", {}).get("email", "")

    log_action(company_id, "delete", "payroll_period", period_id, user_email,
               changes={"period": period_key, "status": status, "range": period_range},
               comment="Eliminación de período de nómina", sandbox=sandbox)

    hr.delete_payroll_period(company_id, period_id, sandbox=sandbox)
    hr.delete_rule_logs_by_period_key(company_id, period_key, sandbox=sandbox)
    flash(f"Período de nómina «{period_range or period_key}» eliminado permanentemente.", "success")
    return redirect(url_for("web_rrhh.payroll_list"))


# ═══════════════════════════════════════════════════════════════════════════
# CONCILIACIÓN BANCARIA DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/<period_id>/reconcile")
def payroll_reconcile(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_reconciliation_service import PayrollReconciliationService

    period = hr.get_payroll_period(company_id, period_id, sandbox=sandbox)
    if not period:
        flash("Período no encontrado.", "error")
        return redirect(url_for("web_rrhh.payroll_list"))

    period["lines"] = PayrollService.get_period_lines(period, company_id=company_id, sandbox=sandbox)
    employees = {e["id"]: e for e in hr.get_employees(company_id, sandbox=sandbox)}

    tx_from = request.args.get("tx_from", period.get("startDate", ""))
    tx_to = request.args.get("tx_to", period.get("endDate", ""))
    bank_transactions = []
    if tx_from and tx_to:
        try:
            from app.services.db_service import DatabaseService
            bank_transactions = DatabaseService.get_bank_transactions(
                owner_uid, date_from=tx_from, date_to=tx_to
            )
        except (AttributeError, Exception):
            bank_transactions = []

    result = None
    suggestions = None
    if bank_transactions:
        result = PayrollReconciliationService.reconcile_period(period, bank_transactions, employees=employees)
    else:
        suggestions = PayrollReconciliationService.suggest_reconciliation(period, employees=employees)

    return render_template("rrhh/payroll_reconcile.html", active_page="rrhh_payroll",
                           period=period, result=result, suggestions=suggestions,
                           tx_from=tx_from, tx_to=tx_to)


@web_rrhh_bp.route("/rrhh/payroll/<period_id>/reconcile/load-transactions", methods=["POST"])
def payroll_reconcile_load_transactions(period_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    tx_from = request.form.get("tx_from", "")
    tx_to = request.form.get("tx_to", "")
    return redirect(url_for("web_rrhh.payroll_reconcile", period_id=period_id,
                           tx_from=tx_from, tx_to=tx_to))


