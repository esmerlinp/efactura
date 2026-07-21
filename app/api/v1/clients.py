# app/api/v1/clients.py
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from app.api.auth import require_api_key
from app.services.db_service import DatabaseService
from app.utils.cache_utils import http_cache

api_clients_bp = Blueprint('api_clients', __name__)

@api_clients_bp.route('/clients', methods=['GET'])
@require_api_key
@http_cache(timeout=60)
def get_clients():
    """
    GET /api/v1/clients
    Retorna la lista de todos los clientes de la empresa.
    """
    try:
        clients = DatabaseService.get_clients(g.owner_uid, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "clients": clients})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_clients_bp.route('/clients', methods=['POST'])
@require_api_key
def create_client():
    """
    POST /api/v1/clients
    Sincroniza o crea un nuevo cliente en el directorio de la empresa con todos sus campos.
    """
    try:
        data = request.json or {}
        rnc = data.get('rnc')
        razon_social = data.get('razon_social') or data.get('razonSocial')
        
        if not rnc or not razon_social:
            return jsonify({"success": False, "error": "RNC y razon_social son campos requeridos."}), 400
            
        client_id = data.get('id') or str(uuid.uuid4())
        client_dict = {
            "rnc": rnc,
            "razonSocial": razon_social,
            "email": data.get('email', ''),
            "telefono": data.get('telefono', ''),
            "direccion": data.get('direccion', ''),
            "crmNotes": data.get('crm_notes', data.get('crmNotes', 'Creado mediante la API externa')),
            "nextContactDate": data.get('next_contact_date') or data.get('nextContactDate'),
            "customer_category": data.get('customer_category', 'NORMAL')
        }
        
        DatabaseService.save_client(g.owner_uid, client_id, client_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Cliente registrado exitosamente.",
            "client_id": client_id,
            "client": client_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_clients_bp.route('/clients/<client_id>', methods=['PUT'])
@require_api_key
def update_client(client_id):
    """
    PUT /api/v1/clients/<client_id>
    Actualiza la ficha completa de un cliente existente.
    """
    try:
        clients = DatabaseService.get_clients(g.owner_uid, sandbox=g.sandbox_mode)
        client = next((c for c in clients if c['id'] == client_id), None)
        if not client:
            return jsonify({"success": False, "error": "Cliente no encontrado."}), 404
            
        data = request.json or {}
        client_dict = {
            **client,
            "rnc": data.get('rnc', client.get('rnc')),
            "razonSocial": data.get('razon_social', data.get('razonSocial', client.get('razonSocial'))),
            "email": data.get('email', client.get('email')),
            "telefono": data.get('telefono', client.get('telefono')),
            "direccion": data.get('direccion', client.get('direccion')),
            "crmNotes": data.get('crm_notes', data.get('crmNotes', client.get('crmNotes'))),
            "nextContactDate": data.get('next_contact_date', data.get('nextContactDate', client.get('nextContactDate'))),
            "customer_category": data.get('customer_category', client.get('customer_category', 'NORMAL'))
        }
        
        DatabaseService.save_client(g.owner_uid, client_id, client_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Cliente actualizado exitosamente.",
            "client": client_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_clients_bp.route('/clients/<client_id>', methods=['DELETE'])
@require_api_key
def delete_client_route(client_id):
    """
    DELETE /api/v1/clients/<client_id>
    Elimina un cliente de Firestore.
    """
    try:
        DatabaseService.delete_client(g.owner_uid, client_id, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "message": "Cliente eliminado exitosamente."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_clients_bp.route('/clients/<client_id>/statement', methods=['GET'])
@require_api_key
def client_statement(client_id):
    try:
        client = DatabaseService.get_client(g.owner_uid, client_id, sandbox=g.sandbox_mode)
        if not client:
            return jsonify({"success": False, "error": "Cliente no encontrado."}), 404
        invoices = DatabaseService.get_invoices(g.owner_uid, sandbox=g.sandbox_mode, include_all=True)
        client_invoices = [inv for inv in invoices if inv.get("clientId") == client_id]
        open_invoices = [inv for inv in client_invoices
                         if inv.get("status") in ("Emitida", "Vencida", "Parcialmente Cobrada", "Revisión de Pago")]
        total_cxc = sum(float(inv.get("remainingBalance", inv.get("netPayable", 0))) for inv in open_invoices)
        total_facturado = sum(float(inv.get("total", 0)) for inv in client_invoices)
        today = datetime.now().strftime("%Y-%m-%d")
        aging = {"current": 0, "days1_30": 0, "days31_60": 0, "days61_90": 0, "days91_plus": 0}
        for inv in open_invoices:
            due = inv.get("dueDate", "")[:10]
            balance = float(inv.get("remainingBalance", inv.get("netPayable", 0)))
            if not due or due >= today:
                aging["current"] += balance
            else:
                days_overdue = (datetime.now() - datetime.strptime(due, "%Y-%m-%d")).days
                if days_overdue <= 30:
                    aging["days1_30"] += balance
                elif days_overdue <= 60:
                    aging["days31_60"] += balance
                elif days_overdue <= 90:
                    aging["days61_90"] += balance
                else:
                    aging["days91_plus"] += balance
        return jsonify({
            "success": True,
            "clientName": client.get("razonSocial", ""),
            "clientRNC": client.get("rnc", ""),
            "totalCxC": round(total_cxc, 2),
            "totalFacturado": round(total_facturado, 2),
            "invoiceCount": len(client_invoices),
            "openInvoiceCount": len(open_invoices),
            "aging": {k: round(v, 2) for k, v in aging.items()},
            "creditLimit": float(client.get("creditLimit", 0) or 0),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
