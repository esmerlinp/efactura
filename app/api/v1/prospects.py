import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from app.api.auth import require_api_key
from app.services.db_service import DatabaseService

api_prospects_bp = Blueprint('api_prospects', __name__)

@api_prospects_bp.route('/prospects', methods=['POST'])
@require_api_key
def create_prospect():
    """
    Crear prospecto (CRM)
    ---
    tags:
      - Prospects
    summary: Registrar un nuevo prospecto
    description: Crea un prospecto en el CRM (se guarda como cliente con pipelineStage="Prospecto").
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - rnc
            - razon_social
          properties:
            rnc:
              type: string
              description: RNC o cédula
            razon_social:
              type: string
              description: Nombre o razón social (también acepta 'nombre')
            email:
              type: string
            telefono:
              type: string
            direccion:
              type: string
            notas:
              type: string
              description: Notas CRM (también acepta 'crm_notes')
            next_contact_date:
              type: string
              format: date
            customer_category:
              type: string
              default: "NORMAL"
    responses:
      200:
        description: Prospecto creado exitosamente
      400:
        description: Faltan campos requeridos
      500:
        description: Error interno del servidor
    """
    try:
        data = request.json or {}
        rnc = data.get('rnc')
        razon_social = data.get('razon_social') or data.get('razonSocial') or data.get('nombre')

        if not rnc or not razon_social:
            return jsonify({"success": False, "error": "rnc y razonSocial (o nombre) son campos requeridos."}), 400

        prospect_id = data.get('id') or str(uuid.uuid4())
        prospect_dict = {
            "rnc": rnc,
            "razonSocial": razon_social,
            "email": data.get('email', ''),
            "telefono": data.get('telefono', ''),
            "direccion": data.get('direccion', ''),
            "crmNotes": data.get('notas') or data.get('crm_notes') or data.get('crmNotes', 'Creado desde n8n'),
            "pipelineStage": "Prospecto",
            "nextContactDate": data.get('fechaProximoContacto') or data.get('next_contact_date') or data.get('nextContactDate') or datetime.now(timezone.utc).isoformat(),
            "customer_category": data.get('customer_category', 'NORMAL')
        }

        DatabaseService.save_client(g.owner_uid, prospect_id, prospect_dict, sandbox=g.sandbox_mode)

        return jsonify({
            "success": True,
            "message": "Prospecto creado exitosamente.",
            "prospect_id": prospect_id,
            "prospect": prospect_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
