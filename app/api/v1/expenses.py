# app/api/v1/expenses.py
import json
from flask import Blueprint, request, g, jsonify
from app.api.auth import require_api_key, require_api_module, gate_api_blueprint_module
from app.services.db_service import DatabaseService

api_expenses_bp = Blueprint('api_expenses', __name__)
gate_api_blueprint_module(api_expenses_bp, 'gastos')


@api_expenses_bp.route('/expenses/payments', methods=['GET'])
@require_api_module('gastos')
def list_payments():
    """
    Listar pagos formales
    ---
    tags:
      - Expenses
    summary: Listar gastos y pagos formales
    description: Retorna los gastos/pagos formales (excluye E43 y recurrentes).
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Lista de pagos
        schema:
          type: object
          properties:
            success:
              type: boolean
            data:
              type: array
              items:
                type: object
            count:
              type: integer
    """
    owner_uid = g.owner_uid
    sandbox = g.sandbox_mode
    expenses = DatabaseService.get_expenses(owner_uid, company_id=g.company_id, sandbox=sandbox)
    filtered = [e for e in expenses if e.get('ecfType') != 'E43' and not e.get('isRecurring')]
    return jsonify({'success': True, 'data': filtered, 'count': len(filtered)})


@api_expenses_bp.route('/expenses/minor', methods=['GET'])
@require_api_module('gastos')
def list_minor():
    """
    Listar gastos menores
    ---
    tags:
      - Expenses
    summary: Listar gastos menores (E43)
    description: Retorna los gastos menores (tipo E43).
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Lista de gastos menores
    """
    owner_uid = g.owner_uid
    sandbox = g.sandbox_mode
    expenses = DatabaseService.get_expenses(owner_uid, company_id=g.company_id, sandbox=sandbox)
    filtered = [e for e in expenses if e.get('ecfType') == 'E43']
    return jsonify({'success': True, 'data': filtered, 'count': len(filtered)})


@api_expenses_bp.route('/expenses/recurring', methods=['GET'])
@require_api_module('gastos')
def list_recurring():
    """
    Listar gastos recurrentes
    ---
    tags:
      - Expenses
    summary: Listar pagos recurrentes
    description: Retorna los gastos marcados como recurrentes.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Lista de gastos recurrentes
    """
    owner_uid = g.owner_uid
    sandbox = g.sandbox_mode
    expenses = DatabaseService.get_expenses(owner_uid, company_id=g.company_id, sandbox=sandbox)
    filtered = [e for e in expenses if e.get('isRecurring')]
    return jsonify({'success': True, 'data': filtered, 'count': len(filtered)})


@api_expenses_bp.route('/expenses/payments/classify', methods=['GET'])
@require_api_module('gastos')
def classify_payment():
    """
    Clasificar concepto de pago con IA
    ---
    tags:
      - Expenses
    summary: Clasificar concepto de pago (IA)
    description: Usa IA para clasificar un concepto de pago según las categorías DGII.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: concept
        in: query
        required: true
        type: string
        description: Concepto del pago a clasificar
        example: "Compra de materiales de oficina"
    responses:
      200:
        description: Clasificación del concepto
        schema:
          type: object
          properties:
            success:
              type: boolean
            code:
              type: string
            category:
              type: string
      400:
        description: Parámetro concepto requerido
    """
    concept = request.args.get('concept', '')
    if not concept:
        return jsonify({'success': False, 'error': 'Parámetro concepto requerido'}), 400
    # Delegate to AI service if available
    try:
        from app.services.ai_classifier import classify_expense
        result = classify_expense(concept)
        return jsonify({'success': True, 'code': result.get('code'), 'category': result.get('category')})
    except ImportError:
        return jsonify({'success': True, 'code': '02', 'category': 'Otros Gastos'})


@api_expenses_bp.route('/expenses/minor/classify', methods=['GET'])
@require_api_module('gastos')
def classify_minor():
    """
    Clasificar concepto de gasto menor con IA
    ---
    tags:
      - Expenses
    summary: Clasificar gasto menor (IA)
    description: Usa IA para clasificar un concepto de gasto menor según las categorías DGII.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: concept
        in: query
        required: true
        type: string
        description: Concepto del gasto menor a clasificar
        example: "Almuerzo de trabajo"
    responses:
      200:
        description: Clasificación del concepto
      400:
        description: Parámetro concepto requerido
    """
    concept = request.args.get('concept', '')
    if not concept:
        return jsonify({'success': False, 'error': 'Parámetro concepto requerido'}), 400
    try:
        from app.services.ai_classifier import classify_expense
        result = classify_expense(concept)
        return jsonify({'success': True, 'code': result.get('code'), 'category': result.get('category')})
    except ImportError:
        return jsonify({'success': True, 'code': '06', 'category': 'Comida y Restaurantes'})


def _api_user_uid():
    company = getattr(g, "company", {}) or {}
    return str(company.get("userUID") or company.get("uid") or company.get("id") or "api")


def _api_user_label():
    return str(getattr(g, "user_name", "") or "API")


def _conflict_status(message):
    text = (message or "").lower()
    conflict_markers = (
        "no se puede", "ya está", "ya fue", "en proceso", "período fiscal",
        "periodo fiscal", "anulada", "emitida", "contabilizada", "bloqueada",
        "excede", "pendiente",
    )
    return 409 if any(m in text for m in conflict_markers) else 400


@api_expenses_bp.route('/expenses/<expense_id>/payments/<payment_id>/approve', methods=['POST'])
@require_api_module('gastos', 'canApprovePayments')
def approve_payment(expense_id, payment_id):
    """Aprueba un pago pendiente de un gasto (con SoD)."""
    owner_uid = g.owner_uid
    sandbox = g.sandbox_mode
    company_id = g.company_id
    user_uid = _api_user_uid()
    body = request.json or {}
    notes = str(body.get("notes", "") or "").strip()
    payments = DatabaseService.get_cxp_payments(owner_uid, expense_id, sandbox=sandbox, company_id=company_id)
    payment = next((p for p in payments if p.get("id") == payment_id), None)
    if not payment:
        return jsonify({"success": False, "error": "Pago no encontrado."}), 404
    ok, msg = DatabaseService.approve_cxp_payment(
        owner_uid, expense_id, payment_id,
        approved_by=body.get("approvedBy", _api_user_label()),
        approved_by_uid=user_uid, notes=notes,
        company_id=company_id, sandbox=sandbox,
    )
    if not ok:
        return jsonify({"success": False, "error": msg}), _conflict_status(msg)
    return jsonify({"success": True, "message": msg}), 200


@api_expenses_bp.route('/expenses/<expense_id>/payments/<payment_id>/reject', methods=['POST'])
@require_api_module('gastos', 'canApprovePayments')
def reject_payment(expense_id, payment_id):
    """Rechaza un pago pendiente de un gasto."""
    owner_uid = g.owner_uid
    sandbox = g.sandbox_mode
    company_id = g.company_id
    body = request.json or {}
    ok, msg = DatabaseService.reject_cxp_payment(
        owner_uid, expense_id, payment_id,
        rejected_by=body.get("rejectedBy", _api_user_label()),
        rejected_by_uid=_api_user_uid(),
        notes=str(body.get("notes", "") or ""),
        company_id=company_id, sandbox=sandbox,
    )
    if not ok:
        return jsonify({"success": False, "error": msg}), _conflict_status(msg)
    return jsonify({"success": True, "message": msg}), 200
