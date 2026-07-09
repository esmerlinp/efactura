# app/api/v1/expenses.py
import json
from flask import Blueprint, request, g, jsonify
from app.api.auth import require_api_key
from app.services.db_service import DatabaseService

api_expenses_bp = Blueprint('api_expenses', __name__)


@api_expenses_bp.route('/expenses/payments', methods=['GET'])
@require_api_key
def list_payments():
    """GET /api/v1/expenses/payments — Lista pagos/gastos formales."""
    owner_uid = g.owner_uid
    sandbox = g.sandbox_mode
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    filtered = [e for e in expenses if e.get('ecfType') != 'E43' and not e.get('isRecurring')]
    return jsonify({'success': True, 'data': filtered, 'count': len(filtered)})


@api_expenses_bp.route('/expenses/minor', methods=['GET'])
@require_api_key
def list_minor():
    """GET /api/v1/expenses/minor — Lista gastos menores (E43)."""
    owner_uid = g.owner_uid
    sandbox = g.sandbox_mode
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    filtered = [e for e in expenses if e.get('ecfType') == 'E43']
    return jsonify({'success': True, 'data': filtered, 'count': len(filtered)})


@api_expenses_bp.route('/expenses/recurring', methods=['GET'])
@require_api_key
def list_recurring():
    """GET /api/v1/expenses/recurring — Lista pagos recurrentes."""
    owner_uid = g.owner_uid
    sandbox = g.sandbox_mode
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    filtered = [e for e in expenses if e.get('isRecurring')]
    return jsonify({'success': True, 'data': filtered, 'count': len(filtered)})


@api_expenses_bp.route('/expenses/payments/classify', methods=['GET'])
@require_api_key
def classify_payment():
    """GET /api/v1/expenses/payments/classify — Clasifica concepto de pago con IA."""
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
@require_api_key
def classify_minor():
    """GET /api/v1/expenses/minor/classify — Clasifica concepto de gasto menor con IA."""
    concept = request.args.get('concept', '')
    if not concept:
        return jsonify({'success': False, 'error': 'Parámetro concepto requerido'}), 400
    try:
        from app.services.ai_classifier import classify_expense
        result = classify_expense(concept)
        return jsonify({'success': True, 'code': result.get('code'), 'category': result.get('category')})
    except ImportError:
        return jsonify({'success': True, 'code': '06', 'category': 'Comida y Restaurantes'})
