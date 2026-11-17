from flask import Blueprint, request, g, jsonify
from app.api.auth import require_api_key, require_api_module, gate_api_blueprint_module
from app.services.supplier_invoice_service import SupplierInvoiceService
from app.services.audit_service import AuditService, ACTION_UPDATE, ACTION_DELETE, MODULE_CXP
from app.utils.decorators import check_sod, record_sod_action

api_supplier_invoices_bp = Blueprint('api_supplier_invoices', __name__)
gate_api_blueprint_module(api_supplier_invoices_bp, 'cxp_compras')


def _company_kw():
    return {"company_id": g.company_id, "owner_uid": g.owner_uid, "sandbox": g.sandbox_mode}


def _api_user_uid():
    company = getattr(g, "company", {}) or {}
    return str(company.get("userUID") or company.get("uid") or company.get("id") or "api")


def _api_user_label():
    return str(getattr(g, "user_name", "") or "API")


def _conflict_status(message):
    """Mapea errores de negocio a 409 sin filtrar detalles internos."""
    text = (message or "").lower()
    conflict_markers = (
        "no se puede", "ya está", "ya fue", "en proceso", "período fiscal",
        "periodo fiscal", "anulada", "emitida", "contabilizada", "bloqueada",
    )
    return 409 if any(marker in text for marker in conflict_markers) else 400


# Campos que el API puede escribir al crear/actualizar una factura de proveedor.
# Los campos de CxP y estado fiscal se protegen explícitamente.
_CREATE_ALLOWED_FIELDS = {
    "supplierName", "supplierRnc", "supplierCedula", "supplierType",
    "supplierId", "supplierInvoiceNumber", "ncf", "date", "dueDate",
    "total", "subtotal", "itbis", "currency", "exchangeRate",
    "paymentMethod", "paymentTerms", "ecfType", "cne", "notes", "comentario",
    "items", "poId", "poNumber", "branchId", "projectId", "tipoGastoDGII",
    "retainedISR", "retainedITBIS", "bankAccountId",
}

_PROTECTED_FIELDS = {
    "cxpStatus", "cxpRemainingBalance", "status", "id", "ownerUID",
    "createdAt", "updatedAt", "encf", "xmlContent", "isSyncedWithDGII",
    "dgiiStatus", "dgiiError", "netPayable", "retainedISRAmount",
    "retainedITBISAmount", "accountingStatus", "accountingError",
    "voidStatus", "voidReason", "voidedAt", "voidedBy", "voidRequestedBy",
    "correctionStatus", "correctionReason", "correctionRequestedBy",
}

_FIELD_ALIASES = {
    "invoiceDate": "date",
    "comment": "comentario",
    "supplierRNC": "supplierRnc",
}


def _sanitize_payload(data, allowed_fields):
    """Normaliza alias y descarta campos no permitidos. Devuelve (cleaned, forbidden)."""
    normalized = {}
    for key, value in (data or {}).items():
        normalized[_FIELD_ALIASES.get(key, key)] = value
    forbidden = sorted(_PROTECTED_FIELDS & set(normalized.keys()))
    cleaned = {k: v for k, v in normalized.items() if k in allowed_fields}
    return cleaned, forbidden


def _check_ncf_duplicates(kw, supplier_invoice_number="", ncf="", exclude_id=None):
    if supplier_invoice_number and not SupplierInvoiceService._check_ncf_unique(ncf=supplier_invoice_number, exclude_id=exclude_id, **kw):
        return supplier_invoice_number
    if ncf and not SupplierInvoiceService._check_ncf_unique(ncf=ncf, exclude_id=exclude_id, **kw):
        return ncf
    return None


@api_supplier_invoices_bp.route('/supplier-invoices', methods=['GET'])
@require_api_module('cxp_compras')
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
    kw = _company_kw()
    invoices = SupplierInvoiceService.get_all(**kw)
    return jsonify({"success": True, "data": invoices}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>', methods=['GET'])
@require_api_module('cxp_compras')
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
    kw = _company_kw()
    invoice = SupplierInvoiceService.get(invoice_id=invoice_id, **kw)
    if not invoice:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    return jsonify({"success": True, "data": invoice}), 200


@api_supplier_invoices_bp.route('/supplier-invoices', methods=['POST'])
@require_api_module('cxp_compras', 'canManagePurchaseCXP')
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
    kw = _company_kw()
    data = request.json or {}
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "El cuerpo debe ser un objeto JSON."}), 400
    cleaned, forbidden = _sanitize_payload(data, _CREATE_ALLOWED_FIELDS)
    if forbidden:
        return jsonify({"success": False, "error": f"Campos protegidos no permitidos: {', '.join(forbidden)}"}), 400

    dup = _check_ncf_duplicates(kw, cleaned.get("supplierInvoiceNumber", ""), cleaned.get("ncf", ""))
    if dup:
        return jsonify({"success": False, "error": "El NCF ya está registrado en otra factura."}), 409

    try:
        invoice = SupplierInvoiceService.create(data=cleaned, **kw)
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception:
        return jsonify({"success": False, "error": "No se pudo crear la factura proveedor."}), 500
    record_sod_action(
        g.owner_uid, _api_user_uid(), _api_user_label(),
        "canManagePurchaseCXP", invoice.get("id", ""), "supplier_invoice",
        company_id=g.company_id,
    )
    return jsonify({"success": True, "data": invoice}), 201


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>', methods=['PUT'])
@require_api_module('cxp_compras', 'canManagePurchaseCXP')
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
    kw = _company_kw()
    existing = SupplierInvoiceService.get(invoice_id=invoice_id, **kw)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    data = request.json or {}
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "El cuerpo debe ser un objeto JSON."}), 400
    cleaned, forbidden = _sanitize_payload(data, _CREATE_ALLOWED_FIELDS)
    if forbidden:
        return jsonify({"success": False, "error": f"Campos protegidos no permitidos: {', '.join(forbidden)}"}), 400

    if SupplierInvoiceService.is_voided(existing):
        return jsonify({"success": False, "error": "No se puede editar una factura anulada."}), 409
    if SupplierInvoiceService.is_emitted(existing):
        return jsonify({"success": False, "error": "No se puede editar una factura emitida a la DGII."}), 409
    try:
        if SupplierInvoiceService.has_accounting_entry(invoice_id=invoice_id, **kw):
            return jsonify({"success": False, "error": "No se puede editar una factura contabilizada. Use el procedimiento de corrección."}), 409
        if SupplierInvoiceService.has_payments(invoice_id=invoice_id, **kw):
            return jsonify({"success": False, "error": "No se puede editar una factura con pagos registrados."}), 409
    except Exception:
        return jsonify({"success": False, "error": "No se pudo verificar la factura; operación bloqueada."}), 409

    if "date" in cleaned:
        try:
            SupplierInvoiceService.validate_period(kw.get("company_id"), cleaned.get("date"))
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400

    dup = _check_ncf_duplicates(kw, cleaned.get("supplierInvoiceNumber", ""), cleaned.get("ncf", ""), exclude_id=invoice_id)
    if dup:
        return jsonify({"success": False, "error": "El NCF ya está registrado en otra factura."}), 409

    ok = SupplierInvoiceService.update(invoice_id=invoice_id, data=cleaned, **kw)
    if not ok:
        return jsonify({"success": False, "error": "Error al actualizar factura proveedor."}), 500
    updated = SupplierInvoiceService.get(invoice_id=invoice_id, **kw)
    return jsonify({"success": True, "data": updated}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>', methods=['DELETE'])
@require_api_module('cxp_compras', 'canManagePurchaseCXP')
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
    kw = _company_kw()
    existing = SupplierInvoiceService.get(invoice_id=invoice_id, **kw)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    ok, msg = SupplierInvoiceService.delete(invoice_id=invoice_id, **kw)
    if not ok:
        return jsonify({"success": False, "error": msg}), _conflict_status(msg)
    AuditService.log(
        owner_uid=g.owner_uid, action=ACTION_DELETE, module=MODULE_CXP,
        entity_id=invoice_id,
        entity_label=f"Factura proveedor eliminada vía API: {existing.get('invoiceNumber', invoice_id)}",
        performed_by_name=_api_user_label(), performed_by_email=_api_user_label(),
        before=existing, sandbox=g.sandbox_mode, company_id=g.company_id,
    )
    return jsonify({"success": True, "message": msg}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/void', methods=['POST'])
@require_api_module('cxp_compras', 'canVoidSupplierInvoice')
def void_supplier_invoice(invoice_id):
    """
    Anular una factura de proveedor
    ---
    tags:
      - Supplier Invoices
    summary: Anula una factura de proveedor preservando su trazabilidad
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
        required: false
        schema:
          type: object
          properties:
            reason:
              type: string
              description: Motivo de la anulación
            voidedBy:
              type: string
              description: Usuario o sistema que anula
    responses:
      200:
        description: Factura de proveedor anulada exitosamente
      400:
        description: Error de validación
      404:
        description: Factura de proveedor no encontrada
    """
    kw = _company_kw()
    existing = SupplierInvoiceService.get(invoice_id=invoice_id, **kw)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    body = request.json or {}
    reason = str(body.get("reason", "") or "").strip()
    if not reason:
        return jsonify({"success": False, "error": "Debe indicar el motivo de la anulación."}), 400
    user_uid = _api_user_uid()
    sod_ok, sod_msg = check_sod(
        g.owner_uid, user_uid, "canVoidSupplierInvoice",
        invoice_id, "supplier_invoice", company_id=g.company_id,
    )
    if not sod_ok:
        return jsonify({"success": False, "error": sod_msg}), 403
    ok, msg = SupplierInvoiceService.void(
        invoice_id=invoice_id, reason=reason,
        voided_by=body.get("voidedBy", _api_user_label()), **kw,
    )
    if not ok:
        return jsonify({"success": False, "error": msg}), _conflict_status(msg)
    record_sod_action(
        g.owner_uid, user_uid, _api_user_label(),
        "canVoidSupplierInvoice", invoice_id, "supplier_invoice",
        company_id=g.company_id,
    )
    AuditService.log(
        owner_uid=g.owner_uid, action=ACTION_UPDATE, module=MODULE_CXP,
        entity_id=invoice_id,
        entity_label=f"Factura proveedor anulada vía API: {reason}",
        performed_by_name=_api_user_label(), performed_by_email=_api_user_label(),
        before=existing, sandbox=g.sandbox_mode, company_id=g.company_id,
    )
    return jsonify({"success": True, "message": msg}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/payments', methods=['GET'])
@require_api_module('cxp_compras')
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
    kw = _company_kw()
    existing = SupplierInvoiceService.get(invoice_id=invoice_id, **kw)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    payments = SupplierInvoiceService.get_payments(invoice_id=invoice_id, **kw)
    return jsonify({"success": True, "data": payments}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/payments', methods=['POST'])
@require_api_module('cxp_compras', 'canManagePurchaseCXP')
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
    kw = _company_kw()
    existing = SupplierInvoiceService.get(invoice_id=invoice_id, **kw)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    body = request.json or {}
    amount = float(body.get("amount", 0))
    if amount <= 0:
        return jsonify({"success": False, "error": "El monto del pago debe ser mayor a cero."}), 400
    ok, msg = SupplierInvoiceService.save_payment(
        invoice_id=invoice_id, payment_amount=amount,
        registered_by=body.get("registeredBy", "API"),
        payment_method=body.get("method", ""),
        payment_reference=body.get("reference", ""),
        bank_account_id=body.get("bankAccountId", ""),
        requested_by_uid=_api_user_uid(),
        **kw,
    )
    if not ok:
        return jsonify({"success": False, "error": msg}), _conflict_status(msg)
    record_sod_action(
        g.owner_uid, _api_user_uid(), _api_user_label(),
        "canManagePurchaseCXP", invoice_id, "supplier_invoice",
        company_id=g.company_id,
    )
    payments = SupplierInvoiceService.get_payments(invoice_id=invoice_id, **kw)
    return jsonify({"success": True, "message": msg, "data": payments}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/payments/<payment_id>/approve', methods=['POST'])
@require_api_module('cxp_compras', 'canApprovePayments')
def approve_payment(invoice_id, payment_id):
    """Aprueba un pago pendiente de una factura de proveedor (con SoD)."""
    kw = _company_kw()
    user_uid = _api_user_uid()
    body = request.json or {}
    notes = str(body.get("notes", "") or "").strip()
    is_owner = str(getattr(g, "company", {}).get("role", "")) == "owner"
    payments = SupplierInvoiceService.get_payments(invoice_id=invoice_id, **kw)
    payment = next((p for p in payments if p.get("id") == payment_id), None)
    if not payment:
        return jsonify({"success": False, "error": "Pago no encontrado."}), 404
    if payment.get("requestedBy") and payment.get("requestedBy") == user_uid:
        if not (is_owner and notes):
            return jsonify({"success": False, "error": "Conflicto de segregación de funciones: no puedes aprobar un pago que registraste. El propietario debe justificar la auto-aprobación."}), 403
    ok, msg = SupplierInvoiceService.approve_payment(
        invoice_id=invoice_id, payment_id=payment_id,
        approved_by=body.get("approvedBy", _api_user_label()),
        approved_by_uid=user_uid,
        notes=notes,
        **kw,
    )
    if not ok:
        return jsonify({"success": False, "error": msg}), _conflict_status(msg)
    return jsonify({"success": True, "message": msg}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/payments/<payment_id>/reject', methods=['POST'])
@require_api_module('cxp_compras', 'canApprovePayments')
def reject_payment(invoice_id, payment_id):
    """Rechaza un pago pendiente de una factura de proveedor."""
    kw = _company_kw()
    body = request.json or {}
    ok, msg = SupplierInvoiceService.reject_payment(
        invoice_id=invoice_id, payment_id=payment_id,
        rejected_by=body.get("rejectedBy", _api_user_label()),
        rejected_by_uid=_api_user_uid(),
        notes=body.get("notes", ""),
        **kw,
    )
    if not ok:
        return jsonify({"success": False, "error": msg}), _conflict_status(msg)
    return jsonify({"success": True, "message": msg}), 200
