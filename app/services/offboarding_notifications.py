"""OffboardingNotifications — Notificaciones por email para el módulo Offboarding.

Se integra con OffboardingService.transition() para enviar alertas
automáticas al empleado, supervisor y RRHH en cada cambio de estado.
"""

from flask import render_template, current_app

from app.services.mailer import Mailer
from app.models.offboarding import OFFBOARDING_STATES


# ── Mapa: estado → destinatarios ──────────────────────────────────────────

VOLUNTARY_TYPES = {"renuncia_voluntaria", "dimision_justificada", "mutuo_acuerdo",
                    "jubilacion", "fin_contrato_temporal", "otro"}

INVOLUNTARY_TYPES = {"desahucio_empleador", "despido_justificado",
                     "despido_injustificado", "abandono"}

FALLECIMIENTO_TYPE = {"fallecimiento"}

PRE_APPROVAL_STATES = {"draft", "pending_supervisor_approval", "pending_hr_approval"}


NOTIFICATION_RULES = {
    "draft":                         {"to": ["supervisor"], "subject": "Solicitud de salida creada"},
    "pending_supervisor_approval":      {"to": ["employee", "supervisor"], "subject": "Aprobación de supervisor requerida"},
    "pending_hr_approval":           {"to": ["hr"], "subject": "Aprobación de RRHH requerida"},
    "approved":                      {"to": ["employee", "supervisor"], "subject": "Solicitud de salida aprobada"},
    "pending_settlement":            {"to": ["hr"], "subject": "Liquidación pendiente de calcular"},
    "pending_assets":                {"to": ["employee", "supervisor"], "subject": "Devolución de activos pendiente"},
    "pending_payment":               {"to": ["employee"], "subject": "Pago de liquidación pendiente"},
    "pending_documents":             {"to": ["hr"], "subject": "Documentos de salida pendientes"},
    "pending_tss":                   {"to": ["hr"], "subject": "Notificación TSS pendiente"},
    "completed":                     {"to": ["employee", "supervisor", "hr"], "subject": "Proceso de salida completado"},
    "cancelled":                     {"to": ["employee", "supervisor"], "subject": "Solicitud de salida cancelada"},
    "rejected":                      {"to": ["employee", "supervisor"], "subject": "Solicitud de salida rechazada"},
    "access_revoked":                {"to": ["hr"], "subject": "Accesos del empleado desactivados"},
}


def _get_employee_email(owner_uid: str, employee_id: str, sandbox: bool, company_id=None) -> str:
    from app.services import hr_data_service as hr
    emp = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if emp:
        return emp.get("email", "") or emp.get("personalEmail", "")
    return ""


def _get_employee_supervisor_email(owner_uid: str, employee_id: str, sandbox: bool, company_id=None) -> str:
    from app.services import hr_data_service as hr
    emp = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if emp and emp.get("supervisorId"):
        sup = hr.get_employee(company_id, emp["supervisorId"], sandbox=sandbox)
        if sup:
            return sup.get("email", "") or ""
    return ""


def _get_hr_emails(owner_uid: str, sandbox: bool, company_id=None) -> list[str]:
    from app.services import hr_data_service as hr
    employees = hr.get_employees(company_id, sandbox=sandbox)
    hr_emails = []
    for e in employees:
        role = e.get("role", "") or e.get("position", "")
        if "rrhh" in role.lower() or "hr" in role.lower() or "recursos" in role.lower():
            email = e.get("email", "")
            if email:
                hr_emails.append(email)
    return hr_emails if hr_emails else []


def notify_transition(
    app,
    owner_uid: str,
    sandbox: bool,
    request_data: dict,
    old_status: str,
    new_status: str,
    changed_by: str,
    company_id=None,
):
    """Envía notificaciones según la transición de estado."""
    if not app:
        return

    rule = NOTIFICATION_RULES.get(new_status)
    if not rule:
        return

    employee_id = request_data.get("employeeId", "")
    employee_name = request_data.get("employeeName", "Empleado")
    termination_type = request_data.get("terminationType", "")
    company_name = app.config.get("COMPANY_NAME", "VykOne ERP")

    def _should_notify_employee() -> bool:
        if termination_type in FALLECIMIENTO_TYPE:
            return False
        if termination_type in INVOLUNTARY_TYPES and new_status in PRE_APPROVAL_STATES:
            return False
        return True

    recipients = []
    for target in rule.get("to", []):
        if target == "employee":
            if not _should_notify_employee():
                continue
            email = _get_employee_email(owner_uid, employee_id, sandbox, company_id=company_id)
            if email:
                recipients.append(email)
        elif target == "supervisor":
            email = _get_employee_supervisor_email(owner_uid, employee_id, sandbox, company_id=company_id)
            if email:
                recipients.append(email)
        elif target == "hr":
            hr_list = _get_hr_emails(owner_uid, sandbox, company_id=company_id)
            recipients.extend(hr_list)

    if not recipients:
        return

    status_label = OFFBOARDING_STATES.get(new_status, {}).get("label", new_status)
    subject = f"[{company_name}] {rule['subject']} — {employee_name}"

    html_body = render_template(
        "rrhh/offboarding/email_notification.html",
        employee_name=employee_name,
        request_data=request_data,
        old_status=old_status,
        new_status=new_status,
        status_label=status_label,
        changed_by=changed_by,
        OFFBOARDING_STATES=OFFBOARDING_STATES,
    )

    try:
        Mailer.send(
            app=app,
            to_email=recipients[0] if len(recipients) == 1 else recipients,
            subject=subject,
            html_body=html_body,
            from_name=company_name,
            category="notification",
        )
    except Exception as e:
        print(f"⚠️ OffboardingNotification: error enviando email — {e}")
