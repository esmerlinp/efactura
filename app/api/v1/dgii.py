# app/api/v1/dgii.py
from flask import Blueprint, jsonify
from app.api.auth import require_api_key
from app.services.dgii import DGIIService

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
