# app/api/v1/invoices.py
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, request, g, jsonify
from app.api.auth import require_api_key
from app.services.db_service import DatabaseService
from app.services.ecf_emission import EcfEmissionService
from app.services.dgii import DGIIService
from app.services.alanube import AlanubeService

api_invoices_bp = Blueprint('api_invoices', __name__)

@api_invoices_bp.route('/invoices/emit', methods=['POST'])
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
        
        # Consumir el siguiente consecutivo del rango fiscal DGII si no se ha asignado y no es cotización
        if not invoice_dict.get("encf"):
            ecf_short = AlanubeService.get_ecf_type_short_code(invoice_dict["ecfType"])
            user_email = g.company.get("companyEmail", "api@efactura.com.do")
            
            # Bloquear secuencia y generar consecutivo transaccionalmente en Firestore
            encf, log_id = DatabaseService.consume_next_sequence(g.owner_uid, ecf_short, user_email, sandbox=g.sandbox_mode)
            invoice_dict["encf"] = encf

        # 1. Guardar localmente / Firebase
        DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)
        
        # 2. Emitir vía Alanube / DGII Direct
        company = g.company
        
        # Llama al motor de emisión unificado
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice_dict, sandbox=g.sandbox_mode)
        
        if res.get('success'):
            invoice_dict["status"] = "Pendiente DGII" if res.get("status") == "PENDING" else "Emitida"
            invoice_dict["encf"] = res.get("encf", invoice_dict.get("encf", ""))
            invoice_dict["xmlSignature"] = res.get("xmlSignature") or res.get("trackId") or ""
            invoice_dict["qrCodeURL"] = res.get("qrCodeURL", "")
            invoice_dict["firebasePDFURL"] = res.get("pdfUrl", "")
            invoice_dict["firebaseXMLURL"] = res.get("xmlUrl", "")
            invoice_dict["isSyncedWithDGII"] = (res.get("mode", "API") == "API" and res.get("status") != "PENDING")
            invoice_dict["emisionMode"] = res.get("mode", "API")
            
            # Guardamos con el estado final actualizado
            DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)
            
            return jsonify({
                "success": True,
                "message": "Factura Electrónica e-CF emitida exitosamente.",
                "invoice_id": invoice_id,
                "encf": invoice_dict["encf"],
                "track_id": res.get("trackId") or res.get("xmlSignature") or "",
                "xmlSignature": res.get("xmlSignature") or "",
                "qrCodeURL": res.get("qrCodeURL", ""),
                "pdfUrl": res.get("pdfUrl", ""),
                "xmlUrl": res.get("xmlUrl", ""),
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


@api_invoices_bp.route('/invoices/<invoice_id>/status', methods=['GET'])
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


@api_invoices_bp.route('/invoices/<invoice_id>/cancel', methods=['POST'])
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


@api_invoices_bp.route('/invoices/calculate', methods=['POST'])
@require_api_key
def calculate_totals():
    """
    POST /api/v1/invoices/calculate
    Calcula los totales de impuestos exactos (con ISC, propina, retenciones y redondeo de ley).
    """
    try:
        data = request.json or {}
        items = data.get('items', [])
        
        discount_rate = float(data.get('discount_rate', 0.0))
        retained_isr_rate = float(data.get('retained_isr_rate', 0.0))
        retained_itbis_rate = float(data.get('retained_itbis_rate', 0.0))
        
        formatted_items = []
        for item in items:
            formatted_items.append({
                "price": float(item.get('price', 0.0)),
                "quantity": float(item.get('quantity', 1.0)),
                "itbisRate": float(item.get('itbis_rate', item.get('itbisRate', 0.18))),
                "discountRate": float(item.get('discountRate', 0.0)),
                "codigoImpuesto": item.get('codigoImpuesto', ''),
                "tasaImpuestoAdicional": float(item.get('tasaImpuestoAdicional', 0.0)),
                "gradosAlcohol": float(item.get('gradosAlcohol', 0.0)),
                "cantidadReferencia": float(item.get('cantidadReferencia', 0.0)),
                "subcantidad": float(item.get('subcantidad', 1.0)),
                "precioReferencia": float(item.get('precioReferencia', 0.0))
            })
            
        calcs = DGIIService.calculate_invoice_totals(
            formatted_items,
            discount_rate=discount_rate,
            retained_isr_rate=retained_isr_rate,
            retained_itbis_rate=retained_itbis_rate
        )
        
        return jsonify({
            "success": True,
            "calculations": calcs
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices', methods=['GET'])
@require_api_key
def get_invoices():
    """
    GET /api/v1/invoices
    Retorna la lista de facturas o cotizaciones para el owner de la API.
    Filtro opcional: ?is_quotation=true/false
    """
    try:
        is_quotation = request.args.get('is_quotation', 'false').lower() == 'true'
        invoices = DatabaseService.get_invoices(g.owner_uid, sandbox=g.sandbox_mode, quotations_only=is_quotation)
        return jsonify({
            "success": True,
            "invoices": invoices
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/documents', methods=['GET'])
@require_api_key
def get_documents():
    """
    GET /api/v1/documents
    Retorna la lista de todos los documentos (facturas y cotizaciones) para el owner de la API.
    """
    try:
        documents = DatabaseService.get_invoices(g.owner_uid, sandbox=g.sandbox_mode, include_all=True)
        return jsonify({
            "success": True,
            "invoices": documents
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices/<invoice_id>', methods=['GET'])
@require_api_key
def get_invoice_detail(invoice_id):
    """
    GET /api/v1/invoices/<invoice_id>
    Retorna el detalle completo de un documento específico.
    """
    try:
        invoice = DatabaseService.get_invoice(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
        if not invoice:
            return jsonify({"success": False, "error": "Documento no encontrado."}), 404
        return jsonify({
            "success": True,
            "invoice": invoice
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices', methods=['POST'])
@require_api_key
def create_draft_invoice():
    """
    POST /api/v1/invoices
    Crea un nuevo Borrador de Factura o una Cotización en Firestore.
    """
    try:
        data = request.json or {}
        items = data.get('items', [])
        
        is_quotation = bool(data.get('is_quotation', False))
        ecf_type = data.get('ecf_type', 'Factura de Consumo (E32)')
        if is_quotation:
            ecf_type = "Cotización"
            
        discount_rate = float(data.get('discount_rate', 0.0))
        retained_isr_rate = float(data.get('retained_isr_rate', 0.0))
        retained_itbis_rate = float(data.get('retained_itbis_rate', 0.0))
        
        formatted_items = []
        for index, item in enumerate(items):
            formatted_items.append({
                "id": item.get('id', f"item_{index}"),
                "code": item.get('code', ''),
                "type": item.get('type', 'Bien'),
                "name": item.get('name', 'Artículo'),
                "price": float(item.get('price', 0.0)),
                "quantity": float(item.get('quantity', 1.0)),
                "itbisRate": float(item.get('itbis_rate', item.get('itbisRate', 0.18))),
                "discountRate": float(item.get('discountRate', 0.0)),
                "codigoImpuesto": item.get('codigoImpuesto', ''),
                "tasaImpuestoAdicional": float(item.get('tasaImpuestoAdicional', 0.0)),
                "gradosAlcohol": float(item.get('gradosAlcohol', 0.0)),
                "cantidadReferencia": float(item.get('cantidadReferencia', 0.0)),
                "subcantidad": float(item.get('subcantidad', 1.0)),
                "precioReferencia": float(item.get('precioReferencia', 0.0))
            })
            
        calcs = DGIIService.calculate_invoice_totals(
            formatted_items,
            discount_rate=discount_rate,
            retained_isr_rate=retained_isr_rate,
            retained_itbis_rate=retained_itbis_rate
        )
        
        invoice_id = data.get('id') or str(uuid.uuid4())
        random_num = f"{uuid.uuid4().int}"[:6]
        inv_number = data.get('invoiceNumber') or (f"COT-{random_num}" if is_quotation else f"FAC-{random_num}")
        
        invoice_dict = {
            "invoiceNumber": inv_number,
            "date": data.get('date', datetime.utcnow().isoformat()),
            "dueDate": data.get('due_date', (datetime.utcnow() + timedelta(days=30)).isoformat()),
            "clientId": data.get('client_id', ''),
            "clientName": data.get('client_name', 'Consumidor Final'),
            "clientRNC": data.get('client_rnc', ''),
            "status": data.get('status', 'Borrador'),
            "ecfType": ecf_type,
            "encf": data.get('encf', ''),
            "xmlSignature": data.get('xml_signature', ''),
            "qrCodeURL": data.get('qr_code_url', ''),
            "isSyncedWithDGII": bool(data.get('is_synced_dgii', False)),
            "creditedAmount": float(data.get('credited_amount', 0.0)),
            "retainedISR": calcs["retained_isr"],
            "retainedITBIS": calcs["retained_itbis"],
            "netPayable": calcs["net_payable"],
            "subtotal": calcs["subtotal"],
            "totalITBIS": calcs["total_itbis"],
            "total": calcs["total"],
            "totalISCEspecifico": calcs["total_isc_especifico"],
            "totalISCAdValorem": calcs["total_isc_advalorem"],
            "totalOtrosImpuestos": calcs["total_otros_impuestos"],
            "isQuotation": is_quotation,
            "isConvertedToInvoice": bool(data.get('is_converted', False)),
            "notes": data.get('notes', ''),
            "comentario": data.get('comentario', ''),
            "isRecurring": bool(data.get('is_recurring', False)),
            "recurrenceInterval": data.get('recurrence_interval', 'mensual'),
            "nextOccurrenceDate": data.get('next_occurrence_date'),
            "firebasePDFURL": data.get('pdf_url', ''),
            "firebaseXMLURL": data.get('xml_url', ''),
            "currency": data.get('currency', 'DOP'),
            "paymentType": data.get('payment_type', 'Contado'),
            "paymentMethod": data.get('payment_method', 'Efectivo'),
            "incomeType": data.get('income_type', '01 - Ingresos por operaciones'),
            "customFields": data.get('custom_fields', []),
            "exchangeRate": float(data.get('exchange_rate', 1.0)),
            "warehouseId": data.get('warehouse_id', ''),
            "branchId": data.get('branch_id', 'default-sucursal-principal'),
            "items": calcs["items"],
            "totalPaid": float(data.get('total_paid', 0.0)),
            "remainingBalance": calcs["net_payable"] - float(data.get('total_paid', 0.0)),
            "createdAt": datetime.utcnow().isoformat()
        }
        
        DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Documento guardado exitosamente.",
            "invoice_id": invoice_id,
            "invoice": invoice_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices/<invoice_id>', methods=['PUT'])
@require_api_key
def update_invoice(invoice_id):
    """
    PUT /api/v1/invoices/<invoice_id>
    Actualiza un borrador o cotización en Firestore.
    """
    try:
        invoice = DatabaseService.get_invoice(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
        if not invoice:
            return jsonify({"success": False, "error": "Documento no encontrado."}), 404
            
        if invoice.get('status') not in ['Borrador', 'Rechazada'] and not invoice.get('isQuotation'):
            return jsonify({"success": False, "error": "Solo se pueden editar documentos en estado Borrador o cotizaciones."}), 422
            
        data = request.json or {}
        items = data.get('items', invoice.get('items', []))
        
        discount_rate = float(data.get('discount_rate', invoice.get('discountRate', 0.0)))
        retained_isr_rate = float(data.get('retained_isr_rate', invoice.get('retainedISR', 0.0)))
        retained_itbis_rate = float(data.get('retained_itbis_rate', invoice.get('retainedITBIS', 0.0)))
        
        formatted_items = []
        for index, item in enumerate(items):
            formatted_items.append({
                "id": item.get('id', item.get('itemId', f"item_{index}")),
                "code": item.get('code', ''),
                "type": item.get('type', 'Bien'),
                "name": item.get('name', 'Artículo'),
                "price": float(item.get('price', 0.0)),
                "quantity": float(item.get('quantity', 1.0)),
                "itbisRate": float(item.get('itbisRate', item.get('itbis_rate', 0.18))),
                "discountRate": float(item.get('discountRate', 0.0)),
                "codigoImpuesto": item.get('codigoImpuesto', ''),
                "tasaImpuestoAdicional": float(item.get('tasaImpuestoAdicional', 0.0)),
                "gradosAlcohol": float(item.get('gradosAlcohol', 0.0)),
                "cantidadReferencia": float(item.get('cantidadReferencia', 0.0)),
                "subcantidad": float(item.get('subcantidad', 1.0)),
                "precioReferencia": float(item.get('precioReferencia', 0.0))
            })
            
        calcs = DGIIService.calculate_invoice_totals(
            formatted_items,
            discount_rate=discount_rate,
            retained_isr_rate=retained_isr_rate,
            retained_itbis_rate=retained_itbis_rate
        )
        
        invoice_dict = {
            **invoice,
            "dueDate": data.get('due_date', invoice.get('dueDate')),
            "clientId": data.get('client_id', invoice.get('clientId')),
            "clientName": data.get('client_name', invoice.get('clientName')),
            "clientRNC": data.get('client_rnc', invoice.get('clientRNC')),
            "ecfType": data.get('ecf_type', invoice.get('ecfType')),
            "retainedISR": calcs["retained_isr"],
            "retainedITBIS": calcs["retained_itbis"],
            "netPayable": calcs["net_payable"],
            "subtotal": calcs["subtotal"],
            "totalITBIS": calcs["total_itbis"],
            "total": calcs["total"],
            "totalISCEspecifico": calcs["total_isc_especifico"],
            "totalISCAdValorem": calcs["total_isc_advalorem"],
            "totalOtrosImpuestos": calcs["total_otros_impuestos"],
            "isQuotation": bool(data.get('is_quotation', invoice.get('isQuotation'))),
            "isConvertedToInvoice": bool(data.get('is_converted', invoice.get('isConvertedToInvoice'))),
            "notes": data.get('notes', invoice.get('notes')),
            "comentario": data.get('comentario', invoice.get('comentario', '')),
            "isRecurring": bool(data.get('is_recurring', invoice.get('isRecurring'))),
            "recurrenceInterval": data.get('recurrence_interval', invoice.get('recurrenceInterval')),
            "nextOccurrenceDate": data.get('next_occurrence_date', invoice.get('nextOccurrenceDate')),
            "currency": data.get('currency', invoice.get('currency')),
            "paymentType": data.get('payment_type', invoice.get('paymentType')),
            "paymentMethod": data.get('payment_method', invoice.get('paymentMethod')),
            "incomeType": data.get('income_type', invoice.get('incomeType')),
            "warehouseId": data.get('warehouse_id', invoice.get('warehouseId')),
            "items": calcs["items"],
            "remainingBalance": calcs["net_payable"] - float(invoice.get('totalPaid', 0.0))
        }
        
        DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Documento actualizado exitosamente.",
            "invoice": invoice_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices/<invoice_id>', methods=['DELETE'])
@require_api_key
def delete_invoice(invoice_id):
    """
    DELETE /api/v1/invoices/<invoice_id>
    Elimina un documento Borrador o Cotización en Firestore.
    """
    try:
        invoice = DatabaseService.get_invoice(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
        if not invoice:
            return jsonify({"success": False, "error": "Documento no encontrado."}), 404
            
        if invoice.get('status') not in ['Borrador', 'Rechazada'] and not invoice.get('isQuotation'):
            return jsonify({"success": False, "error": "No se puede eliminar un documento emitido o cobrado."}), 422
            
        # Borrar de Firestore
        DatabaseService.delete_invoice(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
            
        return jsonify({
            "success": True,
            "message": "Documento eliminado exitosamente."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =========================================================================
# ENDPOINTS PARA PRODUCTOS / SERVICIOS (ITEMS)
# =========================================================================

@api_invoices_bp.route('/items', methods=['GET'])
@require_api_key
def get_items():
    """
    GET /api/v1/items
    Retorna el catálogo de artículos y servicios de la empresa.
    """
    try:
        items = DatabaseService.get_items(g.owner_uid, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/items', methods=['POST'])
@require_api_key
def create_item():
    """
    POST /api/v1/items
    Registra un nuevo artículo o servicio en el catálogo.
    """
    try:
        data = request.json or {}
        name = data.get('name')
        price = float(data.get('price', 0.0))
        
        if not name:
            return jsonify({"success": False, "error": "El nombre del artículo es requerido."}), 400
            
        item_id = data.get('id') or str(uuid.uuid4())
        item_dict = {
            "name": name,
            "price": price,
            "code": data.get('code', ''),
            "type": data.get('type', 'Bien'),
            "unit": data.get('unit', 'Unidad'),
            "itbisRate": float(data.get('itbis_rate', data.get('itbisRate', 0.18))),
            "minStock": float(data.get('min_stock', data.get('minStock', 0.0))),
            "rackLocation": data.get('rack_location', data.get('rackLocation', '')),
            "totalStock": float(data.get('total_stock', data.get('totalStock', 0.0)))
        }
        
        DatabaseService.save_item(g.owner_uid, item_id, item_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Artículo del catálogo registrado exitosamente.",
            "item_id": item_id,
            "item": item_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/items/<item_id>', methods=['PUT'])
@require_api_key
def update_item(item_id):
    """
    PUT /api/v1/items/<item_id>
    Actualiza la información de un producto o servicio del catálogo.
    """
    try:
        items = DatabaseService.get_items(g.owner_uid, sandbox=g.sandbox_mode)
        item = next((i for i in items if i['id'] == item_id), None)
        if not item:
            return jsonify({"success": False, "error": "Artículo no encontrado."}), 404
            
        data = request.json or {}
        item_dict = {
            **item,
            "name": data.get('name', item.get('name')),
            "price": float(data.get('price', item.get('price'))),
            "code": data.get('code', item.get('code')),
            "type": data.get('type', item.get('type')),
            "unit": data.get('unit', item.get('unit')),
            "itbisRate": float(data.get('itbis_rate', data.get('itbisRate', item.get('itbisRate')))),
            "minStock": float(data.get('min_stock', data.get('minStock', item.get('minStock')))),
            "rackLocation": data.get('rack_location', data.get('rackLocation', item.get('rackLocation'))),
            "totalStock": float(data.get('total_stock', data.get('totalStock', item.get('totalStock'))))
        }
        
        DatabaseService.save_item(g.owner_uid, item_id, item_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Artículo del catálogo actualizado exitosamente.",
            "item": item_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/items/<item_id>', methods=['DELETE'])
@require_api_key
def delete_item_route(item_id):
    """
    DELETE /api/v1/items/<item_id>
    Elimina un artículo del catálogo de Firestore.
    """
    try:
        DatabaseService.delete_item(g.owner_uid, item_id, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "message": "Artículo eliminado exitosamente."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =========================================================================
# ENDPOINTS PARA GASTOS / EGRESOS (EXPENSES)
# =========================================================================

@api_invoices_bp.route('/expenses', methods=['GET'])
@require_api_key
def get_expenses():
    """
    GET /api/v1/expenses
    Retorna el histórico de gastos de la empresa.
    """
    try:
        expenses = DatabaseService.get_expenses(g.owner_uid, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "expenses": expenses})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/expenses', methods=['POST'])
@require_api_key
def create_expense():
    """
    POST /api/v1/expenses
    Registra un nuevo gasto ante la DGII.
    """
    try:
        data = request.json or {}
        concept = data.get('concept')
        amount = float(data.get('amount', 0.0))
        
        if not concept:
            return jsonify({"success": False, "error": "El concepto del gasto es requerido."}), 400
            
        expense_id = data.get('id') or str(uuid.uuid4())
        expense_dict = {
            "concept": concept,
            "category": data.get('category', 'Otros'),
            "amount": amount,
            "date": data.get('date', datetime.utcnow().isoformat()),
            "rncEmisor": data.get('rnc_emisor', data.get('rncEmisor', '')),
            "ncf": data.get('ncf', ''),
            "isMinorExpense": bool(data.get('is_minor_expense', data.get('isMinorExpense', False))),
            "isSyncedWithDGII": bool(data.get('is_synced_dgii', data.get('isSyncedWithDGII', False))),
            "qrCodeURL": data.get('qr_code_url', data.get('qrCodeURL', '')),
            "xmlSignature": data.get('xml_signature', data.get('xmlSignature', '')),
            "notes": data.get('notes', ''),
            "isRecurring": bool(data.get('is_recurring', data.get('isRecurring', False))),
            "recurrenceInterval": data.get('recurrence_interval', data.get('recurrenceInterval', 'mensual')),
            "nextOccurrenceDate": data.get('next_occurrence_date'),
            "associatedInvoiceId": data.get('associated_invoice_id', data.get('associatedInvoiceId', '')),
            "itbisAmount": float(data.get('itbis_amount', data.get('itbisAmount', 0.0))),
            "isITBISDeductible": bool(data.get('is_itbis_deductible', data.get('isITBISDeductible', True))),
            "isDeductible": bool(data.get('is_deductible', data.get('isDeductible', True))),
            "firebaseAttachmentURLs": data.get('firebase_attachment_urls', data.get('firebaseAttachmentURLs', []))
        }
        
        DatabaseService.save_expense(g.owner_uid, expense_id, expense_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Gasto registrado exitosamente.",
            "expense_id": expense_id,
            "expense": expense_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/expenses/<expense_id>', methods=['PUT'])
@require_api_key
def update_expense(expense_id):
    """
    PUT /api/v1/expenses/<expense_id>
    Actualiza la información de un gasto existente.
    """
    try:
        expenses = DatabaseService.get_expenses(g.owner_uid, sandbox=g.sandbox_mode)
        expense = next((e for e in expenses if e['id'] == expense_id), None)
        if not expense:
            return jsonify({"success": False, "error": "Gasto no encontrado."}), 404
            
        data = request.json or {}
        expense_dict = {
            **expense,
            "concept": data.get('concept', expense.get('concept')),
            "category": data.get('category', expense.get('category')),
            "amount": float(data.get('amount', expense.get('amount'))),
            "date": data.get('date', expense.get('date')),
            "rncEmisor": data.get('rnc_emisor', data.get('rncEmisor', expense.get('rncEmisor'))),
            "ncf": data.get('ncf', expense.get('ncf')),
            "isMinorExpense": bool(data.get('is_minor_expense', data.get('isMinorExpense', expense.get('isMinorExpense')))),
            "isSyncedWithDGII": bool(data.get('is_synced_dgii', data.get('isSyncedWithDGII', expense.get('isSyncedWithDGII')))),
            "qrCodeURL": data.get('qr_code_url', data.get('qrCodeURL', expense.get('qrCodeURL'))),
            "xmlSignature": data.get('xml_signature', data.get('xmlSignature', expense.get('xmlSignature'))),
            "notes": data.get('notes', expense.get('notes')),
            "isRecurring": bool(data.get('is_recurring', data.get('isRecurring', expense.get('isRecurring')))),
            "recurrenceInterval": data.get('recurrence_interval', data.get('recurrenceInterval', expense.get('recurrenceInterval'))),
            "nextOccurrenceDate": data.get('next_occurrence_date', expense.get('nextOccurrenceDate')),
            "associatedInvoiceId": data.get('associated_invoice_id', data.get('associatedInvoiceId', expense.get('associatedInvoiceId'))),
            "itbisAmount": float(data.get('itbis_amount', data.get('itbisAmount', expense.get('itbisAmount')))),
            "isITBISDeductible": bool(data.get('is_itbis_deductible', data.get('isITBISDeductible', expense.get('isITBISDeductible')))),
            "isDeductible": bool(data.get('is_deductible', data.get('isDeductible', expense.get('isDeductible')))),
            "firebaseAttachmentURLs": data.get('firebase_attachment_urls', data.get('firebaseAttachmentURLs', expense.get('firebaseAttachmentURLs')))
        }
        
        DatabaseService.save_expense(g.owner_uid, expense_id, expense_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Gasto actualizado exitosamente.",
            "expense": expense_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/expenses/<expense_id>', methods=['DELETE'])
@require_api_key
def delete_expense_route(expense_id):
    """
    DELETE /api/v1/expenses/<expense_id>
    Elimina un gasto de la base de datos de Firestore.
    """
    try:
        DatabaseService.delete_expense(g.owner_uid, expense_id, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "message": "Gasto eliminado exitosamente."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =========================================================================
# ENDPOINT PARA DASHBOARD EJECUTIVO (METRICS)
# =========================================================================

@api_invoices_bp.route('/dashboard/summary', methods=['GET'])
@require_api_key
def get_dashboard_summary():
    """
    GET /api/v1/dashboard/summary
    Retorna métricas consolidadas (ingresos, gastos, cuentas por cobrar, etc.) calculadas por el backend.
    """
    try:
        invoices = DatabaseService.get_invoices(g.owner_uid, sandbox=g.sandbox_mode)
        expenses = DatabaseService.get_expenses(g.owner_uid, sandbox=g.sandbox_mode)
        
        real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
        
        total_invoiced = sum(inv.get('total', 0.0) for inv in real_invoices)
        total_expenses = sum(exp.get('amount', 0.0) for exp in expenses)
        total_itbis = sum(inv.get('totalITBIS', 0.0) for inv in real_invoices)
        total_cxc = sum(inv.get('remainingBalance', inv.get('netPayable', 0.0)) for inv in real_invoices if inv.get('status') in ['Emitida', 'Vencida', 'Parcialmente Cobrada'])
        
        margin_net = 0.0
        if total_invoiced > 0:
            margin_net = ((total_invoiced - total_expenses) / total_invoiced) * 100
            
        recent_invoices = invoices[:5]
        recent_expenses = expenses[:5]
        
        return jsonify({
            "success": True,
            "metrics": {
                "total_invoiced": total_invoiced,
                "total_expenses": total_expenses,
                "total_itbis": total_itbis,
                "total_cxc": total_cxc,
                "margin_net": margin_net,
                "net_profit": total_invoiced - total_expenses
            },
            "recent_invoices": recent_invoices,
            "recent_expenses": recent_expenses
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =========================================================================
# ENDPOINTS PARA CORREOS ELECTRÓNICOS
# =========================================================================

@api_invoices_bp.route('/invoices/<invoice_id>/send_receipt', methods=['POST'])
@require_api_key
def send_receipt_endpoint(invoice_id):
    """
    POST /api/v1/invoices/<invoice_id>/send_receipt
    Envía un Recibo de Ingreso por email al cliente.
    """
    try:
        data = request.json or {}
        recipient_email = (data.get("email") or "").strip()
        if not recipient_email:
            return jsonify({"success": False, "error": "Dirección de email no especificada."}), 400

        invoice = DatabaseService.get_invoice(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
        if not invoice:
            return jsonify({"success": False, "error": "Factura no encontrada."}), 404

        company = DatabaseService.get_company_profile(g.owner_uid)

        payment_id      = data.get("paymentId", "")
        payment_date    = data.get("paymentDate", datetime.utcnow().strftime('%Y-%m-%d'))
        payment_method  = data.get("paymentMethod", "Efectivo")
        payment_bank    = data.get("bank", "")
        payment_ref     = data.get("referenceNumber", "")
        payment_amount  = float(data.get("amount", 0.0))

        receipt_no = (payment_id[-8:].upper() if payment_id else "N/A")

        from flask import current_app as app
        smtp_server   = app.config.get("SMTP_SERVER", "")
        smtp_port     = int(app.config.get("SMTP_PORT", 587))
        smtp_user     = app.config.get("SMTP_USER", "")
        smtp_password = app.config.get("SMTP_PASSWORD", "")

        if not smtp_user or not smtp_password:
            return jsonify({"success": False, "error": "El servidor de correo no está configurado en el backend."}), 503

        company_name    = company.get("tradeName") or company.get("companyName", "e-Factura")

        html_body = f"""
        <html><body>
        <h2>Recibo de Ingreso - {company_name}</h2>
        <p>No. Recibo: {receipt_no}</p>
        <p>Fecha de Pago: {payment_date}</p>
        <p>Factura de Referencia: {invoice.get('invoiceNumber','')}</p>
        <p>Forma de Pago: {payment_method}</p>
        <p>Monto Recibido: RD$ {payment_amount:,.2f}</p>
        </body></html>
        """

        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Recibo de Pago - Factura {invoice.get('invoiceNumber', '')} | {company_name}"
        msg["From"]    = f"{company_name} <{smtp_user}>"
        msg["To"]      = recipient_email

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipient_email, msg.as_string())

        return jsonify({"success": True, "message": f"Recibo enviado exitosamente a {recipient_email}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices/<invoice_id>/send_email', methods=['POST'])
@require_api_key
def send_invoice_email_endpoint(invoice_id):
    """
    POST /api/v1/invoices/<invoice_id>/send_email
    Envía la factura electrónica (XML/PDF) por email al cliente usando SMTP.
    """
    try:
        data = request.json or {}
        recipient_email = (data.get("email") or "").strip()
        if not recipient_email:
            return jsonify({"success": False, "error": "Dirección de correo no especificada."}), 400

        invoice = DatabaseService.get_invoice(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
        if not invoice:
            return jsonify({"success": False, "error": "Factura no encontrada."}), 404

        company = DatabaseService.get_company_profile(g.owner_uid)

        from flask import current_app as app
        smtp_server   = app.config.get("SMTP_SERVER", "")
        smtp_port     = int(app.config.get("SMTP_PORT", 587))
        smtp_user     = app.config.get("SMTP_USER", "")
        smtp_password = app.config.get("SMTP_PASSWORD", "")

        if not smtp_server or not smtp_user or not smtp_password:
            return jsonify({"success": False, "error": "Servidor de correo no configurado (SMTP)."}), 500

        xml_content = invoice.get('xmlContent') or invoice.get('xmlSignature') or ''
        
        pdf_url = invoice.get("firebasePDFURL", "")
        xml_url = invoice.get("firebaseXMLURL", "")

        company_name = company.get("tradeName") or company.get("companyName", "EMISOR")
        encf = invoice.get('encf', 'N/A')
        ecf_type = invoice.get('ecfType', 'Factura de Consumo Electrónica')

        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.application import MIMEApplication

        msg = MIMEMultipart()
        msg["Subject"] = f"{ecf_type} No. [{encf}] - [{company_name}]"
        msg["From"] = f"{company_name} <{smtp_user}>"
        msg["To"] = recipient_email

        html_body = f"""
        <html><body>
        <h2>{company_name}</h2>
        <p>Estimado cliente,</p>
        <p>Adjunto a este correo encontrará su comprobante electrónico ({ecf_type}) con e-NCF {encf}.</p>
        <p>Puede visualizar el PDF de su factura en el siguiente enlace: <a href="{pdf_url}">Ver Factura (PDF)</a></p>
        <p>Puede descargar el XML de su factura en el siguiente enlace: <a href="{xml_url}">Descargar Factura (XML)</a></p>
        </body></html>
        """

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if xml_content:
            xml_attachment = MIMEApplication(xml_content.encode('utf-8'), _subtype="xml")
            xml_attachment.add_header('Content-Disposition', 'attachment', filename=f"{encf}.xml")
            msg.attach(xml_attachment)

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipient_email, msg.as_string())

        return jsonify({"success": True, "message": f"Factura enviada exitosamente por correo a {recipient_email}."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/company/plan-consumption', methods=['GET'])
@require_api_key
def get_company_plan_consumption():
    """
    GET /api/v1/company/plan-consumption
    Retorna la información del plan activo y el consumo actual de comprobantes de la empresa.
    """
    try:
        owner_uid = g.owner_uid
        sandbox = g.sandbox_mode
        company = g.company
        
        billing_day = company.get('billingDay', 1)
        plan_stats = DatabaseService.get_invoice_stats(owner_uid, billing_day)
        
        docs_used = plan_stats['sandbox_current_cycle'] if sandbox else plan_stats['prod_current_cycle']
        docs_limit = int(company.get('documentLimit', 100)) if company.get('documentLimit') else 100
        plan_pct = min(100.0, (docs_used / docs_limit) * 100.0) if docs_limit > 0 else 0.0
        
        plan_name = "Plan Personalizado"
        try:
            plan_id = company.get('planId')
            if plan_id:
                from app.services.db_service import db_firestore
                plan_doc = db_firestore.collection('plans').document(plan_id).get()
                if plan_doc.exists:
                    plan_name = plan_doc.to_dict().get('name', 'Plan Activo')
        except Exception:
            pass
            
        return jsonify({
            "success": True,
            "plan_name": plan_name,
            "billing_type": company.get('billingType', 'Pago por uso'),
            "document_limit": docs_limit,
            "documents_used": docs_used,
            "consumption_percentage": plan_pct,
            "sandbox_mode": sandbox
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

