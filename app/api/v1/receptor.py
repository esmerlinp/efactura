import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, make_response
from config import Config
from app.services.receptor_auth_service import ReceptorAuthService
from app.services.receptor_xml_service import ReceptorXmlService
from app.services.dgii_signer import DgiiSigner
from app.repositories.receptor_repository import ReceptorRepository
from app.services.db_service import DatabaseService

api_receptor_bp = Blueprint("api_receptor", __name__)

logger = logging.getLogger(__name__)


def _auth_enabled():
    return getattr(Config, "RECEPTOR_AUTH_ENABLED", True)


def _resolve_sandbox(request):
    header = request.headers.get("X-Sandbox")
    if header is None:
        return bool(getattr(Config, "DEFAULT_SANDBOX_MODE", False))
    return header.lower() == "true"


def _normalize_rnc(value):
    return str(value or "").replace("-", "").replace(" ", "").strip()


_PAYLOAD_FILE_FIELDS = ("xml", "file", "archivo", "semilla", "document")


def _read_xml_payload(request):
    """Lee el XML recibido en cualquiera de los formatos soportados:
    multipart (campo 'xml' u otros), form-urlencoded, JSON o cuerpo crudo."""
    for field in _PAYLOAD_FILE_FIELDS:
        f = request.files.get(field)
        if f is not None and f.filename:
            return f.read()
    for field in _PAYLOAD_FILE_FIELDS:
        value = request.form.get(field)
        if value:
            return value.encode("utf-8")
    data = request.get_data(cache=True)
    if data and request.mimetype not in ("multipart/form-data", "application/x-www-form-urlencoded"):
        return data
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        for field in _PAYLOAD_FILE_FIELDS:
            value = payload.get(field)
            if isinstance(value, str) and value:
                return value.encode("utf-8")
    return None


def _authenticate(request, sandbox):
    """Valida el token Bearer emitido por ValidacionCertificado.

    No resuelve la empresa receptora: el dominio es compartido por múltiples
    clientes y la empresa se determina por petición con el RNCComprador del
    e-CF recibido (ver _resolve_receiver).
    """
    if not _auth_enabled():
        return {
            "taxpayer_rnc": "",
            "token_owner_uid": "",
            "header_owner_uid": request.headers.get("X-Owner-UID", ""),
        }, None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Token de autorización no proporcionado."
    token = auth_header[len("Bearer "):].strip()
    stored = ReceptorRepository.get_token_global(token)
    if not stored:
        return None, "Token inválido."
    expires = stored.get("expires_at", "")
    if expires:
        try:
            if datetime.fromisoformat(expires) < datetime.now(timezone.utc):
                return None, "Token expirado."
        except ValueError:
            pass
    return {
        "taxpayer_rnc": stored.get("taxpayer_rnc", ""),
        "token_owner_uid": stored.get("owner_uid", ""),
        "header_owner_uid": request.headers.get("X-Owner-UID", ""),
    }, None


def _resolve_receiver(request, comprador_rnc, token_info):
    """Resuelve la empresa receptora por petición:
    1. RNCComprador del e-CF recibido (dinámico — identifica al cliente).
    2. Si el comprador no coincide con ninguna empresa, se usa un fallback
       (header/token/env) para poder responder ARECF Estado=1 motivo 4.
    3. Sin comprador ni fallback → error."""
    comprador_rnc = _normalize_rnc(comprador_rnc)
    token_info = token_info or {}
    if comprador_rnc:
        owner_uid, profile = ReceptorAuthService.resolve_company_by_rnc(comprador_rnc)
        if owner_uid:
            return owner_uid, profile, None
        logger.warning(
            f"Receptor: RNCComprador {comprador_rnc} no corresponde a ninguna empresa "
            f"registrada; usando fallback para responder ARECF motivo 4."
        )
    owner_uid = (
        token_info.get("header_owner_uid", "")
        or token_info.get("token_owner_uid", "")
        or getattr(Config, "RECEPTOR_DEFAULT_OWNER_UID", "")
    )
    if owner_uid:
        return owner_uid, None, None
    return None, None, (
        f"No se pudo determinar la empresa receptora "
        f"(RNCComprador {comprador_rnc or 'ausente'} y sin contexto)."
    )


# ═══════════════════════════════════════════════════════════════════
# Servicio de Autenticación (URLs registradas ante la DGII)
# ═══════════════════════════════════════════════════════════════════

@api_receptor_bp.route("/fe/autenticacion/api/semilla", methods=["GET"])
def semilla():
    xml_str, seed = ReceptorAuthService.generate_seed_xml()
    response = make_response(xml_str)
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    response.headers["X-Seed-Value"] = seed
    return response


@api_receptor_bp.route("/fe/autenticacion/api/validacioncertificado", methods=["POST"])
@api_receptor_bp.route("/fe/autenticacion/api/ValidacionCertificado", methods=["POST"])
def validacion_certificado():
    xml_payload = _read_xml_payload(request)
    if xml_payload is None:
        logger.error(
            f"ValidacionCertificado: sin payload XML (Content-Type={request.content_type}, "
            f"files={list(request.files.keys())}, form={list(request.form.keys())}, "
            f"data={len(request.get_data(cache=True))} bytes)"
        )
        return jsonify({"success": False, "error": "Campo 'xml' requerido (multipart/form-data, form o cuerpo XML)."}), 400
    expected_seed = request.headers.get("X-Seed-Value", "") or None
    result, error = ReceptorAuthService.validate_signed_seed(xml_payload, expected_seed)
    if error:
        logger.error(
            f"ValidacionCertificado: semilla rechazada (Content-Type={request.content_type}): {error} "
            f"| payload[:300]={xml_payload[:300]!r}"
        )
        ReceptorRepository.save_diagnostic({
            "endpoint": "validacioncertificado",
            "error": error,
            "content_type": request.content_type,
            "payload": xml_payload.decode("utf-8", errors="replace"),
            "received_at": datetime.now(timezone.utc).isoformat(),
        })
        return jsonify({"success": False, "error": error}), 400
    owner_uid = request.headers.get("X-Owner-UID", "")
    sandbox = _resolve_sandbox(request)
    taxpayer_rnc = result.get("subject_sn", "")
    token_data = ReceptorAuthService.issue_token(owner_uid, taxpayer_rnc, sandbox=sandbox)
    ReceptorRepository.save_token(owner_uid, token_data, sandbox=sandbox)
    accept = request.headers.get("Accept", "application/json")
    if "xml" in accept.lower():
        from lxml import etree
        root = etree.Element("RespuestaAutenticacion")
        etree.SubElement(root, "token").text = token_data["token"]
        etree.SubElement(root, "expira").text = token_data["expires_at"]
        etree.SubElement(root, "expedido").text = token_data["issued_at"]
        xml_resp = etree.tostring(root, encoding="utf-8", xml_declaration=True)
        response = make_response(xml_resp)
        response.headers["Content-Type"] = "application/xml; charset=utf-8"
        return response
    return jsonify({
        "token": token_data["token"],
        "expira": token_data["expires_at"],
        "expedido": token_data["issued_at"],
    })


# ═══════════════════════════════════════════════════════════════════
# Servicio de Recepción (URL registrada ante la DGII)
# ═══════════════════════════════════════════════════════════════════

@api_receptor_bp.route("/fe/recepcion/api/ecf", methods=["POST"])
def recepcion_ecf():
    sandbox = _resolve_sandbox(request)
    ctx, error = _authenticate(request, sandbox)
    if error:
        logger.warning(f"Recepcion e-CF: autenticación fallida: {error}")
        return jsonify({"success": False, "error": error}), 401
    xml_payload = _read_xml_payload(request)
    if xml_payload is None:
        logger.error(
            f"Recepcion e-CF: sin payload XML (Content-Type={request.content_type}, "
            f"files={list(request.files.keys())}, form={list(request.form.keys())})"
        )
        return jsonify({"success": False, "error": "Campo 'xml' requerido (multipart/form-data, form o cuerpo XML)."}), 400
    ecf_bytes = xml_payload

    parsed, error = ReceptorXmlService.parse_ecf(ecf_bytes)
    if error:
        return jsonify({"success": False, "error": error}), 400

    owner_uid, company, resolve_error = _resolve_receiver(
        request, parsed.get("rnc_comprador", ""), ctx
    )
    if resolve_error:
        return jsonify({"success": False, "error": resolve_error}), 404
    if not company:
        company = DatabaseService.get_company_profile(owner_uid)
    if not company:
        return jsonify({"success": False, "error": "Perfil de empresa no encontrado."}), 404
    receiver_rnc = _normalize_rnc(company.get("companyRNC"))

    estado, codigo_motivo = "0", None

    sig_ok, sig_error = ReceptorXmlService.verify_signature(ecf_bytes)
    if sig_ok is False:
        if getattr(Config, "RECEPTOR_REQUIRE_SIGNATURE", False):
            estado, codigo_motivo = "1", "2"
        else:
            logger.warning(f"e-CF recibido con firma inválida (aceptado por configuración): {sig_error}")
    elif sig_ok is None:
        logger.info("e-CF recibido sin firma digital (simulación local).")

    if estado == "0":
        comprador_rnc = _normalize_rnc(parsed.get("rnc_comprador", ""))
        if comprador_rnc and receiver_rnc and comprador_rnc != receiver_rnc:
            estado, codigo_motivo = "1", "4"

    if estado == "0":
        encf = parsed.get("encf", "")
        sender_rnc = _normalize_rnc(parsed.get("rnc_emisor", ""))
        if encf and ReceptorRepository.find_received_by_encf(owner_uid, encf, sender_rnc, sandbox=sandbox):
            estado, codigo_motivo = "1", "3"

    arecf_xml_bytes, track_id = ReceptorXmlService.build_arecf(
        receiver_rnc, parsed, estado=estado, codigo_motivo=codigo_motivo
    )
    try:
        signed_arecf = DgiiSigner.sign_xml(arecf_xml_bytes, company)
    except Exception as e:
        logger.warning(f"No se pudo firmar ARECF, usando sin firma: {e}")
        signed_arecf = arecf_xml_bytes

    receiver_name = company.get("companyName", "")
    ecf_document = {
        "sender_rnc": parsed["rnc_emisor"],
        "sender_name": parsed["razon_social_emisor"],
        "receiver_rnc": receiver_rnc,
        "receiver_name": receiver_name,
        "encf": parsed["encf"],
        "ecf_type": parsed["tipo_ecf"],
        "monto_total": parsed["monto_total"],
        "xml_content": ecf_bytes.decode("utf-8", errors="replace"),
        "arecf_xml": signed_arecf.decode("utf-8", errors="replace"),
        "status": "recibido" if estado == "0" else "rechazado",
        "estado_arecf": estado,
        "codigo_motivo_no_recibido": codigo_motivo,
        "track_id": track_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    ReceptorRepository.save_received_ecf(owner_uid, ecf_document, sandbox=sandbox)
    response = make_response(signed_arecf)
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    response.headers["X-Track-Id"] = track_id
    return response


# ═══════════════════════════════════════════════════════════════════
# Aprobación Comercial
# ═══════════════════════════════════════════════════════════════════

@api_receptor_bp.route("/fe/aprobacioncomercial/api/ecf", methods=["POST"])
def aprobacion_comercial():
    sandbox = _resolve_sandbox(request)
    ctx, error = _authenticate(request, sandbox)
    if error:
        logger.warning(f"Aprobación Comercial: autenticación fallida: {error}")
        return jsonify({"success": False, "error": error}), 401
    xml_payload = _read_xml_payload(request)
    if xml_payload is None:
        logger.error(
            f"Aprobación Comercial: sin payload XML (Content-Type={request.content_type}, "
            f"files={list(request.files.keys())}, form={list(request.form.keys())})"
        )
        return jsonify({"success": False, "error": "Campo 'xml' requerido (multipart/form-data, form o cuerpo XML)."}), 400
    approval_bytes = xml_payload
    parsed, error = ReceptorXmlService.parse_approval(approval_bytes)
    if error:
        return jsonify({"success": False, "error": error}), 400
    owner_uid, company, resolve_error = _resolve_receiver(
        request, parsed.get("rnc_comprador", ""), ctx
    )
    if resolve_error:
        return jsonify({"success": False, "error": resolve_error}), 404
    if not company:
        company = DatabaseService.get_company_profile(owner_uid)
    receiver_rnc = _normalize_rnc(company.get("companyRNC")) if company else ""
    receiver_name = company.get("companyName", "") if company else ""
    approval_document = {
        "sender_rnc": parsed.get("rnc_emisor", ""),
        "sender_name": parsed.get("razon_social_emisor", ""),
        "receiver_rnc": receiver_rnc,
        "receiver_name": receiver_name,
        "encf": parsed.get("encf", ""),
        "ecf_type": parsed.get("tipo_ecf", ""),
        "approval_rnc_comprador": parsed.get("rnc_comprador", ""),
        "xml_content": approval_bytes.decode("utf-8", errors="replace"),
        "status": "recibido",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    ReceptorRepository.save_received_approval(owner_uid, approval_document, sandbox=sandbox)
    return jsonify({"success": True, "message": "Aprobación comercial recibida."}), 200


# ═══════════════════════════════════════════════════════════════════
# Dispatcher case-insensitive de las rutas DGII (/fe/...)
# La DGII varía el casing de los segmentos (p. ej. validacionCertificado),
# así que toda variante de mayúsculas/minúsculas resuelve al mismo handler.
# Las rutas explícitas registradas arriba tienen prioridad (match exacto).
# ═══════════════════════════════════════════════════════════════════

@api_receptor_bp.route("/fe/<path:rest>", methods=["GET", "POST"])
@api_receptor_bp.route("/Fe/<path:rest>", methods=["GET", "POST"])
@api_receptor_bp.route("/fE/<path:rest>", methods=["GET", "POST"])
@api_receptor_bp.route("/FE/<path:rest>", methods=["GET", "POST"])
def fe_dispatch(rest):
    lowered = "/fe/" + rest.strip("/").lower()
    if lowered == "/fe/autenticacion/api/semilla" and request.method == "GET":
        return semilla()
    if lowered == "/fe/autenticacion/api/validacioncertificado" and request.method == "POST":
        return validacion_certificado()
    if lowered == "/fe/recepcion/api/ecf" and request.method == "POST":
        return recepcion_ecf()
    if lowered == "/fe/aprobacioncomercial/api/ecf" and request.method == "POST":
        return aprobacion_comercial()
    return jsonify({"success": False, "error": "Ruta no encontrada."}), 404
