from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.dgii_cert_service import DgiiCertService
from app.services.db_service import DatabaseService

web_certificacion_bp = Blueprint("web_certificacion", __name__)

STEP_LABELS = {
    1: "Registrado",
    2: "Pruebas de Datos e-CF",
    3: "Pruebas de Datos Aprobación Comercial",
    4: "Pruebas Simulación e-CF",
    5: "Pruebas Simulación Representación Impresa",
    6: "Validación Representación Impresa",
    7: "URL Servicios Prueba",
    8: "Inicio Prueba Recepción e-CF",
    9: "Recepción e-CF",
    10: "Inicio Prueba Recepción Aprobación Comercial",
    11: "Recepción Aprobación Comercial",
    12: "URL Servicios Producción",
    13: "Declaración Jurada",
    14: "Verificación Estatus",
    15: "Finalizado",
}


def _login_required():
    if "user" not in session:
        flash("Debe iniciar sesión para acceder.", "error")
        return redirect(url_for("web_auth.login"))
    return None


def _get_context():
    uid = session.get("selected_owner_uid", "") or session.get("user", {}).get("ownerUID", "")
    company_id = session.get("selected_company_id", "")
    profile = None
    if company_id:
        profile = DatabaseService.get_company_profile(uid, company_id=company_id)
    return uid, company_id, profile


@web_certificacion_bp.route("/certificacion")
def wizard():
    redirect_resp = _login_required()
    if redirect_resp:
        return redirect_resp

    uid, company_id, profile = _get_context()
    process = DgiiCertService.get_process(company_id) if company_id else {}
    current_step = process.get("current_step", 1)
    steps = process.get("steps", {})

    return redirect(url_for("web_certificacion.step_view", step=current_step))


@web_certificacion_bp.route("/certificacion/paso/<int:step>")
def step_view(step):
    redirect_resp = _login_required()
    if redirect_resp:
        return redirect_resp

    uid, company_id, profile = _get_context()
    if not company_id:
        flash("Seleccione una empresa primero.", "error")
        return redirect(url_for("web_dashboard.dashboard"))

    process = DgiiCertService.get_process(company_id)
    steps = process.get("steps", {})
    current_step = process.get("current_step", 1)

    step_templates = {
        1: "certificacion/step_01_registro.html",
        2: "certificacion/step_02_datos_ecf.html",
        3: "certificacion/step_03_aprobacion.html",
        4: "certificacion/step_04_simulacion.html",
        5: "certificacion/step_05_representacion.html",
        6: "certificacion/step_06_validacion_ri.html",
        7: "certificacion/step_07_urls_prueba.html",
        8: "certificacion/step_08_recepcion.html",
        9: "certificacion/step_09_recepcion_ecf.html",
        10: "certificacion/step_10_recepcion_acecf.html",
        11: "certificacion/step_11_acecf.html",
        12: "certificacion/step_12_urls_produccion.html",
        13: "certificacion/step_13_declaracion.html",
        14: "certificacion/step_14_verificacion.html",
        15: "certificacion/step_15_finalizado.html",
    }

    template = step_templates.get(step, "certificacion/step_01_registro.html")
    step_status = steps.get(str(step), {})

    cert_status = None
    if profile:
        cert_status = DgiiCertService.validate_certificate(profile)

    is_locked = DgiiCertService.is_certification_locked(company_id) if company_id else False

    return render_template(
        template,
        step=step,
        step_label=STEP_LABELS.get(step, f"Paso {step}"),
        step_status=step_status,
        current_step=current_step,
        steps=steps,
        step_labels=STEP_LABELS,
        profile=profile,
        cert_status=cert_status,
        is_locked=is_locked,
        active_page="certificacion",
    )


@web_certificacion_bp.route("/certificacion/paso/<int:step>/avanzar", methods=["POST"])
def step_advance(step):
    redirect_resp = _login_required()
    if redirect_resp:
        return redirect_resp

    _, company_id, _ = _get_context()
    DgiiCertService.set_current_step_manual(company_id, step)
    DgiiCertService.mark_step_skipped(company_id, step)

    next_step = step + 1 if step < 15 else 15
    flash(f"Paso {step} completado.", "success")
    return redirect(url_for("web_certificacion.step_view", step=next_step))


@web_certificacion_bp.route("/certificacion/paso/<int:step>/completar", methods=["POST"])
def step_complete(step):
    redirect_resp = _login_required()
    if redirect_resp:
        return redirect_resp

    _, company_id, _ = _get_context()
    DgiiCertService.mark_step_skipped(company_id, step)

    next_step = step + 1 if step < 15 else 15
    DgiiCertService.set_current_step_manual(company_id, next_step)

    flash(f"Paso {step} — {STEP_LABELS.get(step, '')} completado.", "success")
    return redirect(url_for("web_certificacion.step_view", step=next_step))
