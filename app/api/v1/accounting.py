"""API REST para el módulo de Contabilidad."""
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from app.services.db_service import DatabaseService
from app.services.accounting_service import AccountingService
from app.services.fixed_asset_service import FixedAssetService
from app.api.auth import require_api_key

api_accounting_bp = Blueprint('api_accounting', __name__)


# =========================================================================
# CHART OF ACCOUNTS
# =========================================================================
@api_accounting_bp.route('/accounting/accounts', methods=['GET'])
@require_api_key
def get_accounts():
    accounts = DatabaseService.get_chart_of_accounts(g.owner_uid)
    return jsonify({"success": True, "accounts": accounts})


@api_accounting_bp.route('/accounting/accounts', methods=['POST'])
@require_api_key
def create_account():
    data = request.get_json() or {}
    account_id = str(uuid.uuid4())
    account = {
        "id": account_id,
        "code": data.get("code", ""),
        "name": data.get("name", ""),
        "type": data.get("type", "movimiento"),
        "nature": data.get("nature", "deudora"),
        "group": data.get("group", "activos"),
        "parentId": data.get("parentId"),
        "level": data.get("level", 1),
        "description": data.get("description", ""),
        "usage": data.get("usage"),
        "showByThirdParty": data.get("showByThirdParty", False),
        "isActive": True,
        "isSystem": False,
        "orderIdx": data.get("orderIdx", 1),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    DatabaseService.save_account(g.owner_uid, account_id, account)
    return jsonify({"success": True, "account": account}), 201


@api_accounting_bp.route('/accounting/accounts/<account_id>', methods=['PUT'])
@require_api_key
def update_account(account_id):
    data = request.get_json() or {}
    account = DatabaseService.get_account(g.owner_uid, account_id)
    if not account:
        return jsonify({"success": False, "error": "Cuenta no encontrada"}), 404
    for field in ("code", "name", "type", "nature", "group", "description", "usage", "showByThirdParty", "orderIdx"):
        if field in data:
            account[field] = data[field]
    account["updatedAt"] = datetime.now(timezone.utc).isoformat()
    DatabaseService.save_account(g.owner_uid, account_id, account)
    return jsonify({"success": True, "account": account})


@api_accounting_bp.route('/accounting/accounts/<account_id>', methods=['DELETE'])
@require_api_key
def delete_account(account_id):
    account = DatabaseService.get_account(g.owner_uid, account_id)
    if not account:
        return jsonify({"success": False, "error": "Cuenta no encontrada"}), 404
    if account.get("isSystem"):
        return jsonify({"success": False, "error": "No se puede eliminar una cuenta regla"}), 400
    DatabaseService.delete_account(g.owner_uid, account_id)
    return jsonify({"success": True, "message": "Cuenta eliminada"})


# =========================================================================
# ACCOUNTING ENTRIES
# =========================================================================
@api_accounting_bp.route('/accounting/entries', methods=['GET'])
@require_api_key
def get_entries():
    sandbox = g.get('sandbox_mode', True)
    entries = DatabaseService.get_accounting_entries(g.owner_uid, sandbox=sandbox)
    return jsonify({"success": True, "entries": entries})


@api_accounting_bp.route('/accounting/entries', methods=['POST'])
@require_api_key
def create_entry():
    sandbox = g.get('sandbox_mode', True)
    data = request.get_json() or {}
    try:
        entry = AccountingService.generate_entry(g.owner_uid, {
            "entryType": data.get("entryType", "standard"),
            "typeId": data.get("typeId"),
            "date": data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            "concept": data.get("concept", ""),
            "referenceType": data.get("referenceType"),
            "referenceId": data.get("referenceId"),
            "referenceNumber": data.get("referenceNumber"),
            "lines": data.get("lines", []),
            "createdBy": "api",
            "prefix": data.get("prefix", "ED"),
        }, sandbox=sandbox)
        return jsonify({"success": True, "entry": entry}), 201
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@api_accounting_bp.route('/accounting/entries/<entry_id>', methods=['GET'])
@require_api_key
def get_entry(entry_id):
    sandbox = g.get('sandbox_mode', True)
    entry = DatabaseService.get_accounting_entry(g.owner_uid, entry_id, sandbox=sandbox)
    if not entry:
        return jsonify({"success": False, "error": "Asiento no encontrado"}), 404
    return jsonify({"success": True, "entry": entry})


# =========================================================================
# REPORTS
# =========================================================================
@api_accounting_bp.route('/accounting/reports/balance-sheet', methods=['GET'])
@require_api_key
def balance_sheet():
    date = request.args.get('date', '')
    result = AccountingService.get_balance_sheet(g.owner_uid, date=date or None)
    return jsonify({"success": True, "result": result})


@api_accounting_bp.route('/accounting/reports/income-statement', methods=['GET'])
@require_api_key
def income_statement():
    date_from = request.args.get('dateFrom', '')
    date_to = request.args.get('dateTo', '')
    result = AccountingService.get_income_statement(g.owner_uid, date_from=date_from or None, date_to=date_to or None)
    return jsonify({"success": True, "result": result})


@api_accounting_bp.route('/accounting/reports/trial-balance', methods=['GET'])
@require_api_key
def trial_balance():
    date = request.args.get('date', '')
    result = AccountingService.get_trial_balance(g.owner_uid, date=date or None)
    return jsonify({"success": True, "result": result})


# =========================================================================
# FIXED ASSETS
# =========================================================================
@api_accounting_bp.route('/accounting/fixed-assets', methods=['GET'])
@require_api_key
def get_fixed_assets():
    sandbox = g.get('sandbox_mode', True)
    assets = DatabaseService.get_fixed_assets(g.owner_uid, sandbox=sandbox)
    return jsonify({"success": True, "assets": assets})


@api_accounting_bp.route('/accounting/fixed-assets', methods=['POST'])
@require_api_key
def create_fixed_asset():
    sandbox = g.get('sandbox_mode', True)
    data = request.get_json() or {}
    try:
        asset = FixedAssetService.register_asset(g.owner_uid, data, sandbox=sandbox)
        return jsonify({"success": True, "asset": asset}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


# =========================================================================
# OBLIGACIONES TRIBUTARIAS DGII
# =========================================================================
@api_accounting_bp.route('/accounting/tax-obligations/status', methods=['GET'])
@require_api_key
def tax_obligations_status():
    from app.services.tax_obligation_service import TaxObligationService
    status_list = TaxObligationService.get_status(g.owner_uid)
    pending = [s for s in status_list if s["status"] in ("due_soon", "overdue", "upcoming")]
    return jsonify({
        "success": True,
        "obligations": status_list,
        "pending_count": len(pending),
        "pending": pending,
    })
