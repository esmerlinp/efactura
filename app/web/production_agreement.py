"""Contrato de Producción — rutas web de aceptación y reconocimiento."""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app

from app.services.db_service import DatabaseService
from app.services.production_agreement_service import ProductionAgreementService
from app.services.production_agreement_acceptance_service import ProductionAgreementAcceptanceService
from app.services.production_agreement_access_service import ProductionAgreementAccessService
from app.services.audit_service import (
    AuditService, MODULE_PRODUCTION_AGREEMENT,
    ACTION_AGREEMENT_VIEWED, ACTION_AGREEMENT_ACCEPTED,
    ACTION_AGREEMENT_ACKNOWLEDGED, ACTION_AGREEMENT_REJECTED,
)

web_production_agreement_bp = Blueprint("web_production_agreement", __name__)


def _client_ip():
    """IP de la solicitud, usando solo fuentes confiables según configuración.

    Por defecto se usa ``request.remote_addr``. Solo se confía en
    ``X-Forwarded-For`` cuando ``TRUST_PROXY_HEADERS`` está habilitado de forma
    explícita (despliegue detrás de un proxy confiable).
    """
    if current_app.config.get("TRUST_PROXY_HEADERS", False):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def _safe_next():
    from urllib.parse import urlparse
    next_url = request.args.get("next") or request.form.get("next") or ""
    if next_url:
        parsed = urlparse(next_url)
        if not parsed.netloc and not parsed.scheme:
            return next_url
    return ""


def _current_context():
    """Recupera el contexto de compañía/usuario desde la sesión."""
    user = session.get("user", {})
    company_id = session.get("selected_company_id", "")
    user_id = user.get("uid", "")
    return company_id, user_id, user


def _company_label(company_id):
    company = DatabaseService.get_company(company_id) if company_id else None
    name = ""
    rnc = ""
    if company:
        name = company.get("company_name") or company.get("name", "")
        rnc = company.get("rnc", "")
    return name, rnc


def _audit(action, company_id, user, label="", entity_id="", sandbox=False):
    try:
        AuditService.log_from_request(
            owner_uid=session.get("selected_owner_uid") or user.get("ownerUID", ""),
            action=action,
            module=MODULE_PRODUCTION_AGREEMENT,
            entity_id=entity_id or company_id,
            entity_label=label,
            user_session=user,
            sandbox=sandbox,
            company_id=company_id,
        )
    except Exception:
        pass


@web_production_agreement_bp.route("/production-agreement", methods=["GET"])
def view():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))

    sandbox = session.get("is_sandbox_mode", False)

    company_id, user_id, user = _current_context()
    if not company_id:
        return redirect(url_for("web_auth.select_company"))

    active = ProductionAgreementService.get_active_version()
    if not active:
        return redirect(url_for("web_dashboard.dashboard"))

    decision = ProductionAgreementAccessService.evaluate_web_access(company_id, user_id, sandbox=sandbox)
    if decision.allowed:
        return redirect(url_for("web_dashboard.dashboard"))

    company_name, rnc = _company_label(company_id)
    _audit(ACTION_AGREEMENT_VIEWED, company_id, user,
           label=f"Visualización del contrato ({'sandbox' if sandbox else 'producción'})",
           sandbox=sandbox)

    return render_template(
        "production_agreement/view.html",
        active_page="production_agreement",
        company_name=company_name,
        company_rnc=rnc,
        version=active.get("version", 0),
        version_id=active.get("id", ""),
        published_at=active.get("publishedAt", ""),
        content=active.get("content", ""),
        is_owner=decision.is_owner,
        company_agreement_ok=decision.company_agreement_ok,
        user_acknowledged=decision.user_acknowledged,
        requires_company_agreement=decision.requires_company_agreement,
        requires_user_acknowledgement=decision.requires_user_acknowledgement,
        next_url=_safe_next(),
        sandbox=sandbox,
        user_name=user.get("name", ""),
        user_email=user.get("email", ""),
    )


@web_production_agreement_bp.route("/production-agreement/accept-company", methods=["POST"])
def accept_company():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))

    sandbox = session.get("is_sandbox_mode", False)
    company_id, user_id, user = _current_context()
    if not company_id:
        return redirect(url_for("web_auth.select_company"))

    if request.form.get("accept") != "1":
        flash("Debes marcar la casilla de aceptación para continuar.", "error")
        return redirect(url_for("web_production_agreement.view"))

    result = ProductionAgreementAcceptanceService.accept_company(
        company_id=company_id,
        user_id=user_id,
        user_name=user.get("name", ""),
        user_email=user.get("email", ""),
        ip_address=_client_ip(),
        user_agent=request.headers.get("User-Agent", ""),
        sandbox=sandbox,
    )

    if result.get("ok"):
        _audit(ACTION_AGREEMENT_ACCEPTED, company_id, user,
               label="Aceptación contractual de la compañía",
               entity_id=result.get("version_id", ""), sandbox=sandbox)
        flash("Contrato aceptado correctamente.", "success")
    else:
        reason = result.get("reason", "")
        if reason == "not_owner":
            flash("Solo el propietario de la compañía puede aceptar el contrato.", "error")
        elif reason == "no_active_membership":
            flash("No tienes una membresía activa para esta compañía.", "error")
        else:
            flash("No se pudo registrar la aceptación. Inténtalo de nuevo.", "error")

    return _redirect_after_change(company_id, user_id, sandbox=sandbox)


@web_production_agreement_bp.route("/production-agreement/acknowledge", methods=["POST"])
def acknowledge():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))

    sandbox = session.get("is_sandbox_mode", False)
    company_id, user_id, user = _current_context()
    if not company_id:
        return redirect(url_for("web_auth.select_company"))

    if request.form.get("accept") != "1":
        flash("Debes marcar la casilla de reconocimiento para continuar.", "error")
        return redirect(url_for("web_production_agreement.view"))

    result = ProductionAgreementAcceptanceService.acknowledge_user(
        company_id=company_id,
        user_id=user_id,
        user_name=user.get("name", ""),
        user_email=user.get("email", ""),
        ip_address=_client_ip(),
        user_agent=request.headers.get("User-Agent", ""),
        sandbox=sandbox,
    )

    if result.get("ok"):
        _audit(ACTION_AGREEMENT_ACKNOWLEDGED, company_id, user,
               label="Reconocimiento individual del contrato",
               entity_id=result.get("version_id", ""), sandbox=sandbox)
        flash("Reconocimiento registrado correctamente.", "success")
    else:
        flash("No se pudo registrar tu reconocimiento. Inténtalo de nuevo.", "error")

    return _redirect_after_change(company_id, user_id, sandbox=sandbox)


@web_production_agreement_bp.route("/production-agreement/reject", methods=["POST"])
def reject():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))

    sandbox = session.get("is_sandbox_mode", False)
    company_id, user_id, user = _current_context()
    _audit(ACTION_AGREEMENT_REJECTED, company_id or "", user,
           label="Rechazo del contrato", sandbox=sandbox)
    flash("No has aceptado el contrato. No podrás operar en el sistema.", "warning")
    if sandbox:
        return redirect(url_for("web_dashboard.dashboard"))
    return redirect(url_for("web_auth.logout"))


def _redirect_after_change(company_id, user_id, sandbox=False):
    decision = ProductionAgreementAccessService.evaluate_web_access(company_id, user_id, sandbox=sandbox)
    if decision.allowed:
        next_url = _safe_next()
        if next_url:
            return redirect(next_url)
        return redirect(url_for("web_dashboard.dashboard"))
    return redirect(url_for("web_production_agreement.view"))
