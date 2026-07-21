from flask import Blueprint, request, g, jsonify
from app.api.auth import require_api_key
from app.services.supplier_invoice_service import SupplierInvoiceService

api_supplier_invoices_bp = Blueprint('api_supplier_invoices', __name__)


@api_supplier_invoices_bp.route('/supplier-invoices', methods=['GET'])
@require_api_key
def list_supplier_invoices():
    """
    Listar todas las facturas de proveedor
    ---
    tags:
      - Supplier Invoices
    summary: Obtiene todas las facturas de proveedor del usuario autenticado
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Lista de facturas de proveedor
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: array
              items:
                type: object
    """
    invoices = SupplierInvoiceService.get_all(g.owner_uid, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "data": invoices}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>', methods=['GET'])
@require_api_key
def get_supplier_invoice(invoice_id):
    """
    Obtener una factura de proveedor por ID
    ---
    tags:
      - Supplier Invoices
    summary: Obtiene una factura de proveedor específica por su ID
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura de proveedor
    responses:
      200:
        description: Factura de proveedor encontrada
      404:
        description: Factura de proveedor no encontrada
    """
    invoice = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    if not invoice:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    return jsonify({"success": True, "data": invoice}), 200


@api_supplier_invoices_bp.route('/supplier-invoices', methods=['POST'])
@require_api_key
def create_supplier_invoice():
    """
    Crear una nueva factura de proveedor
    ---
    tags:
      - Supplier Invoices
    summary: Registra una nueva factura de proveedor
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            supplierName:
              type: string
              description: Nombre del proveedor
            supplierRNC:
              type: string
              description: RNC/Cédula del proveedor
            supplierInvoiceNumber:
              type: string
              description: Número de factura del proveedor (NCF)
            ncf:
              type: string
              description: NCF DGII (opcional, válido si longitud >= 8)
            invoiceDate:
              type: string
              format: date
              description: Fecha de la factura (YYYY-MM-DD)
            dueDate:
              type: string
              format: date
              description: Fecha de vencimiento (YYYY-MM-DD)
            total:
              type: number
              description: Monto total de la factura
            subtotal:
              type: number
              description: Subtotal antes de impuestos
            itbis:
              type: number
              description: Monto de ITBIS
            currency:
              type: string
              description: Moneda (DOP por defecto)
              default: DOP
            exchangeRate:
              type: number
              description: Tasa de cambio
              default: 1.0
            paymentMethod:
              type: string
              description: Método de pago
            paymentTerms:
              type: string
              description: Términos de pago (contado/crédito)
              default: contado
            supplierType:
              type: string
              description: Tipo de proveedor (formal/informal)
              default: formal
            ecfType:
              type: string
              description: Tipo de comprobante fiscal (E31, etc.)
              default: E31
            cne:
              type: string
              description: CNE
            notes:
              type: string
              description: Notas adicionales
            comment:
              type: string
              description: Comentario interno
            items:
              type: array
              items:
                type: object
              description: Líneas de la factura
            poId:
              type: string
              description: ID de la orden de compra asociada
            poNumber:
              type: string
              description: Número de orden de compra
            branchId:
              type: string
              description: ID de la sucursal
            projectId:
              type: string
              description: ID del proyecto asociado
            tipoGastoDGII:
              type: string
              description: Tipo de gasto para DGII
              default: "02"
            retainedISR:
              type: number
              description: ISR retenido
              default: 0.0
            retainedITBIS:
              type: number
              description: ITBIS retenido
              default: 0.0
            bankAccountId:
              type: string
              description: ID de la cuenta bancaria
    responses:
      201:
        description: Factura de proveedor creada exitosamente
    """
    data = request.json or {}
    invoice = SupplierInvoiceService.create(g.owner_uid, data, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "data": invoice}), 201


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>', methods=['PUT'])
@require_api_key
def update_supplier_invoice(invoice_id):
    """
    Actualizar una factura de proveedor existente
    ---
    tags:
      - Supplier Invoices
    summary: Actualiza campos no fiscales de una factura de proveedor
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura de proveedor
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            supplierName:
              type: string
              description: Nombre del proveedor
            supplierRNC:
              type: string
              description: RNC/Cédula del proveedor
            supplierInvoiceNumber:
              type: string
              description: Número de factura del proveedor (NCF)
            ncf:
              type: string
              description: NCF DGII
            invoiceDate:
              type: string
              format: date
              description: Fecha de la factura (YYYY-MM-DD)
            dueDate:
              type: string
              format: date
              description: Fecha de vencimiento (YYYY-MM-DD)
            total:
              type: number
              description: Monto total de la factura
            subtotal:
              type: number
              description: Subtotal antes de impuestos
            itbis:
              type: number
              description: Monto de ITBIS
            currency:
              type: string
              description: Moneda
            exchangeRate:
              type: number
              description: Tasa de cambio
            paymentMethod:
              type: string
              description: Método de pago
            paymentTerms:
              type: string
              description: Términos de pago
            supplierType:
              type: string
              description: Tipo de proveedor
            ecfType:
              type: string
              description: Tipo de comprobante fiscal
            cne:
              type: string
              description: CNE
            notes:
              type: string
              description: Notas adicionales
            comment:
              type: string
              description: Comentario interno
            items:
              type: array
              items:
                type: object
              description: Líneas de la factura
            poId:
              type: string
              description: ID de la orden de compra
            poNumber:
              type: string
              description: Número de orden de compra
            branchId:
              type: string
              description: ID de la sucursal
            projectId:
              type: string
              description: ID del proyecto
            tipoGastoDGII:
              type: string
              description: Tipo de gasto para DGII
            retainedISR:
              type: number
              description: ISR retenido
            retainedITBIS:
              type: number
              description: ITBIS retenido
            bankAccountId:
              type: string
              description: ID de la cuenta bancaria
            cxpStatus:
              type: string
              description: Estado CxP (Pendiente/Abonado/Pagado/Vencido)
            cxpRemainingBalance:
              type: number
              description: Saldo pendiente CxP
            status:
              type: string
              description: Estado de la factura
    responses:
      200:
        description: Factura de proveedor actualizada exitosamente
      404:
        description: Factura de proveedor no encontrada
      500:
        description: Error al actualizar factura de proveedor
    """
    existing = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    data = request.json or {}
    ok = SupplierInvoiceService.update(g.owner_uid, invoice_id, data, sandbox=g.sandbox_mode)
    if not ok:
        return jsonify({"success": False, "error": "Error al actualizar factura proveedor."}), 500
    updated = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "data": updated}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>', methods=['DELETE'])
@require_api_key
def delete_supplier_invoice(invoice_id):
    """
    Eliminar una factura de proveedor
    ---
    tags:
      - Supplier Invoices
    summary: Elimina una factura de proveedor y sus archivos adjuntos
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura de proveedor
    responses:
      200:
        description: Factura de proveedor eliminada exitosamente
      404:
        description: Factura de proveedor no encontrada
    """
    existing = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    SupplierInvoiceService.delete(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "message": "Factura proveedor eliminada."}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/payments', methods=['GET'])
@require_api_key
def list_payments(invoice_id):
    """
    Listar pagos de una factura de proveedor
    ---
    tags:
      - Supplier Invoices
    summary: Obtiene todos los pagos registrados para una factura de proveedor
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura de proveedor
    responses:
      200:
        description: Lista de pagos de la factura
      404:
        description: Factura de proveedor no encontrada
    """
    existing = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    payments = SupplierInvoiceService.get_payments(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "data": payments}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/payments', methods=['POST'])
@require_api_key
def register_payment(invoice_id):
    """
    Registrar un pago a una factura de proveedor
    ---
    tags:
      - Supplier Invoices
    summary: Registra un pago parcial o total a una factura de proveedor
    security:
      - ApiKeyHeader: []
    parameters:
      - name: invoice_id
        in: path
        required: true
        type: string
        description: ID de la factura de proveedor
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            amount:
              type: number
              description: Monto del pago (debe ser mayor a cero)
            registeredBy:
              type: string
              description: Usuario o sistema que registra el pago
              default: API
            method:
              type: string
              description: Método de pago
            reference:
              type: string
              description: Referencia del pago
            bankAccountId:
              type: string
              description: ID de la cuenta bancaria para debitar el pago
    responses:
      200:
        description: Pago registrado exitosamente
      400:
        description: Error de validación (monto inválido o excede saldo)
      404:
        description: Factura de proveedor no encontrada
    """
    existing = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    body = request.json or {}
    amount = float(body.get("amount", 0))
    if amount <= 0:
        return jsonify({"success": False, "error": "El monto del pago debe ser mayor a cero."}), 400
    ok, msg = SupplierInvoiceService.save_payment(
        g.owner_uid, invoice_id, amount,
        registered_by=body.get("registeredBy", "API"),
        sandbox=g.sandbox_mode,
        payment_method=body.get("method", ""),
        payment_reference=body.get("reference", ""),
        bank_account_id=body.get("bankAccountId", ""),
    )
    if not ok:
        return jsonify({"success": False, "error": msg}), 400
    payments = SupplierInvoiceService.get_payments(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "message": msg, "data": payments}), 200
