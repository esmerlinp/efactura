import logging
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


def _get_owner_uid_from_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Token de autorización no proporcionado."
    token = auth_header[len("Bearer "):].strip()
    owner_uid = request.headers.get("X-Owner-UID", "")
    sandbox = request.headers.get("X-Sandbox", "true").lower() == "true"
    if not owner_uid:
        return None, "Header X-Owner-UID requerido."
    stored = ReceptorRepository.get_token(owner_uid, token, sandbox=sandbox)
    if not stored:
        return None, "Token inválido."
    from datetime import datetime, timezone
    expires = stored.get("expires_at", "")
    if expires and datetime.fromisoformat(expires) < datetime.now(timezone.utc):
        return None, "Token expirado."
    return owner_uid, None


def _resolve_sandbox(request):
    return request.headers.get("X-Sandbox", "true").lower() == "true"


@api_receptor_bp.route("/fe/autenticacion/api/semilla", methods=["GET"])
def semilla():
    xml_str, seed = ReceptorAuthService.generate_seed_xml()
    response = make_response(xml_str)
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    response.headers["X-Seed-Value"] = seed
    return response


@api_receptor_bp.route("/fe/autenticacion/api/validacioncertificado", methods=["POST"])
def validacion_certificado():
    if "xml" not in request.files:
        return jsonify({"success": False, "error": "Campo 'xml' requerido (multipart/form-data)."}), 400
    xml_file = request.files["xml"]
    signed_seed_bytes = xml_file.read()
    expected_seed = request.headers.get("X-Seed-Value", "")
    if not expected_seed:
        return jsonify({"success": False, "error": "Header X-Seed-Value requerido."}), 400
    result, error = ReceptorAuthService.validate_signed_seed(signed_seed_bytes, expected_seed)
    if error:
        return jsonify({"success": False, "error": error}), 400
    owner_uid = request.headers.get("X-Owner-UID", "")
    sandbox = _resolve_sandbox(request)
    taxpayer_rnc = result.get("subject_sn", "")
    token_data = ReceptorAuthService.issue_token(owner_uid, taxpayer_rnc, sandbox=sandbox)
    ReceptorRepository.save_token(owner_uid, token_data, sandbox=sandbox)
    accept = request.headers.get("Accept", "application/json")
    if "xml" in accept.lower():
        from lxml import etree
        root = etree.Element("respuestaautenticacion")
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


@api_receptor_bp.route("/fe/recepcion/api/ecf", methods=["POST"])
def recepcion_ecf():
    if _auth_enabled():
        owner_uid, error = _get_owner_uid_from_token(request)
        if error:
            return jsonify({"success": False, "error": error}), 401
    else:
        owner_uid = request.headers.get("X-Owner-UID", "")
        if not owner_uid:
            return jsonify({"success": False, "error": "Header X-Owner-UID requerido."}), 400
    sandbox = _resolve_sandbox(request)
    if "xml" not in request.files:
        return jsonify({"success": False, "error": "Campo 'xml' requerido (multipart/form-data)."}), 400
    xml_file = request.files["xml"]
    ecf_bytes = xml_file.read()
    parsed, error = ReceptorXmlService.parse_ecf(ecf_bytes)
    if error:
        return jsonify({"success": False, "error": error}), 400
    company = DatabaseService.get_company_profile(owner_uid)
    if not company:
        return jsonify({"success": False, "error": "Perfil de empresa no encontrado."}), 404
    receiver_rnc = company.get("companyRNC", "").replace("-", "").strip()
    arecf_xml_bytes, track_id = ReceptorXmlService.build_arecf(receiver_rnc, parsed)
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
        "status": "recibido",
        "track_id": track_id,
    }
    ReceptorRepository.save_received_ecf(owner_uid, ecf_document, sandbox=sandbox)
    response = make_response(signed_arecf)
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    response.headers["X-Track-Id"] = track_id
    return response


@api_receptor_bp.route("/fe/aprobacioncomercial/api/ecf", methods=["POST"])
def aprobacion_comercial():
    if _auth_enabled():
        owner_uid, error = _get_owner_uid_from_token(request)
        if error:
            return jsonify({"success": False, "error": error}), 401
    else:
        owner_uid = request.headers.get("X-Owner-UID", "")
        if not owner_uid:
            return jsonify({"success": False, "error": "Header X-Owner-UID requerido."}), 400
    sandbox = _resolve_sandbox(request)
    if "xml" not in request.files:
        return jsonify({"success": False, "error": "Campo 'xml' requerido (multipart/form-data)."}), 400
    xml_file = request.files["xml"]
    approval_bytes = xml_file.read()
    parsed, error = ReceptorXmlService.parse_approval(approval_bytes)
    if error:
        return jsonify({"success": False, "error": error}), 400
    company = DatabaseService.get_company_profile(owner_uid)
    receiver_rnc = company.get("companyRNC", "").replace("-", "").strip() if company else ""
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
    }
    ReceptorRepository.save_received_approval(owner_uid, approval_document, sandbox=sandbox)
    return jsonify({"success": True, "message": "Aprobación comercial recibida."}), 200
