# app/api/v1/dgii.py
from flask import Blueprint, jsonify, g
from app.api.auth import require_api_key
from app.services.dgii import DGIIService
from app.services.db_service import DatabaseService

api_dgii_bp = Blueprint('api_dgii', __name__)

@api_dgii_bp.route('/dgii/rnc/<rnc>', methods=['GET'])
@require_api_key
def lookup_rnc(rnc):
    """
    GET /api/v1/dgii/rnc/<rnc>
    Consulta la información fiscal de un RNC o Cédula directamente con la DGII.
    """
    try:
        res = DGIIService.validate_and_fetch_rnc(rnc)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_dgii_bp.route('/dgii/sequences', methods=['GET'])
@require_api_key
def get_sequences():
    """
    GET /api/v1/dgii/sequences
    Consulta las secuencias (rangos) de comprobantes fiscales autorizadas.
    """
    try:
        sequences = DatabaseService.get_sequences(g.owner_uid, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "sequences": sequences})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_dgii_bp.route('/dgii/audit', methods=['GET'])
@require_api_key
def get_sequence_audit():
    """
    GET /api/v1/dgii/audit
    Consulta los logs de auditoría de secuencias usadas y su estado en DGII.
    """
    try:
        logs = DatabaseService.get_sequence_logs(g.owner_uid, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "audit_logs": logs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
