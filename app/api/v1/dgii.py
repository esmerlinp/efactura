# app/api/v1/dgii.py
from flask import Blueprint, jsonify, g, session
from app.api.auth import require_api_key
from app.services.dgii import DGIIService
from app.services.db_service import DatabaseService
from app.utils.cache_utils import http_cache

api_dgii_bp = Blueprint('api_dgii', __name__)


@api_dgii_bp.before_request
def restrict_to_do():
    if session.get('company_country', 'DO') != 'DO':
        return jsonify({"error": "Este endpoint solo está disponible para contribuyentes de República Dominicana"}), 404

@api_dgii_bp.route('/dgii/rnc/<rnc>', methods=['GET'])
@require_api_key
def lookup_rnc(rnc):
    """
    Consultar RNC/Cédula en DGII
    ---
    tags:
      - DGII
    summary: Consultar información fiscal de un RNC
    description: Consulta los datos fiscales de un RNC o Cédula directamente en la DGII. Solo disponible para contribuyentes dominicanos.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: rnc
        in: path
        required: true
        type: string
        description: Número de RNC o cédula
        example: "130000000"
    responses:
      200:
        description: Datos fiscales del RNC
      500:
        description: Error interno del servidor
    """
    try:
        res = DGIIService.validate_and_fetch_rnc(rnc)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_dgii_bp.route('/dgii/sequences', methods=['GET'])
@require_api_key
@http_cache(timeout=300)
def get_sequences():
    """
    Listar secuencias fiscales autorizadas
    ---
    tags:
      - DGII
    summary: Consultar secuencias autorizadas
    description: Retorna los rangos de secuencias de comprobantes fiscales electrónicos autorizados por la DGII.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Lista de secuencias
        schema:
          type: object
          properties:
            success:
              type: boolean
            sequences:
              type: array
              items:
                type: object
      500:
        description: Error interno del servidor
    """
    try:
        sequences = DatabaseService.get_sequences(g.owner_uid, company_id=g.company_id, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "sequences": sequences})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_dgii_bp.route('/dgii/audit', methods=['GET'])
@require_api_key
@http_cache(timeout=60)
def get_sequence_audit():
    """
    Consultar logs de auditoría de secuencias
    ---
    tags:
      - DGII
    summary: Consultar auditoría de secuencias
    description: Retorna los logs de uso de secuencias fiscales y su estado de sincronización con la DGII.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Logs de auditoría
        schema:
          type: object
          properties:
            success:
              type: boolean
            audit_logs:
              type: array
              items:
                type: object
      500:
        description: Error interno del servidor
    """
    try:
        logs = DatabaseService.get_sequence_logs(g.owner_uid, company_id=g.company_id, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "audit_logs": logs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
