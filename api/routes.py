import uuid
from datetime import datetime
from flask import request, jsonify, g
from . import api_bp
from .auth import require_api_key
from firebase_service import DatabaseService
from ecf_emission_service import EcfEmissionService
from dgii_service import DGIIService

@api_bp.route('/invoices/emit', methods=['POST'])
@require_api_key
def emit_invoice():
    """
    POST /api/v1/invoices/emit
    Emite un comprobante fiscal electrónico (e-CF).
    Recibe la información de la factura en JSON.
    """
    try:
        data = request.json or {}
        
        # Validaciones iniciales del Payload
        items = data.get('items', [])
        if not items:
            return jsonify({"success": False, "error": "El documento debe contener al menos un artículo ('items')."}), 400
            
        client_rnc = data.get('client_rnc', '')
        client_name = data.get('client_name', 'Consumidor Final')
        
        ecf_type = data.get('ecf_type', 'Factura de Consumo (E32)')
        payment_method = data.get('payment_method', 'Efectivo')
        due_date = data.get('due_date', datetime.utcnow().strftime("%Y-%m-%d"))
        
        # Cálculo de subtotals y taxes
        subtotal = 0.0
        total_itbis = 0.0
        formatted_items = []
        
        for index, item in enumerate(items):
            price = float(item.get('price', 0.0))
            qty = float(item.get('quantity', 1.0))
            itbis_rate = float(item.get('itbis_rate', 0.18))
            
            line_subtotal = price * qty
            line_itbis = line_subtotal * itbis_rate
            
            subtotal += line_subtotal
            total_itbis += line_itbis
            
            formatted_items.append({
                "itemId": item.get('id', f"api_item_{index}"),
                "name": item.get('name', 'Artículo Genérico'),
                "price": price,
                "quantity": qty,
                "unit": item.get('unit', 'Unidad'),
                "itbisRate": itbis_rate,
                "subtotal": line_subtotal,
                "itbis": line_itbis,
                "total": line_subtotal + line_itbis
            })
            
        discount_rate = float(data.get('discount_rate', 0.0))
        discount_amount = subtotal * discount_rate
        total = (subtotal - discount_amount) + total_itbis
        
        invoice_id = str(uuid.uuid4())
        
        invoice_dict = {
            "id": invoice_id,
            "clientId": data.get('client_id', 'api_client_default'),
            "clientRNC": client_rnc,
            "razonSocial": client_name,
            "ecfType": ecf_type,
            "currency": data.get('currency', 'DOP'),
            "paymentMethod": payment_method,
            "dueDate": due_date,
            "discountRate": discount_rate,
            "subtotal": subtotal,
            "totalITBIS": total_itbis,
            "netPayable": total,
            "total": total,
            "items": formatted_items,
            "status": "Borrador",
            "date": datetime.utcnow().isoformat(),
            "incomeType": data.get('income_type', '01 - Ingresos por operaciones'),
            "isQuotation": False,
            "createdAt": datetime.utcnow().isoformat()
        }
        
        # 1. Guardar localmente / Firebase
        DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)
        
        # 2. Emitir vía Alanube (preparado para ser reemplazado por motor directo DGII)
        # Obtenemos el perfil completo de la compañía
        company = g.company
        
        # Llama a Alanube
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice_dict, sandbox=g.sandbox_mode)
        
        if res.get('success'):
            invoice_dict["status"] = "Emitida"
            invoice_dict["encf"] = res.get("encf", "")
            invoice_dict["trackId"] = res.get("trackId", "")
            invoice_dict["isSyncedWithDGII"] = True
            
            # Guardamos con el estado final actualizado
            DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)
            
            return jsonify({
                "success": True,
                "message": "Factura Electrónica e-CF emitida exitosamente.",
                "invoice_id": invoice_id,
                "encf": res.get("encf"),
                "track_id": res.get("trackId"),
                "total": total
            })
        else:
            invoice_dict["status"] = "Rechazada"
            invoice_dict["errorDetail"] = res.get("error", "Error desconocido de emisión")
            DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)
            
            return jsonify({
                "success": False,
                "error": "Error al procesar el e-CF con el proveedor de facturación.",
                "details": res.get("error")
            }), 422
            
    except Exception as e:
        return jsonify({"success": False, "error": f"Fallo interno del servidor: {str(e)}"}), 500


@api_bp.route('/invoices/<invoice_id>/status', methods=['GET'])
@require_api_key
def get_invoice_status(invoice_id):
    """
    GET /api/v1/invoices/<invoice_id>/status
    Consulta el estado de sincronización y validación de una factura electrónica específica.
    """
    try:
        invoices = DatabaseService.get_invoices(g.owner_uid, sandbox=g.sandbox_mode)
        invoice = next((inv for inv in invoices if inv['id'] == invoice_id), None)
        
        if not invoice:
            return jsonify({"success": False, "error": "Factura no encontrada."}), 404
            
        return jsonify({
            "success": True,
            "invoice_id": invoice_id,
            "status": invoice.get("status"),
            "encf": invoice.get("encf"),
            "track_id": invoice.get("trackId"),
            "is_synced_dgii": invoice.get("isSyncedWithDGII", False),
            "error_detail": invoice.get("errorDetail")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/invoices/<invoice_id>/cancel', methods=['POST'])
@require_api_key
def cancel_invoice(invoice_id):
    """
    POST /api/v1/invoices/<invoice_id>/cancel
    Anula un e-CF emitido.
    """
    try:
        invoices = DatabaseService.get_invoices(g.owner_uid, sandbox=g.sandbox_mode)
        invoice = next((inv for inv in invoices if inv['id'] == invoice_id), None)
        
        if not invoice:
            return jsonify({"success": False, "error": "Factura no encontrada."}), 404
            
        data = request.json or {}
        reason = data.get('reason', 'Anulación solicitada por la API')
        
        # Estructurar solicitud de anulación similar a la lógica en app.py
        canc_dict = {
            "encf": invoice.get("encf"),
            "reason": reason,
            "date": datetime.utcnow().strftime("%Y-%m-%d")
        }
        
        res = EcfEmissionService.emit_cancellation(g.company, canc_dict, sandbox=g.sandbox_mode)
        
        if res.get('success'):
            invoice["status"] = "Anulada"
            DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice, sandbox=g.sandbox_mode)
            return jsonify({
                "success": True,
                "message": "Factura anulada con éxito.",
                "invoice_id": invoice_id,
                "encf": invoice.get("encf")
            })
        else:
            return jsonify({
                "success": False,
                "error": "No se pudo anular la factura.",
                "details": res.get("error")
            }), 422
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/dgii/rnc/<rnc>', methods=['GET'])
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


@api_bp.route('/clients', methods=['POST'])
@require_api_key
def create_client():
    """
    POST /api/v1/clients
    Sincroniza o crea un nuevo cliente en el directorio de la empresa.
    """
    try:
        data = request.json or {}
        rnc = data.get('rnc')
        razon_social = data.get('razon_social')
        
        if not rnc or not razon_social:
            return jsonify({"success": False, "error": "RNC y razon_social son campos requeridos."}), 400
            
        client_id = str(uuid.uuid4())
        client_dict = {
            "rnc": rnc,
            "razonSocial": razon_social,
            "email": data.get('email', ''),
            "telefono": data.get('telefono', ''),
            "direccion": data.get('direccion', ''),
            "crmNotes": "Creado mediante la API externa",
            "nextContactDate": None
        }
        
        DatabaseService.save_client(g.owner_uid, client_id, client_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Cliente registrado exitosamente.",
            "client_id": client_id,
            "rnc": rnc
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
