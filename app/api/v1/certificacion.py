import base64
import json
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO

from flask import Blueprint, request, jsonify, send_file, session

from app.services.dgii_cert_service import DgiiCertService
from app.services.db_service import DatabaseService
from app.services.dgii_signer import DgiiSigner
from app.services.ecf_readiness_service import EcfReadinessService

api_certificacion_bp = Blueprint("api_certificacion", __name__)

UPLOAD_DIR = "uploads/certificacion"


def _get_owner_and_company():
    uid = session.get("selected_owner_uid", "") or session.get("user", {}).get("ownerUID", "")
    company_id = session.get("selected_company_id", "")
    sandbox = session.get("is_sandbox_mode", True)
    return uid, company_id, sandbox


def _get_company_profile():
    uid, company_id, sandbox = _get_owner_and_company()
    if not company_id:
        return None
    return DatabaseService.get_company_profile(uid, company_id=company_id)


def _login_required():
    if "user" not in session:
        return jsonify({"error": "No autorizado"}), 401
    return None


# ═══════════════════════════════════════════════════════════════
# Certificado Digital
# ═══════════════════════════════════════════════════════════════

@api_certificacion_bp.route("/certificacion/certificate", methods=["POST"])
def upload_certificate():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    uid, company_id, sandbox = _get_owner_and_company()
    cert_file = request.files.get("certificateFile")
    cert_password = request.form.get("certificatePassword", "").strip()

    if not cert_file or not cert_file.filename:
        return jsonify({"error": "Archivo de certificado requerido"}), 400
    if not cert_password:
        return jsonify({"error": "Contraseña del certificado requerida"}), 400

    filename = cert_file.filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "p12"
    if ext not in ("p12", "pfx"):
        return jsonify({"error": "Formato no válido. Use .p12 o .pfx"}), 400

    file_data = cert_file.read()
    cert_content_b64 = base64.b64encode(file_data).decode("utf-8")
    cert_name = filename.rsplit(".", 1)[0]

    valid, detail = EcfReadinessService._validate_certificate(cert_content_b64, cert_password)
    if not valid:
        return jsonify({"error": detail.get("message", "Certificado no válido")}), 400

    existing = DatabaseService.get_company_profile(uid, company_id=company_id) or {}
    existing["certificateName"] = cert_name
    existing["certificateExtension"] = f".{ext}"
    existing["certificateContent"] = cert_content_b64
    existing["certificatePassword"] = cert_password

    DatabaseService.save_company_profile(uid, existing, company_id=company_id)

    return jsonify({
        "success": True,
        "name": cert_name,
        "extension": f".{ext}",
        "not_after": detail.get("notAfter") if isinstance(detail, dict) else None,
    })


@api_certificacion_bp.route("/certificacion/certificate/status", methods=["GET"])
def certificate_status():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    profile = _get_company_profile()
    if not profile:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    result = DgiiCertService.validate_certificate(profile)
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════
# Progreso del proceso
# ═══════════════════════════════════════════════════════════════

@api_certificacion_bp.route("/certificacion/progress", methods=["GET"])
def get_progress():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    status = DgiiCertService.get_step_status(company_id)
    return jsonify(status)


@api_certificacion_bp.route("/certificacion/progress", methods=["POST"])
def save_progress():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    data = request.get_json() or {}
    step_num = data.get("step")
    if step_num:
        DgiiCertService.set_current_step_manual(company_id, int(step_num))
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════
# Paso 1: Postulacion
# ═══════════════════════════════════════════════════════════════

@api_certificacion_bp.route("/certificacion/step-1/sign-postulacion", methods=["POST"])
def sign_postulacion():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    profile = _get_company_profile()
    if not profile:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404
    if not profile.get("certificateContent"):
        return jsonify({"error": "Debe cargar un certificado digital primero"}), 400

    xml_file = request.files.get("xmlFile")
    if not xml_file:
        return jsonify({"error": "Debe subir el XML de postulacion"}), 400

    raw_xml = xml_file.read()
    try:
        signed_xml, filename = DgiiCertService.sign_postulacion_xml(profile, raw_xml)
        return send_file(
            BytesIO(signed_xml),
            mimetype="application/xml",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        return jsonify({"error": f"Error al firmar: {str(e)}"}), 500


# ═══════════════════════════════════════════════════════════════
# Paso 2: Pruebas de Datos e-CF
# ═══════════════════════════════════════════════════════════════

@api_certificacion_bp.route("/certificacion/step-2/upload-excel", methods=["POST"])
def step2_upload_excel():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    excel_file = request.files.get("excelFile")
    if not excel_file:
        return jsonify({"error": "Debe subir el archivo Excel del DGII"}), 400

    _, company_id, _ = _get_owner_and_company()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    excel_path = os.path.join(UPLOAD_DIR, f"{company_id}_step2_test_data.xlsx")
    excel_file.save(excel_path)

    try:
        parsed = DgiiCertService.parse_step2_excel(excel_path)
        return jsonify({"success": True, **parsed})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@api_certificacion_bp.route("/certificacion/step-2/generate", methods=["POST"])
def step2_generate():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()

    if DgiiCertService.is_certification_locked(company_id):
        return jsonify({"error": "La certificación ya ha sido completada. El ambiente CerteCF está bloqueado."}), 403
    profile = _get_company_profile()
    if not profile:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    data = request.get_json() or {}
    parsed_data = data.get("parsed_data")
    selected_groups = data.get("groups")
    dry_run = data.get("dry_run", False)
    resume_run = data.get("resume_run", False)
    force_rerun = data.get("force_rerun", False)

    if not parsed_data:
        return jsonify({"error": "Debe subir el Excel primero"}), 400

    run_number = None

    if resume_run:
        status = DgiiCertService.get_step_status(company_id)
        steps = status.get("steps", {})
        step_2 = steps.get("2", {})
        run_number = step_2.get("current_run")
        if not run_number:
            resume_run = False

    if not resume_run:
        _, step_data = DgiiCertService.init_step(company_id, 2)
        run_number = step_data["current_run"]

    try:
        result = DgiiCertService.process_step2_generate(
            company_id=company_id,
            company_profile=profile,
            parsed_data=parsed_data,
            selected_groups=selected_groups,
            dry_run=dry_run,
            run_number=run_number,
            resume_run=resume_run,
            force_rerun=force_rerun,
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        run_dict = {"run_number": run_number, "status": "failed", "error_summary": str(e)}
        DgiiCertService.fail_step(company_id, 2, run_number, run_dict)
        return jsonify({"success": False, "error": str(e)}), 500



@api_certificacion_bp.route("/certificacion/step-2/force-dgii-reset", methods=["POST"])
def step2_force_dgii_reset():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    profile = _get_company_profile()
    if not profile:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    data = request.get_json() or {}
    parsed_data = data.get("parsed_data")
    group = data.get("group")
    count = int(data.get("count", 1))

    if not parsed_data:
        return jsonify({"error": "Debe subir el Excel primero"}), 400

    from app.services.dgii_cert_service import DgiiCertService
    result = DgiiCertService.force_dgii_reset(company_id, profile, parsed_data, group, count)
    return jsonify(result)

@api_certificacion_bp.route("/certificacion/step-2/reset", methods=["POST"])
def step2_reset():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    DgiiCertService.init_step(company_id, 2)
    return jsonify({"success": True})


@api_certificacion_bp.route("/certificacion/step-2/check-status/<track_id>", methods=["GET"])
def step2_check_status(track_id):
    auth_err = _login_required()
    if auth_err:
        return auth_err

    profile = _get_company_profile()
    if not profile:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    result = DgiiCertService.check_case_status(profile, track_id)
    return jsonify(result)


@api_certificacion_bp.route("/certificacion/step-2/download/<path:encf>", methods=["GET"])
def step2_download_xml(encf):
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    process = DgiiCertService.get_process(company_id)
    step_data = process.get("steps", {}).get("2", {})

    run_number = request.args.get("run", step_data.get("current_run", 0))
    if not run_number:
        return jsonify({"error": "No hay ejecuciones previas"}), 404

    evidence_dir = _get_evidence_dir_path(company_id, 2, run_number)
    xml_dir = os.path.join(evidence_dir, "xml")

    signed_path = os.path.join(xml_dir, f"{encf}_signed.xml")
    manual_path = os.path.join(xml_dir, f"{encf}_manual_signed.xml")

    download_path = None
    if os.path.exists(manual_path):
        download_path = manual_path
    elif os.path.exists(signed_path):
        download_path = signed_path

    if not download_path:
        return jsonify({"error": f"XML no encontrado para {encf}"}), 404

    return send_file(
        os.path.abspath(download_path),
        mimetype="application/xml",
        as_attachment=True,
        download_name=os.path.basename(download_path),
    )


@api_certificacion_bp.route("/certificacion/step-2/download-all", methods=["GET"])
def step2_download_all():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    process = DgiiCertService.get_process(company_id)
    step_data = process.get("steps", {}).get("2", {})

    run_number = request.args.get("run", step_data.get("current_run", 0))
    if not run_number:
        return jsonify({"error": "No hay ejecuciones previas"}), 404

    zip_data = DgiiCertService.download_all_evidence_zip(company_id, 2, run_number)
    if not zip_data:
        return jsonify({"error": "No se encontraron evidencias"}), 404

    return send_file(
        BytesIO(zip_data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"evidencias_paso2_run{run_number}.zip",
    )


@api_certificacion_bp.route("/certificacion/step-2/mark-manual-uploaded/<encf>", methods=["POST"])
def step2_mark_manual(encf):
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    process = DgiiCertService.get_process(company_id)
    step_data = process.get("steps", {}).get("2", {})
    run_number = request.args.get("run", step_data.get("current_run", 0))

    if not run_number:
        return jsonify({"error": "No hay ejecuciones previas"}), 404

    result = DgiiCertService.mark_manual_uploaded(company_id, 2, run_number, encf)
    return jsonify(result)


def _get_evidence_dir_path(company_id, step, run_number):
    return f"uploads/certificacion/{company_id}/step{step}/run{run_number}"


# ═══════════════════════════════════════════════════════════════
# Paso 3: Pruebas de Datos Aprobacion Comercial
# ═══════════════════════════════════════════════════════════════

@api_certificacion_bp.route("/certificacion/step-3/upload-excel", methods=["POST"])
def step3_upload_excel():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    excel_file = request.files.get("excelFile")
    if not excel_file:
        return jsonify({"error": "Debe subir el archivo Excel de Aprobaciones"}), 400

    _, company_id, _ = _get_owner_and_company()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    excel_path = os.path.join(UPLOAD_DIR, f"{company_id}_step3_acecf.xlsx")
    excel_file.save(excel_path)

    try:
        parsed = DgiiCertService.parse_step3_excel(excel_path)
        return jsonify({"success": True, **parsed})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@api_certificacion_bp.route("/certificacion/step-3/generate", methods=["POST"])
def step3_generate():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()

    if DgiiCertService.is_certification_locked(company_id):
        return jsonify({"error": "La certificación ya ha sido completada. El ambiente CerteCF está bloqueado."}), 403

    profile = _get_company_profile()
    if not profile:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    data = request.get_json() or {}
    parsed_data = data.get("parsed_data")
    dry_run = data.get("dry_run", False)

    if not parsed_data:
        return jsonify({"error": "Debe subir el Excel primero"}), 400

    _, step_data = DgiiCertService.init_step(company_id, 3)
    run_number = step_data["current_run"]

    try:
        result = DgiiCertService.process_step3_generate(
            company_id=company_id,
            company_profile=profile,
            parsed_data=parsed_data,
            dry_run=dry_run,
            run_number=run_number,
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        run_dict = {"run_number": run_number, "status": "failed", "error_summary": str(e)}
        DgiiCertService.fail_step(company_id, 3, run_number, run_dict)
        return jsonify({"success": False, "error": str(e)}), 500


@api_certificacion_bp.route("/certificacion/step-3/download/<encf>", methods=["GET"])
def step3_download_xml(encf):
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    process = DgiiCertService.get_process(company_id)
    step_data = process.get("steps", {}).get("3", {})
    run_number = request.args.get("run", step_data.get("current_run", 0))

    if not run_number:
        return jsonify({"error": "No hay ejecuciones previas"}), 404

    evidence_dir = _get_evidence_dir_path(company_id, 3, run_number)
    xml_dir = os.path.join(evidence_dir, "xml")
    signed_path = os.path.join(xml_dir, f"ACECF_{encf}_signed.xml")

    if not os.path.exists(signed_path):
        return jsonify({"error": f"XML no encontrado para {encf}"}), 404

    return send_file(
        os.path.abspath(signed_path),
        mimetype="application/xml",
        as_attachment=True,
        download_name=f"ACECF_{encf}.xml",
    )


@api_certificacion_bp.route("/certificacion/step-3/download-all", methods=["GET"])
def step3_download_all():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    process = DgiiCertService.get_process(company_id)
    step_data = process.get("steps", {}).get("3", {})
    run_number = request.args.get("run", step_data.get("current_run", 0))

    if not run_number:
        return jsonify({"error": "No hay ejecuciones previas"}), 404

    zip_data = DgiiCertService.download_all_evidence_zip(company_id, 3, run_number)
    if not zip_data:
        return jsonify({"error": "No se encontraron evidencias"}), 404

    return send_file(
        BytesIO(zip_data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"evidencias_paso3_run{run_number}.zip",
    )


# ═══════════════════════════════════════════════════════════════
# Paso 13: Declaracion Jurada
# ═══════════════════════════════════════════════════════════════

@api_certificacion_bp.route("/certificacion/step-13/generate-declaracion", methods=["POST"])
def step13_generate():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    profile = _get_company_profile()
    if not profile:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404
    if not profile.get("certificateContent"):
        return jsonify({"error": "Debe cargar un certificado digital primero"}), 400

    data = request.get_json() or {}
    rnc = profile.get("companyRNC", "").replace("-", "")
    razon_social = profile.get("companyName", "")

    declaracion_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<DeclaracionJurada xmlns="http://www.dgii.gov.do/">\n'
        f"  <RNC>{rnc}</RNC>\n"
        f"  <RazonSocial>{razon_social}</RazonSocial>\n"
        f"  <Fecha>{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')}</Fecha>\n"
        f"  <NombreRepresentante>{data.get('nombre_representante', '')}</NombreRepresentante>\n"
        f"  <CedulaRepresentante>{data.get('cedula_representante', '')}</CedulaRepresentante>\n"
        '  <Declaracion>Certifico que el proceso de certificacion como Emisor Electronico</Declaracion>\n'
        '  <Declaracion>se ha realizado de manera integra y sin irregularidades,</Declaracion>\n'
        '  <Declaracion>cumpliendo con la Ley 32-23, Decreto 587-24 y Norma General 01-2020.</Declaracion>\n'
        '</DeclaracionJurada>'
    ).encode("utf-8")

    try:
        signed_xml, filename = DgiiCertService.sign_postulacion_xml(profile, declaracion_xml)
        filename = f"{rnc}_declaracion_jurada_firmada.xml" if rnc else "declaracion_jurada_firmada.xml"
        return send_file(
            BytesIO(signed_xml),
            mimetype="application/xml",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        return jsonify({"error": f"Error al firmar: {str(e)}"}), 500


# ═══════════════════════════════════════════════════════════════
# Paso 4: Pruebas de Simulación e-CF (emisión real)
# ═══════════════════════════════════════════════════════════════

@api_certificacion_bp.route("/certificacion/step-4/invoices", methods=["GET"])
def step4_list_invoices():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    uid, company_id, sandbox = _get_owner_and_company()
    if not company_id:
        return jsonify({"error": "Seleccione una empresa"}), 400

    invoices = DgiiCertService.get_available_invoices(
        uid, company_id, sandbox=sandbox, limit=100
    )
    return jsonify({"invoices": invoices})


@api_certificacion_bp.route("/certificacion/step-4/generate", methods=["POST"])
def step4_generate():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    uid, company_id, sandbox = _get_owner_and_company()

    if DgiiCertService.is_certification_locked(company_id):
        return jsonify({"error": "La certificación ya ha sido completada."}), 403

    profile = _get_company_profile()
    if not profile:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    data = request.get_json() or {}
    invoice_ids = data.get("invoice_ids", [])
    if not invoice_ids:
        return jsonify({"error": "Seleccione al menos una factura"}), 400

    _, step_data = DgiiCertService.init_step(company_id, 4)
    run_number = step_data["current_run"]

    try:
        result = DgiiCertService.process_step4(
            company_id=company_id,
            company_profile=profile,
            invoice_ids=invoice_ids,
            owner_uid=uid,
            sandbox_origin=sandbox,
            run_number=run_number,
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        run_dict = {"run_number": run_number, "status": "failed", "error_summary": str(e)}
        DgiiCertService.fail_step(company_id, 4, run_number, run_dict)
        return jsonify({"success": False, "error": str(e)}), 500


@api_certificacion_bp.route("/certificacion/step-4/download-all", methods=["GET"])
def step4_download_all():
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    process = DgiiCertService.get_process(company_id)
    step_data = process.get("steps", {}).get("4", {})
    run_number = request.args.get("run", step_data.get("current_run", 0))

    if not run_number:
        return jsonify({"error": "No hay ejecuciones previas"}), 404

    zip_data = DgiiCertService.download_all_evidence_zip(company_id, 4, run_number)
    if not zip_data:
        return jsonify({"error": "No se encontraron evidencias"}), 404

    return send_file(
        BytesIO(zip_data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"evidencias_paso4_run{run_number}.zip",
    )


@api_certificacion_bp.route("/certificacion/step-4/download/<encf>", methods=["GET"])
def step4_download_xml(encf):
    auth_err = _login_required()
    if auth_err:
        return auth_err

    _, company_id, _ = _get_owner_and_company()
    process = DgiiCertService.get_process(company_id)
    step_data = process.get("steps", {}).get("4", {})
    run_number = request.args.get("run", step_data.get("current_run", 0))

    if not run_number:
        return jsonify({"error": "No hay ejecuciones previas"}), 404

    evidence_dir = f"uploads/certificacion/{company_id}/step4/run{run_number}"
    xml_dir = os.path.join(evidence_dir, "xml")
    signed_path = os.path.join(xml_dir, f"{encf}_signed.xml")

    if not os.path.exists(signed_path):
        return jsonify({"error": f"XML no encontrado para {encf}"}), 404

    return send_file(
        os.path.abspath(signed_path),
        mimetype="application/xml",
        as_attachment=True,
        download_name=f"{encf}_signed.xml",
    )
