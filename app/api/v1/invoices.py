# app/api/v1/invoices.py
import json
import uuid
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, g, jsonify
from app.api.auth import require_api_key
from app.services.db_service import DatabaseService
from app.services.mailer import Mailer
from app.services.ecf_emission import EcfEmissionService
from app.services.dgii import DGIIService
from app.utils.cache_utils import http_cache
from app.utils.ecf_utils import get_ecf_type_short_code
from app.brand import get_product_name

api_invoices_bp = Blueprint('api_invoices', __name__)

@api_invoices_bp.route('/invoices/emit', methods=['POST'])
@require_api_key
def emit_invoice():
    """
    Emite un comprobante fiscal electrónico (e-CF)
    ---
    tags:
      - Invoices
    summary: Emite un comprobante fiscal electronico (e-CF) ante la DGII
    description: |
      Recibe la informacion de la factura en JSON, calcula los impuestos
      (ITBIS, ISC, retenciones) y emite el e-CF via el proveedor autorizado.
      Soporta clave de idempotencia via header Idempotency-Key.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: Idempotency-Key
        in: header
        required: false
        type: string
        description: Clave de idempotencia para evitar duplicados
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [items]
          properties:
            items:
              type: array
              description: Lista de articulos del documento
              items:
                type: object
                properties:
                  id:
                    type: string
                    description: ID del articulo
                  name:
                    type: string
                    description: Nombre del articulo
                  price:
                    type: number
                    description: Precio unitario
                  quantity:
                    type: number
                    description: Cantidad
                  itbis_rate:
                    type: number
                    description: Tasa de ITBIS (default 0.18)
                  discount_rate:
                    type: number
                    description: Tasa de descuento
                  type:
                    type: string
                    description: Tipo (Bien/Servicio)
                  unit:
                    type: string
                    description: Unidad de medida
            client_rnc:
              type: string
              description: RNC del cliente
            client_name:
              type: string
              description: Nombre del cliente
            client_id:
              type: string
              description: ID del cliente
            ecf_type:
              type: string
              description: Tipo de comprobante fiscal
            payment_method:
              type: string
              description: Metodo de pago
            due_date:
              type: string
              description: Fecha de vencimiento (YYYY-MM-DD)
            discount_rate:
              type: number
              description: Tasa de descuento global
            retained_isr_rate:
              type: number
              description: Tasa de retencion de ISR
            retained_itbis_rate:
              type: number
              description: Tasa de retencion de ITBIS
            currency:
              type: string
              description: Moneda (DOP)
            income_type:
              type: string
              description: Tipo de ingreso segun DGII
    responses:
      200:
        description: Factura emitida exitosamente
      400:
        description: Payload invalido
      422:
        description: Error del proveedor de facturacion
      500:
        description: Error interno del servidor
    """
    try:
        data = request.json or {}
        idempotency_key = request.headers.get('Idempotency-Key') or data.get('idempotency_key')
        if idempotency_key:
            record = DatabaseService.get_idempotency_record(g.owner_uid, idempotency_key, sandbox=g.sandbox_mode)
            if record and record.get("response"):
                status_code = int(record.get("statusCode", 200))
                return jsonify(record["response"]), status_code
        
        # Validaciones iniciales del Payload
        items = data.get('items', [])
        if not items:
            return jsonify({"success": False, "error": "El documento debe contener al menos un artículo ('items')."}), 400
            
        client_rnc = data.get('client_rnc', '')
        client_name = data.get('client_name', 'Consumidor Final')
        
        ecf_type = data.get('ecf_type', 'Factura de Consumo (E32)')
        payment_method = data.get('payment_method', 'Efectivo')
        due_date = data.get('due_date', datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        
        # Cálculo fiscal completo (DGII)
        parsed_items = []
        for index, item in enumerate(items):
            price = float(item.get('price', 0.0))
            qty = float(item.get('quantity', 1.0))
            itbis_rate = float(item.get('itbis_rate', item.get('itbisRate', 0.18)))
            parsed_items.append({
                "id": item.get('id') or item.get('item_id') or f"api_item_{index}",
                "code": item.get('code', ''),
                "type": item.get('type', 'Bien'),
                "name": item.get('name', 'Artículo Genérico'),
                "price": price,
                "quantity": qty,
                "unit": item.get('unit', 'Unidad'),
                "itbisRate": itbis_rate,
                "discountRate": float(item.get('discount_rate', item.get('discountRate', 0.0))),
                "codigoImpuesto": item.get('codigo_impuesto', item.get('codigoImpuesto', '')),
                "tasaImpuestoAdicional": float(item.get('tasa_impuesto_adicional', item.get('tasaImpuestoAdicional', 0.0))),
                "gradosAlcohol": float(item.get('grados_alcohol', item.get('gradosAlcohol', 0.0))),
                "cantidadReferencia": float(item.get('cantidad_referencia', item.get('cantidadReferencia', 0.0))),
                "subcantidad": float(item.get('subcantidad', 1.0)),
                "precioReferencia": float(item.get('precio_referencia', item.get('precioReferencia', 0.0))),
                "tasaImpuestoAdValorem": float(item.get('tasa_impuesto_ad_valorem', item.get('tasaImpuestoAdValorem', 0.0)))
            })

        discount_rate = float(data.get('discount_rate', 0.0))
        retained_isr_rate = float(data.get('retained_isr_rate', data.get('retainedISRRate', 0.0)))
        retained_itbis_rate = float(data.get('retained_itbis_rate', data.get('retainedITBISRate', 0.0)))
        calcs = DGIIService.calculate_invoice_totals(
            parsed_items,
            discount_rate=discount_rate,
            retained_isr_rate=retained_isr_rate,
            retained_itbis_rate=retained_itbis_rate
        )
        
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
            "retainedISR": calcs["retained_isr"],
            "retainedITBIS": calcs["retained_itbis"],
            "subtotal": calcs["subtotal"],
            "totalITBIS": calcs["total_itbis"],
            "total": calcs["total"],
            "netPayable": calcs["net_payable"],
            "totalISCEspecifico": calcs["total_isc_especifico"],
            "totalISCAdValorem": calcs["total_isc_advalorem"],
            "totalOtrosImpuestos": calcs["total_otros_impuestos"],
            "items": calcs["items"],
            "status": "Borrador",
            "date": datetime.now(timezone.utc).isoformat(),
            "incomeType": data.get('income_type', '01 - Ingresos por operaciones'),
            "isQuotation": False,
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
        
        # Consumir el siguiente consecutivo del rango fiscal DGII si no se ha asignado y no es cotización
        if not invoice_dict.get("encf"):
            ecf_short = get_ecf_type_short_code(invoice_dict["ecfType"])
            user_email = g.company.get("companyEmail", "api@vykcore.com")
            
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
            pending_dgii = res.get("status") == "PENDING" or res.get("mode") == "FALLBACK"
            invoice_dict["status"] = "Pendiente DGII" if pending_dgii else "Emitida"
            invoice_dict["encf"] = res.get("encf", invoice_dict.get("encf", ""))
            invoice_dict["xmlSignature"] = res.get("xmlSignature") or res.get("trackId") or ""
            invoice_dict["qrCodeURL"] = res.get("qrCodeURL", "")
            invoice_dict["firebasePDFURL"] = res.get("pdfUrl", "")
            invoice_dict["firebaseXMLURL"] = res.get("xmlUrl", "")
            invoice_dict["isSyncedWithDGII"] = (res.get("mode", "API") == "API" and res.get("status") != "PENDING")
            invoice_dict["emisionMode"] = res.get("mode", "API")
            invoice_dict["dgiiStatus"] = res.get("dgiiStatus") or ("PENDING" if pending_dgii else "ACCEPTED")
            
            # Guardamos con el estado final actualizado
            DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)

            # Generar asiento contable automático
            try:
                from app.services.accounting_service import AccountingService
                AccountingService.auto_generate_invoice_entry(g.owner_uid, invoice_dict, sandbox=g.sandbox_mode)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(f"Asiento contable API no generado: {exc}")

            # Event Bus: notificar emisión de factura vía API
            try:
                from app.events import get_event_bus, InvoiceEmitted
                country = g.company.get("country", "DO") if g.company else "DO"
                get_event_bus().publish(InvoiceEmitted(
                    owner_uid=g.owner_uid,
                    invoice_id=invoice_id,
                    invoice_number=invoice_dict.get("invoiceNumber", ""),
                    invoice_data=invoice_dict,
                    sandbox=g.sandbox_mode,
                    country=country,
                ))
            except Exception:
                pass
            
            response_body = {
                "success": True,
                "message": "Factura Electrónica e-CF emitida exitosamente.",
                "invoice_id": invoice_id,
                "encf": invoice_dict["encf"],
                "track_id": res.get("trackId") or res.get("xmlSignature") or "",
                "xmlSignature": res.get("xmlSignature") or "",
                "qrCodeURL": res.get("qrCodeURL", ""),
                "pdfUrl": res.get("pdfUrl", ""),
                "xmlUrl": res.get("xmlUrl", ""),
                "total": invoice_dict["total"]
            }
            try:
                logs = DatabaseService.get_sequence_logs(g.owner_uid, sandbox=g.sandbox_mode)
                log = next((l for l in logs if l.get("encf") == invoice_dict.get("encf")), None)
                if log:
                    cuadratura = DGIIService.check_tolerancia_cuadratura(invoice_dict.get("items", []), invoice_dict.get("total", 0.0))
                    estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                    if pending_dgii:
                        estado_dgii = "PENDING"
                    elif res.get("mode") == "FALLBACK":
                        estado_dgii = "CONTINGENCY"
                    DatabaseService.update_sequence_log(g.owner_uid, log["id"], {
                        "estado": estado_dgii,
                        "motivo": res.get("message") or "Emisión API",
                        "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                        "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                    }, sandbox=g.sandbox_mode)
            except Exception as log_err:
                print(f"⚠️ Error al actualizar log de secuencia en API: {log_err}")
            if idempotency_key:
                DatabaseService.save_idempotency_record(g.owner_uid, idempotency_key, {
                    "response": response_body,
                    "statusCode": 200,
                    "invoiceId": invoice_id
                }, sandbox=g.sandbox_mode)
            return jsonify(response_body)
        else:
            invoice_dict["status"] = "Rechazada"
            invoice_dict["dgiiStatus"] = "REJECTED"
            invoice_dict["errorDetail"] = res.get("error", "Error desconocido de emisión")
            DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice_dict, sandbox=g.sandbox_mode)

            try:
                logs = DatabaseService.get_sequence_logs(g.owner_uid, sandbox=g.sandbox_mode)
                log = next((l for l in logs if l.get("encf") == invoice_dict.get("encf")), None)
                if log:
                    DatabaseService.update_sequence_log(g.owner_uid, log["id"], {
                        "estado": "REJECTED",
                        "motivo": invoice_dict.get("errorDetail") or "Emisión API rechazada",
                        "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                        "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                    }, sandbox=g.sandbox_mode)
            except Exception as log_err:
                print(f"⚠️ Error al actualizar log de secuencia en API (rechazo): {log_err}")
            
            response_body = {
                "success": False,
                "error": "Error al procesar el e-CF con el proveedor de facturación.",
                "details": res.get("error")
            }
            if idempotency_key:
                DatabaseService.save_idempotency_record(g.owner_uid, idempotency_key, {
                    "response": response_body,
                    "statusCode": 422,
                    "invoiceId": invoice_id
                }, sandbox=g.sandbox_mode)
            return jsonify(response_body), 422
            
    except Exception as e:
        response_body = {"success": False, "error": f"Fallo interno del servidor: {str(e)}"}
        if 'idempotency_key' in locals() and idempotency_key:
            DatabaseService.save_idempotency_record(g.owner_uid, idempotency_key, {
                "response": response_body,
                "statusCode": 500
            }, sandbox=g.sandbox_mode)
        return jsonify(response_body), 500


@api_invoices_bp.route('/invoices/<invoice_id>/status', methods=['GET'])
@require_api_key
@http_cache(timeout=30)
def get_invoice_status(invoice_id):
    """
    Consulta el estado de una factura electronica
    ---
    tags:
      - Invoices
    summary: Consulta el estado de sincronizacion y validacion DGII de una factura
    description: |
      Retorna el estado actual, NCF, track ID y estado de sincronizacion con la DGII
      para una factura electronica especifica.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura a consultar
    responses:
      200:
        description: Estado de la factura
      404:
        description: Factura no encontrada
      500:
        description: Error interno del servidor
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
            "dgii_status": invoice.get("dgiiStatus", ""),
            "error_detail": invoice.get("errorDetail")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices/<invoice_id>/cancel', methods=['POST'])
@require_api_key
def cancel_invoice(invoice_id):
    """
    Anula un e-CF emitido
    ---
    tags:
      - Invoices
    summary: Anula un comprobante fiscal electronico emitido
    description: |
      Anula un e-CF previamente emitido, enviando la solicitud de anulacion
      al proveedor de facturacion autorizado por la DGII.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura a anular
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            reason:
              type: string
              description: Motivo de la anulacion
    responses:
      200:
        description: Factura anulada exitosamente
      404:
        description: Factura no encontrada
      422:
        description: No se pudo anular la factura
      500:
        description: Error interno del servidor
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
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
        }
        
        res = EcfEmissionService.emit_cancellation(g.company, canc_dict, sandbox=g.sandbox_mode)
        
        if res.get('success'):
            before_invoice = invoice.copy()
            invoice["status"] = "Anulada"
            DatabaseService.save_invoice(g.owner_uid, invoice_id, invoice, sandbox=g.sandbox_mode)
            try:
                from app.services.accounting_service import AccountingService
                AccountingService.auto_reverse_invoice_entry(
                    g.owner_uid, before_invoice,
                    reason="Anulación API - " + (data.get('reason', '')),
                    user_id="api",
                    sandbox=g.sandbox_mode
                )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(f"Reverso contable API no generado: {exc}")
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
    Calcula los totales de impuestos de una factura
    ---
    tags:
      - Invoices
    summary: Calcula los totales fiscales exactos (ITBIS, ISC, retenciones)
    description: |
      Calcula los totales de impuestos con ISC especifico, ad valorem,
      retenciones de ISR e ITBIS y redondeo de ley segun DGII.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [items]
          properties:
            items:
              type: array
              description: Lista de articulos
              items:
                type: object
                properties:
                  price:
                    type: number
                    description: Precio unitario
                  quantity:
                    type: number
                    description: Cantidad
                  itbisRate:
                    type: number
                    description: Tasa de ITBIS
                  discountRate:
                    type: number
                    description: Tasa de descuento
                  codigoImpuesto:
                    type: string
                    description: Codigo de impuesto ISC
                  tasaImpuestoAdicional:
                    type: number
                    description: Tasa de impuesto adicional
            discount_rate:
              type: number
              description: Tasa de descuento global
            retained_isr_rate:
              type: number
              description: Tasa de retencion de ISR
            retained_itbis_rate:
              type: number
              description: Tasa de retencion de ITBIS
    responses:
      200:
        description: Calculo realizado exitosamente
      500:
        description: Error interno del servidor
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
@http_cache(timeout=30)
def get_invoices():
    """
    Lista las facturas de la empresa
    ---
    tags:
      - Invoices
    summary: Retorna la lista de facturas emitidas por la empresa
    description: |
      Retorna todas las facturas del owner autenticado. Permite filtrar
      por cotizaciones usando el query param is_quotation.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: is_quotation
        in: query
        required: false
        type: string
        description: Filtrar cotizaciones (true/false)
    responses:
      200:
        description: Lista de facturas
      500:
        description: Error interno del servidor
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
@http_cache(timeout=30)
def get_documents():
    """
    Lista todos los documentos
    ---
    tags:
      - Invoices
    summary: Retorna la lista de todos los documentos (facturas y cotizaciones)
    description: |
      Retorna todos los documentos del owner autenticado, incluyendo
      facturas emitidas, borradores y cotizaciones.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Lista de documentos
      500:
        description: Error interno del servidor
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
@http_cache(timeout=30)
def get_invoice_detail(invoice_id):
    """
    Obtiene el detalle completo de un documento
    ---
    tags:
      - Invoices
    summary: Retorna el detalle completo de un documento especifico
    description: |
      Retorna toda la informacion de una factura o cotizacion, incluyendo
      items, totales, estado y datos del cliente.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID del documento a consultar
    responses:
      200:
        description: Detalle del documento
      404:
        description: Documento no encontrado
      500:
        description: Error interno del servidor
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
    Crea un nuevo borrador de factura o cotizacion
    ---
    tags:
      - Invoices
    summary: Crea un borrador de factura o cotizacion en Firestore
    description: |
      Crea un nuevo documento (factura borrador o cotizacion) con los datos
      proporcionados. Los totales fiscales se calculan automaticamente.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            items:
              type: array
              description: Lista de articulos del documento
            is_quotation:
              type: boolean
              description: Si es true, crea una cotizacion
            ecf_type:
              type: string
              description: Tipo de comprobante fiscal
            client_rnc:
              type: string
              description: RNC del cliente
            client_name:
              type: string
              description: Nombre del cliente
            client_id:
              type: string
              description: ID del cliente
            due_date:
              type: string
              description: Fecha de vencimiento
            discount_rate:
              type: number
              description: Tasa de descuento global
            currency:
              type: string
              description: Moneda (DOP)
            payment_method:
              type: string
              description: Metodo de pago
            notes:
              type: string
              description: Notas del documento
            income_type:
              type: string
              description: Tipo de ingreso DGII
            warehouse_id:
              type: string
              description: ID del almacen
            branch_id:
              type: string
              description: ID de la sucursal
    responses:
      200:
        description: Documento creado exitosamente
      500:
        description: Error interno del servidor
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
            "date": data.get('date', datetime.now(timezone.utc).isoformat()),
            "dueDate": data.get('due_date', (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()),
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
            "createdAt": datetime.now(timezone.utc).isoformat()
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
    Actualiza un borrador o cotizacion
    ---
    tags:
      - Invoices
    summary: Actualiza un borrador de factura o cotizacion existente
    description: |
      Actualiza los datos de un documento en estado Borrador o una cotizacion.
      Los totales fiscales se recalculan automaticamente.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID del documento a actualizar
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            items:
              type: array
              description: Lista de articulos del documento
            client_rnc:
              type: string
              description: RNC del cliente
            client_name:
              type: string
              description: Nombre del cliente
            client_id:
              type: string
              description: ID del cliente
            ecf_type:
              type: string
              description: Tipo de comprobante fiscal
            due_date:
              type: string
              description: Fecha de vencimiento
            discount_rate:
              type: number
              description: Tasa de descuento global
            currency:
              type: string
              description: Moneda
            payment_method:
              type: string
              description: Metodo de pago
            payment_type:
              type: string
              description: Tipo de pago (Contado/Credito)
            notes:
              type: string
              description: Notas del documento
            income_type:
              type: string
              description: Tipo de ingreso DGII
            warehouse_id:
              type: string
              description: ID del almacen
            is_recurring:
              type: boolean
              description: Si es recurrente
            recurrence_interval:
              type: string
              description: Intervalo de recurrencia
    responses:
      200:
        description: Documento actualizado exitosamente
      404:
        description: Documento no encontrado
      422:
        description: El documento no se puede editar
      500:
        description: Error interno del servidor
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
    Elimina un borrador o cotizacion
    ---
    tags:
      - Invoices
    summary: Elimina un documento en estado Borrador o una cotizacion
    description: |
      Elimina permanentemente un documento que este en estado Borrador,
      Rechazada o sea una cotizacion. No se pueden eliminar documentos emitidos.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID del documento a eliminar
    responses:
      200:
        description: Documento eliminado exitosamente
      404:
        description: Documento no encontrado
      422:
        description: No se puede eliminar un documento emitido
      500:
        description: Error interno del servidor
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
@http_cache(timeout=60)
def get_items():
    """
    Lista el catalogo de articulos y servicios
    ---
    tags:
      - Items
    summary: Retorna el catalogo de articulos y servicios de la empresa
    description: |
      Retorna todos los articulos y servicios registrados en el catalogo
      de la empresa autenticada.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Catalogo de articulos
      500:
        description: Error interno del servidor
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
    Registra un nuevo articulo o servicio en el catalogo
    ---
    tags:
      - Items
    summary: Crea un nuevo articulo o servicio en el catalogo
    description: |
      Registra un nuevo articulo o servicio en el catalogo de la empresa
      con sus propiedades fiscales y de inventario.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [name]
          properties:
            name:
              type: string
              description: Nombre del articulo o servicio
            price:
              type: number
              description: Precio unitario
            code:
              type: string
              description: Codigo interno del articulo
            type:
              type: string
              description: Tipo (Bien o Servicio)
            unit:
              type: string
              description: Unidad de medida
            itbis_rate:
              type: number
              description: Tasa de ITBIS (default 0.18)
            min_stock:
              type: number
              description: Stock minimo
            rack_location:
              type: string
              description: Ubicacion en almacen
            total_stock:
              type: number
              description: Stock total inicial
    responses:
      200:
        description: Articulo creado exitosamente
      400:
        description: El nombre del articulo es requerido
      500:
        description: Error interno del servidor
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
    Actualiza un articulo o servicio del catalogo
    ---
    tags:
      - Items
    summary: Actualiza la informacion de un articulo o servicio existente
    description: |
      Actualiza los datos de un articulo o servicio del catalogo,
      incluyendo precio, stock, tipo y propiedades fiscales.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: item_id
        in: path
        required: true
        type: string
        description: ID del articulo a actualizar
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
              description: Nombre del articulo
            price:
              type: number
              description: Precio unitario
            code:
              type: string
              description: Codigo interno
            type:
              type: string
              description: Tipo (Bien/Servicio)
            unit:
              type: string
              description: Unidad de medida
            itbis_rate:
              type: number
              description: Tasa de ITBIS
            min_stock:
              type: number
              description: Stock minimo
            rack_location:
              type: string
              description: Ubicacion en almacen
            total_stock:
              type: number
              description: Stock total
    responses:
      200:
        description: Articulo actualizado exitosamente
      404:
        description: Articulo no encontrado
      500:
        description: Error interno del servidor
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
    Elimina un articulo del catalogo
    ---
    tags:
      - Items
    summary: Elimina un articulo del catalogo de Firestore
    description: |
      Elimina permanentemente un articulo o servicio del catalogo
      de la empresa.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: item_id
        in: path
        required: true
        type: string
        description: ID del articulo a eliminar
    responses:
      200:
        description: Articulo eliminado exitosamente
      500:
        description: Error interno del servidor
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
@http_cache(timeout=30)
def get_expenses():
    """
    Lista los gastos de la empresa
    ---
    tags:
      - Expenses (CRUD)
    summary: Retorna el historico de gastos de la empresa
    description: |
      Retorna todos los gastos registrados por la empresa autenticada,
      incluyendo informacion fiscal y de cuentas por pagar.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Lista de gastos
      500:
        description: Error interno del servidor
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
    Registra un nuevo gasto
    ---
    tags:
      - Expenses (CRUD)
    summary: Registra un nuevo gasto en el sistema
    description: |
      Registra un nuevo gasto con su informacion fiscal, categoria,
      datos del proveedor y estatus de cuentas por pagar.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [concept, amount]
          properties:
            concept:
              type: string
              description: Concepto del gasto
            amount:
              type: number
              description: Monto del gasto (mayor a cero)
            category:
              type: string
              description: Categoria del gasto
            date:
              type: string
              description: Fecha del gasto (ISO)
            rnc_emisor:
              type: string
              description: RNC del emisor/proveedor
            ncf:
              type: string
              description: NCF del comprobante
            is_minor_expense:
              type: boolean
              description: Si es un gasto menor DGII
            notes:
              type: string
              description: Notas adicionales
            is_recurring:
              type: boolean
              description: Si el gasto es recurrente
            recurrence_interval:
              type: string
              description: Intervalo de recurrencia
            itbis_amount:
              type: number
              description: Monto de ITBIS del gasto
            is_itbis_deductible:
              type: boolean
              description: Si el ITBIS es deducible
            is_deductible:
              type: boolean
              description: Si el gasto es deducible de ISR
            provider_name:
              type: string
              description: Nombre del proveedor
            ecf_type:
              type: string
              description: Tipo de comprobante fiscal
            payment_type:
              type: string
              description: Tipo de pago (Contado/Credito)
            branch_id:
              type: string
              description: ID de la sucursal
    responses:
      200:
        description: Gasto registrado exitosamente
      400:
        description: Concepto o monto invalido
      500:
        description: Error interno del servidor
    """
    try:
        data = request.json or {}
        concept = data.get('concept')
        amount = float(data.get('amount', 0.0))
        
        if not concept:
            return jsonify({"success": False, "error": "El concepto del gasto es requerido."}), 400
        
        if amount <= 0:
            return jsonify({"success": False, "error": "El monto del gasto debe ser mayor a cero."}), 400
            
        expense_id = data.get('id') or str(uuid.uuid4())
        
        payment_type = data.get('paymentType', data.get('payment_type', 'Contado'))
        cxp_status = data.get('cxpStatus', data.get('cxp_status', 'Pagado' if payment_type == 'Contado' else 'Pendiente'))
        cxp_balance = float(data.get('cxpRemainingBalance', data.get('cxp_remaining_balance', 0.0 if payment_type == 'Contado' else amount)))
        
        expense_dict = {
            "concept": concept,
            "category": data.get('category', 'Otros'),
            "amount": amount,
            "date": data.get('date', datetime.now(timezone.utc).isoformat()),
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
            "firebaseAttachmentURLs": data.get('firebase_attachment_urls', data.get('firebaseAttachmentURLs', [])),
            
            # Nuevos campos homologados
            "providerName": data.get('providerName', data.get('provider_name', '')),
            "ecfType": data.get('ecfType', data.get('ecf_type', 'E31')),
            "cne": data.get('cne', ''),
            "tipoGastoDGII": data.get('tipoGastoDGII', data.get('tipo_gasto_dgii', '02')),
            "paymentType": payment_type,
            "cxpStatus": cxp_status,
            "cxpRemainingBalance": cxp_balance,
            "approvalStatus": data.get('approvalStatus', data.get('approval_status', 'Aprobado')),
            "requestedBy": data.get('requestedBy', data.get('requested_by', 'Usuario')),
            "approvedBy": data.get('approvedBy', data.get('approved_by', 'Usuario' if data.get('approvalStatus', data.get('approval_status', 'Aprobado')) == 'Aprobado' else '')),
            "dueDate": data.get('dueDate', data.get('due_date', '')),
            "accountItems": data.get('accountItems', data.get('account_items', [])),
            "branchId": data.get('branchId', data.get('branch_id', g.get('branch_id') or 'default-sucursal-principal')),
            "projectId": data.get('projectId', data.get('project_id', g.get('project_id') or None))
        }
        
        DatabaseService.save_expense(g.owner_uid, expense_id, expense_dict, sandbox=g.sandbox_mode)
        
        try:
            from app.services.accounting_service import AccountingService
            AccountingService.auto_generate_expense_entry(g.owner_uid, expense_dict, sandbox=g.sandbox_mode)
        except Exception:
            pass
        
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
    Actualiza un gasto existente
    ---
    tags:
      - Expenses (CRUD)
    summary: Actualiza la informacion de un gasto registrado
    description: |
      Actualiza los datos de un gasto existente, incluyendo concepto,
      monto, categoria, datos del proveedor y estatus fiscal.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: expense_id
        in: path
        required: true
        type: string
        description: ID del gasto a actualizar
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            concept:
              type: string
              description: Concepto del gasto
            amount:
              type: number
              description: Monto del gasto
            category:
              type: string
              description: Categoria del gasto
            date:
              type: string
              description: Fecha del gasto (ISO)
            rnc_emisor:
              type: string
              description: RNC del emisor/proveedor
            ncf:
              type: string
              description: NCF del comprobante
            is_minor_expense:
              type: boolean
              description: Gasto menor DGII
            notes:
              type: string
              description: Notas adicionales
            is_recurring:
              type: boolean
              description: Gasto recurrente
            recurrence_interval:
              type: string
              description: Intervalo de recurrencia
            itbis_amount:
              type: number
              description: Monto de ITBIS
            is_itbis_deductible:
              type: boolean
              description: ITBIS deducible
            is_deductible:
              type: boolean
              description: Gasto deducible de ISR
            provider_name:
              type: string
              description: Nombre del proveedor
            ecf_type:
              type: string
              description: Tipo de comprobante fiscal
            payment_type:
              type: string
              description: Tipo de pago
            approval_status:
              type: string
              description: Estado de aprobacion
    responses:
      200:
        description: Gasto actualizado exitosamente
      404:
        description: Gasto no encontrado
      500:
        description: Error interno del servidor
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
            "firebaseAttachmentURLs": data.get('firebase_attachment_urls', data.get('firebaseAttachmentURLs', expense.get('firebaseAttachmentURLs'))),
            
            # Nuevos campos homologados
            "providerName": data.get('providerName', data.get('provider_name', expense.get('providerName', ''))),
            "ecfType": data.get('ecfType', data.get('ecf_type', expense.get('ecfType', 'E31'))),
            "cne": data.get('cne', expense.get('cne', '')),
            "tipoGastoDGII": data.get('tipoGastoDGII', data.get('tipo_gasto_dgii', expense.get('tipoGastoDGII', '02'))),
            "paymentType": data.get('paymentType', data.get('payment_type', expense.get('paymentType', 'Contado'))),
            "dueDate": data.get('dueDate', data.get('due_date', expense.get('dueDate', ''))),
            "cxpStatus": data.get('cxpStatus', data.get('cxp_status', expense.get('cxpStatus', 'Pagado'))),
            "cxpRemainingBalance": float(data.get('cxpRemainingBalance', data.get('cxp_remaining_balance', expense.get('cxpRemainingBalance', 0.0)))),
            "approvalStatus": data.get('approvalStatus', data.get('approval_status', expense.get('approvalStatus', 'Aprobado'))),
            "requestedBy": data.get('requestedBy', data.get('requested_by', expense.get('requestedBy', ''))),
            "approvedBy": data.get('approvedBy', data.get('approved_by', expense.get('approvedBy', ''))),
        }
        
        DatabaseService.save_expense(g.owner_uid, expense_id, expense_dict, sandbox=g.sandbox_mode)
        
        return jsonify({
            "success": True,
            "message": "Gasto actualizado exitosamente.",
            "expense": expense_dict
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/ai/receipt-ocr', methods=['POST'])
@require_api_key
def api_v1_ai_receipt_ocr():
    """
    Procesa un recibo o factura con IA (OCR)
    ---
    tags:
      - AI
    summary: Extrae datos de un recibo o factura usando GPT-4o-mini
    description: |
      Recibe una imagen de un recibo o factura y utiliza inteligencia artificial
      para extraer los datos relevantes (RNC, NCF, monto, ITBIS, etc.).
    security:
      - ApiKeyHeader: []
    parameters:
      - name: file
        in: formData
        required: true
        type: file
        description: Imagen del recibo o factura (JPEG, PNG, HEIC)
    responses:
      200:
        description: Datos extraidos del recibo
      400:
        description: No se recibio ningun archivo
    """
    file = request.files.get('file')
    if not file:
        return jsonify({"success": False, "error": "No se recibió ningún archivo"}), 400
        
    file_bytes = file.read()
    mime_type = file.mimetype or "image/jpeg"
    filename = file.filename or ""
    if filename.lower().endswith(('.heic', '.heif')):
        mime_type = "image/heic"
        
    from app.services.ai_service import AIService
    res = AIService.analyze_receipt_ocr(g.owner_uid, file_bytes, mime_type)
    return jsonify(res)


@api_invoices_bp.route('/ai/classify-expense', methods=['POST', 'GET'])
@require_api_key
def api_v1_ai_classify_expense():
    """
    Clasifica un concepto de gasto segun DGII
    ---
    tags:
      - AI
    summary: Clasifica un concepto de gasto usando IA segun los codigos DGII
    description: |
      Recibe un concepto de gasto y retorna el codigo de clasificacion
      DGII correspondiente utilizando inteligencia artificial.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: concept
        in: query
        required: true
        type: string
        description: Concepto del gasto a clasificar
    responses:
      200:
        description: Codigo DGII retornado exitosamente
      400:
        description: El concepto es requerido
    """
    concept = request.values.get('concept', '').strip()
    if not concept and request.json:
        concept = request.json.get('concept', '').strip()
    if not concept:
        return jsonify({"success": False, "error": "El concepto es requerido"}), 400
        
    from app.services.ai_service import AIService
    code = AIService.classify_dgii_expense(g.owner_uid, concept)
    return jsonify({"success": True, "code": code})


@api_invoices_bp.route('/expenses/<expense_id>', methods=['DELETE'])
@require_api_key
def delete_expense_route(expense_id):
    """
    Elimina un gasto
    ---
    tags:
      - Expenses (CRUD)
    summary: Elimina un gasto de la base de datos
    description: |
      Elimina permanentemente un gasto registrado en Firestore.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: expense_id
        in: path
        required: true
        type: string
        description: ID del gasto a eliminar
    responses:
      200:
        description: Gasto eliminado exitosamente
      500:
        description: Error interno del servidor
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
@http_cache(timeout=30)
def get_dashboard_summary():
    """
    Retorna metricas consolidadas del dashboard
    ---
    tags:
      - Dashboard
    summary: Retorna metricas financieras consolidadas calculadas por el backend
    description: |
      Retorna metricas financieras clave: total facturado, total gastos,
      total ITBIS, cuentas por cobrar, margen neto y utilidad neta.
      Incluye las facturas y gastos mas recientes.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Metricas del dashboard
      500:
        description: Error interno del servidor
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
    Envia un recibo de ingreso por email
    ---
    tags:
      - Invoices
    summary: Envia un recibo de ingreso por email al cliente
    description: |
      Envia un correo electronico con el recibo de pago al cliente,
      incluyendo datos del pago y la factura de referencia.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura de referencia
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [email]
          properties:
            email:
              type: string
              description: Direccion de email del destinatario
            paymentId:
              type: string
              description: ID del pago
            paymentDate:
              type: string
              description: Fecha del pago
            paymentMethod:
              type: string
              description: Metodo de pago
            bank:
              type: string
              description: Banco
            referenceNumber:
              type: string
              description: Numero de referencia
            amount:
              type: number
              description: Monto del pago
    responses:
      200:
        description: Recibo enviado exitosamente
      400:
        description: Email no especificado
      404:
        description: Factura no encontrada
      500:
        description: Error al enviar el correo
      503:
        description: Servidor de correo no configurado
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
        payment_date    = data.get("paymentDate", datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        payment_method  = data.get("paymentMethod", "Efectivo")
        payment_bank    = data.get("bank", "")
        payment_ref     = data.get("referenceNumber", "")
        payment_amount  = float(data.get("amount", 0.0))

        receipt_no = (payment_id[-8:].upper() if payment_id else "N/A")

        from flask import current_app as app

        if not app.config.get("SMTP_USER") or not app.config.get("SMTP_PASSWORD"):
            return jsonify({"success": False, "error": "El servidor de correo no está configurado en el backend."}), 503

        company_name    = company.get("tradeName") or company.get("companyName", get_product_name())
        brand_color     = company.get("colorMarca", "#10b981")
        logo_url        = company.get("logoUrl", "")
        logo_html       = f'<img src="{logo_url}" alt="Logo" style="max-height: 50px; margin-bottom: 15px;"><br>' if logo_url else ''

        html_body = f"""
        <html><body>
        {logo_html}
        <h2 style="color: {brand_color};">Recibo de Ingreso - {company_name}</h2>
        <p>No. Recibo: {receipt_no}</p>
        <p>Fecha de Pago: {payment_date}</p>
        <p>Factura de Referencia: {invoice.get('invoiceNumber','')}</p>
        <p>Forma de Pago: {payment_method}</p>
        <p>Monto Recibido: RD$ {payment_amount:,.2f}</p>
        </body></html>
        """

        subject = f"Recibo de Pago - Factura {invoice.get('invoiceNumber', '')} | {company_name}"

        success = Mailer.send(
            app=app._get_current_object(),
            to_email=recipient_email,
            subject=subject,
            html_body=html_body,
            from_name=company_name,
            category='receipt'
        )

        if not success:
            return jsonify({"success": False, "error": "Error al enviar el correo."}), 500

        return jsonify({"success": True, "message": f"Recibo enviado exitosamente a {recipient_email}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices/<invoice_id>/send_email', methods=['POST'])
@require_api_key
def send_invoice_email_endpoint(invoice_id):
    """
    Envia la factura electronica por email
    ---
    tags:
      - Invoices
    summary: Envia la factura electronica (XML/PDF) por email al cliente
    description: |
      Envia un correo electronico al cliente con los enlaces al PDF y XML
      de la factura electronica, ademas del XML adjunto.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura a enviar
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [email]
          properties:
            email:
              type: string
              description: Direccion de email del destinatario
    responses:
      200:
        description: Factura enviada exitosamente
      400:
        description: Email no especificado
      404:
        description: Factura no encontrada
      500:
        description: Error al enviar el correo
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

        if not app.config.get("SMTP_USER") or not app.config.get("SMTP_PASSWORD"):
            return jsonify({"success": False, "error": "Servidor de correo no configurado (SMTP)."}), 500

        xml_content = invoice.get('xmlContent') or invoice.get('xmlSignature') or ''

        pdf_url = invoice.get("firebasePDFURL", "")
        xml_url = invoice.get("firebaseXMLURL", "")

        company_name = company.get("tradeName") or company.get("companyName", "EMISOR")
        encf = invoice.get('encf', 'N/A')
        ecf_type = invoice.get('ecfType', 'Factura de Consumo Electrónica')

        brand_color = company.get("colorMarca", "#10b981")
        logo_url    = company.get("logoUrl", "")
        logo_html   = f'<img src="{logo_url}" alt="Logo" style="max-height: 60px; margin-bottom: 15px;"><br>' if logo_url else ''

        html_body = f"""
        <html><body>
        {logo_html}
        <h2 style="color: {brand_color};">{company_name}</h2>
        <p>Estimado cliente,</p>
        <p>Adjunto a este correo encontrará su comprobante electrónico ({ecf_type}) con e-NCF {encf}.</p>
        <p>Puede visualizar el PDF de su factura en el siguiente enlace: <a href="{pdf_url}">Ver Factura (PDF)</a></p>
        <p>Puede descargar el XML de su factura en el siguiente enlace: <a href="{xml_url}">Descargar Factura (XML)</a></p>
        </body></html>
        """

        subject = f"{ecf_type} No. [{encf}] - [{company_name}]"

        attachments = []
        if xml_content:
            attachments.append({
                'filename': f"{encf}.xml",
                'data': xml_content.encode('utf-8'),
                'mimetype': 'xml'
            })

        success = Mailer.send(
            app=app._get_current_object(),
            to_email=recipient_email,
            subject=subject,
            html_body=html_body,
            from_name=company_name,
            category='invoice',
            attachments=attachments
        )

        if not success:
            return jsonify({"success": False, "error": "Error al enviar el correo."}), 500

        return jsonify({"success": True, "message": f"Factura enviada exitosamente por correo a {recipient_email}."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/company/plan-consumption', methods=['GET'])
@require_api_key
@http_cache(timeout=300)
def get_company_plan_consumption():
    """
    Retorna el consumo del plan de la empresa
    ---
    tags:
      - Company
    summary: Retorna informacion del plan activo y consumo de comprobantes
    description: |
      Retorna el nombre del plan, limite de documentos, documentos utilizados
      en el ciclo actual y porcentaje de consumo del plan contratado.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Informacion de consumo del plan
      500:
        description: Error interno del servidor
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


@api_invoices_bp.route('/invoices/<invoice_id>/payments', methods=['POST'])
@require_api_key
def register_payment(invoice_id):
    """
    Registra un pago a una factura
    ---
    tags:
      - Invoices
    summary: Registra un pago aplicado a una factura
    description: |
      Registra un pago asociado a una factura especifica, actualizando
      el balance pendiente de la misma.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura a la que se aplica el pago
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [amount]
          properties:
            amount:
              type: number
              description: Monto del pago (mayor a cero)
            paymentMethod:
              type: string
              description: Metodo de pago
            bank:
              type: string
              description: Banco
            referenceNumber:
              type: string
              description: Numero de referencia
            bankAccountId:
              type: string
              description: ID de la cuenta bancaria
    responses:
      200:
        description: Pago registrado exitosamente
      400:
        description: Monto invalido
      500:
        description: Error interno del servidor
    """
    try:
        data = request.get_json(force=True) or {}
        amount = float(data.get("amount", 0))
        if amount <= 0:
            return jsonify({"success": False, "error": "El monto debe ser mayor a cero."}), 400
        payment_dict = {
            "amount": amount,
            "paymentMethod": data.get("paymentMethod", "Transferencia"),
            "bank": data.get("bank", "Banco"),
            "referenceNumber": data.get("referenceNumber", ""),
            "bankAccountId": data.get("bankAccountId", ""),
            "paymentDate": datetime.now(timezone.utc).isoformat(),
            "registeredBy": g.user_email if hasattr(g, 'user_email') else "API",
        }
        from app.services.db_service import DatabaseService
        DatabaseService.register_invoice_payment(g.owner_uid, invoice_id, payment_dict, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "message": "Pago registrado exitosamente."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_invoices_bp.route('/invoices/<invoice_id>/credit-notes', methods=['POST'])
@require_api_key
def create_credit_note(invoice_id):
    """
    Crea una nota de credito asociada a una factura
    ---
    tags:
      - Invoices
    summary: Crea una nota de credito (e-CF E34) vinculada a una factura original
    description: |
      Crea una nota de credito electronica asociada a una factura existente.
      La nota de credito se genera con el tipo E34 y referencia de modificacion
      a la factura original.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura original
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [netPayable]
          properties:
            netPayable:
              type: number
              description: Monto de la nota de credito (mayor a cero)
            total:
              type: number
              description: Monto total alternativo
            items:
              type: array
              description: Items de la nota de credito
            reason:
              type: string
              description: Motivo de la modificacion
            notes:
              type: string
              description: Notas adicionales
    responses:
      200:
        description: Nota de credito creada exitosamente
      400:
        description: Monto invalido
      404:
        description: Factura original no encontrada
      500:
        description: Error interno del servidor
    """
    try:
        from app.services.db_service import DatabaseService
        original = DatabaseService.get_invoice(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
        if not original:
            return jsonify({"success": False, "error": "Factura original no encontrada."}), 404
        data = request.get_json(force=True) or {}
        note_amount = float(data.get("netPayable", 0) or data.get("total", 0))
        if note_amount <= 0:
            return jsonify({"success": False, "error": "El monto de la nota de crédito debe ser mayor a cero."}), 400
        note_id = str(uuid.uuid4())
        note_dict = {
            "invoiceNumber": f"NC-{original.get('invoiceNumber', invoice_id)}",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "dueDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "clientId": original.get("clientId", ""),
            "clientName": original.get("clientName", ""),
            "clientRNC": original.get("clientRNC", ""),
            "status": "Borrador",
            "ecfType": "Nota de Crédito (E34)",
            "netPayable": note_amount,
            "total": note_amount,
            "subtotal": note_amount,
            "totalITBIS": 0,
            "isQuotation": False,
            "paymentType": "Crédito",
            "currency": original.get("currency", "DOP"),
            "items": data.get("items", original.get("items", [])),
            "totalPaid": 0,
            "remainingBalance": note_amount,
            "informationReference": {
                "modificationCode": 3,
                "ncfModified": original.get("encf", ""),
                "ncfModifiedDate": original.get("date", "")[:10],
                "reasonForModification": data.get("reason", "Corrección de importes"),
            },
            "notes": data.get("notes", ""),
            "branchId": original.get("branchId", "default-sucursal-principal"),
        }
        DatabaseService.save_invoice(g.owner_uid, note_id, note_dict, sandbox=g.sandbox_mode)
        return jsonify({"success": True, "creditNoteId": note_id, "message": "Nota de crédito creada."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
