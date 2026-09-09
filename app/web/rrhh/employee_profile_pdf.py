"""Ficha de empleado en PDF con estilo CV moderno.

Genera en `/rrhh/employees/<employee_id>/profile.pdf` un documento multipágina
con foto, resumen profesional de 1-2 párrafos generado por IA (fresco en cada
descarga, con respaldo determinístico si no hay API key), todos los datos del
empleado y su historial laboral/trayectoria completo.
"""

import io
from datetime import date, datetime

from flask import render_template, request, redirect, url_for, session, flash, send_file

from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _sanitize_for_role,
)
from app.web.rrhh.employees import _load_employee_context
from app.web.rrhh.work_certificate import _get_company_data
from app.services.ai_service import AIService
from app.utils.pdf import pdf_write_options


EDUCATION_LABELS = {
    1: "Primaria", 2: "Secundaria", 3: "Técnico",
    4: "Grado", 5: "Postgrado", 6: "Ninguno",
}
MARITAL_LABELS = {
    "S": "Soltero/a", "C": "Casado/a", "U": "Unión libre",
    "D": "Divorciado/a", "V": "Viudo/a",
}
SHIFT_LABELS = {1: "Diurno", 2: "Nocturno", 3: "Mixto"}
STATUS_LABELS = {
    "activo": "Activo", "inactivo": "Inactivo", "suspendido": "Suspendido",
    "vacaciones": "De vacaciones", "licencia": "De licencia",
}

# Acciones del timeline que aportan a la trayectoria profesional del resumen.
_MILESTONE_KINDS = {
    ("mass", "promotion"), ("mass", "position_change"), ("mass", "salary_change"),
    ("mass", "supervisor_change"), ("mass", "desvinculacion"),
    ("audit", "create"), ("audit", "rehire"), ("audit", "update"),
    ("audit", "employee_marked_inactive"), ("audit", "employee_reactivated"),
}


def _tenure_text(hire_date: str) -> str:
    """Calcula la antigüedad en texto (ej. '3 años y 2 meses')."""
    if not hire_date:
        return ""
    try:
        started = datetime.strptime(str(hire_date)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    today = date.today()
    if started > today:
        return ""
    months = ((today.year - started.year) * 12 + (today.month - started.month)
              - (1 if today.day < started.day else 0))
    months = max(months, 0)
    years, rest = divmod(months, 12)
    if years and rest:
        return f"{years} año{'s' if years > 1 else ''} y {rest} mes{'es' if rest > 1 else ''}"
    if years:
        return f"{years} año{'s' if years > 1 else ''}"
    if rest:
        return f"{rest} mes{'es' if rest > 1 else ''}"
    days = (today - started).days
    return f"{days} día{'s' if days != 1 else ''}"


def _fmt_rd(value) -> str:
    if isinstance(value, str) and value and set(value) <= {"*"}:
        return value  # valor sanitizado por rol (sin permiso HR)
    try:
        return "RD$ {:,.2f}".format(float(value or 0))
    except (TypeError, ValueError):
        return "—"


def _avg_evaluation(evaluations: list):
    """Promedio de puntajes (escala /5) o None si no hay datos."""
    scores = []
    for ev in evaluations or []:
        try:
            scores.append(float(ev.get("score", 0) or 0))
        except (TypeError, ValueError):
            continue
    scores = [s for s in scores if s > 0]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


def _milestones(timeline: list, limit: int = 8) -> list:
    """Extrae los hitos de trayectoria (promociones, cambios, altas/bajas)."""
    out = []
    for it in timeline or []:
        key = (it.get("kind", ""), it.get("action", ""))
        category = it.get("category", "")
        is_status = it.get("kind") == "status"
        if key not in _MILESTONE_KINDS and category not in ("vacaciones", "licencia") and not is_status:
            if category in ("pago", "carta", "hora_extra", "evaluacion",
                            "capacitacion", "herramienta", "empleado"):
                continue
        label = (it.get("label") or "").strip()
        detail = (it.get("detail") or "").strip()
        when = (it.get("_date") or "").strip()
        text = f"{label}: {detail}" if detail and detail != "—" else label
        if len(text) > 140:
            text = text[:137].rstrip() + "…"
        if when:
            text = f"{text} ({when})"
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _build_bio_input(ctx: dict, company: dict) -> dict:
    """Arma el contexto minimizado (sin PII sensible) para el resumen IA."""
    employee = ctx.get("employee") or {}
    evaluations = ctx.get("evaluations") or []
    trainings = ctx.get("trainings") or []
    status = employee.get("status", "")
    level = employee.get("educationLevel", "")
    try:
        education = EDUCATION_LABELS.get(int(level), "")
    except (TypeError, ValueError):
        education = ""
    return {
        "fullName": employee.get("fullName", ""),
        "position": employee.get("position", ""),
        "department": employee.get("department") or employee.get("area", ""),
        "companyName": company.get("tradeName") or company.get("companyName", ""),
        "hireDate": employee.get("hireDate", ""),
        "tenure": _tenure_text(employee.get("hireDate", "")),
        "contractType": employee.get("contractType", ""),
        "statusLabel": STATUS_LABELS.get(status, status or ""),
        "education": education or ctx.get("sirla_education_label", ""),
        "occupationCode": employee.get("occupationCode", ""),
        "trainings": [t.get("trainingName", "") for t in trainings if t.get("trainingName")][:8],
        "evaluationsCount": len(evaluations),
        "avgEvaluation": _avg_evaluation(evaluations),
        "milestones": _milestones(ctx.get("timeline") or []),
        "dependentsCount": len(ctx.get("dependents") or []),
    }


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/profile.pdf")
def employee_profile_pdf(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    ctx = _load_employee_context(company_id, employee_id, owner_uid, sandbox=sandbox)
    if not ctx:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))
    ctx["employee"] = _sanitize_for_role(ctx["employee"])
    employee = ctx["employee"]

    company = _get_company_data(owner_uid, company_id)

    # Opción del modal "Imprimir ficha": incluir u omitir el historial de pagos.
    # Sin parámetro se incluye todo (comportamiento original).
    show_payments = request.args.get("include_payments", "1") != "0"

    # ── Resumen profesional IA (fresco en cada descarga, con respaldo local) ──
    bio_input = _build_bio_input(ctx, company)
    bio_text = AIService.build_employee_bio_template(bio_input)
    try:
        bio_result = AIService.generate_employee_bio(
            owner_uid, bio_input, company_id=company_id)
        if bio_result.get("success") and (bio_result.get("text") or "").strip():
            bio_text = bio_result["text"].strip()
    except Exception as e:
        print(f"employee_profile_pdf: resumen IA no disponible ({e}), usando plantilla.")

    level = employee.get("educationLevel", "")
    try:
        education_label = EDUCATION_LABELS.get(int(level), "")
    except (TypeError, ValueError):
        education_label = ""

    try:
        from weasyprint import HTML as WeasyprintHTML
        rendered = render_template(
            "rrhh/employee_profile_pdf.html",
            bio=bio_text,
            company=company,
            now=date.today().strftime("%d/%m/%Y"),
            tenure=_tenure_text(employee.get("hireDate", "")),
            education_label=education_label,
            marital_label=MARITAL_LABELS.get(employee.get("maritalStatus", ""), ""),
            shift_label=SHIFT_LABELS.get(employee.get("workShift"), ""),
            status_label=STATUS_LABELS.get(employee.get("status", ""), employee.get("status", "")),
            avg_evaluation=_avg_evaluation(ctx.get("evaluations") or []),
            fmt_rd=_fmt_rd,
            show_payments=show_payments,
            **ctx,
        )
        pdf_bytes = WeasyprintHTML(string=rendered, base_url=request.host_url).write_pdf(**pdf_write_options())

        try:
            from app.services.payroll_audit_service import log_employee_action
            log_employee_action(
                company_id, employee_id, "profile_pdf_generated",
                comment="Ficha de empleado en PDF generada",
                changes={"includePayments": show_payments},
                user_email=session.get("user", {}).get("email", ""),
                sandbox=sandbox,
            )
        except Exception as e:
            print(f"⚠️ employee_profile_pdf.log_employee_action: {e}")

        code = employee.get("code") or employee_id
        filename = f"ficha_empleado_{code}.pdf"
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=False, download_name=filename)
    except Exception as e:
        print(f"Error generando PDF de ficha de empleado: {e}")
        flash("Error al generar el PDF.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))
