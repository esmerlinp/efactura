from flask import Blueprint, request, g, jsonify
from app.api.auth import require_api_key
from app.services.supplier_invoice_service import SupplierInvoiceService

api_supplier_invoices_bp = Blueprint('api_supplier_invoices', __name__)


@api_supplier_invoices_bp.route('/supplier-invoices', methods=['GET'])
@require_api_key
def list_supplier_invoices():
    invoices = SupplierInvoiceService.get_all(g.owner_uid, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "data": invoices}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>', methods=['GET'])
@require_api_key
def get_supplier_invoice(invoice_id):
    invoice = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    if not invoice:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    return jsonify({"success": True, "data": invoice}), 200


@api_supplier_invoices_bp.route('/supplier-invoices', methods=['POST'])
@require_api_key
def create_supplier_invoice():
    data = request.json or {}
    invoice = SupplierInvoiceService.create(g.owner_uid, data, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "data": invoice}), 201


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>', methods=['PUT'])
@require_api_key
def update_supplier_invoice(invoice_id):
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
    existing = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    SupplierInvoiceService.delete(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "message": "Factura proveedor eliminada."}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/payments', methods=['GET'])
@require_api_key
def list_payments(invoice_id):
    existing = SupplierInvoiceService.get(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    if not existing:
        return jsonify({"success": False, "error": "Factura proveedor no encontrada."}), 404
    payments = SupplierInvoiceService.get_payments(g.owner_uid, invoice_id, sandbox=g.sandbox_mode)
    return jsonify({"success": True, "data": payments}), 200


@api_supplier_invoices_bp.route('/supplier-invoices/<invoice_id>/payments', methods=['POST'])
@require_api_key
def register_payment(invoice_id):
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
