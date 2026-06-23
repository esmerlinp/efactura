import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from app.api.auth import require_api_key
from app.services.db_service import DatabaseService

api_prospects_bp = Blueprint('api_prospects', __name__)

@api_prospects_bp.route('/prospects', methods=['POST'])
@require_api_key
def create_prospect():
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
            "nextContactDate": data.get('fechaProximoContacto') or data.get('next_contact_date') or data.get('nextContactDate') or datetime.now(timezone.utc).isoformat()
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
