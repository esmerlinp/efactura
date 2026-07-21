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
    """
    Listar cuentas contables
    ---
    tags:
      - Accounting
    summary: Obtener catálogo de cuentas
    description: |
      Retorna el catálogo completo de cuentas contables del contribuyente.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Operación exitosa
    """
    accounts = DatabaseService.get_chart_of_accounts(g.owner_uid)
    return jsonify({"success": True, "accounts": accounts})


@api_accounting_bp.route('/accounting/accounts', methods=['POST'])
@require_api_key
def create_account():
    """
    Crear cuenta contable
    ---
    tags:
      - Accounting
    summary: Crear una nueva cuenta contable
    description: |
      Registra una nueva cuenta en el catálogo de cuentas contables.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [code, name]
          properties:
            code:
              type: string
            name:
              type: string
            type:
              type: string
            nature:
              type: string
            group:
              type: string
            parentId:
              type: string
            level:
              type: integer
            description:
              type: string
            usage:
              type: string
            showByThirdParty:
              type: boolean
            orderIdx:
              type: integer
    responses:
      201:
        description: Cuenta creada exitosamente
    """
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
    """
    Actualizar cuenta contable
    ---
    tags:
      - Accounting
    summary: Actualizar una cuenta contable existente
    description: |
      Modifica los campos de una cuenta contable especificada por su ID.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: account_id
        in: path
        required: true
        type: string
        description: ID de la cuenta
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            code:
              type: string
            name:
              type: string
            type:
              type: string
            nature:
              type: string
            group:
              type: string
            description:
              type: string
            usage:
              type: string
            showByThirdParty:
              type: boolean
            orderIdx:
              type: integer
    responses:
      200:
        description: Cuenta actualizada exitosamente
      404:
        description: Cuenta no encontrada
    """
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
    """
    Eliminar cuenta contable
    ---
    tags:
      - Accounting
    summary: Eliminar una cuenta contable
    description: |
      Elimina una cuenta contable del catálogo. Las cuentas de sistema no pueden ser eliminadas.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: account_id
        in: path
        required: true
        type: string
        description: ID de la cuenta
    responses:
      200:
        description: Cuenta eliminada exitosamente
      400:
        description: No se puede eliminar una cuenta de sistema
      404:
        description: Cuenta no encontrada
    """
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
    """
    Listar asientos contables
    ---
    tags:
      - Accounting
    summary: Obtener asientos contables
    description: |
      Retorna la lista de asientos contables registrados.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Operación exitosa
    """
    sandbox = g.get('sandbox_mode', True)
    entries = DatabaseService.get_accounting_entries(g.owner_uid, sandbox=sandbox)
    return jsonify({"success": True, "entries": entries})


@api_accounting_bp.route('/accounting/entries', methods=['POST'])
@require_api_key
def create_entry():
    """
    Crear asiento contable
    ---
    tags:
      - Accounting
    summary: Crear un nuevo asiento contable
    description: |
      Registra un nuevo asiento contable con sus respectivas líneas de débito y crédito.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [date, concept, lines]
          properties:
            entryType:
              type: string
            typeId:
              type: string
            date:
              type: string
            concept:
              type: string
            referenceType:
              type: string
            referenceId:
              type: string
            referenceNumber:
              type: string
            prefix:
              type: string
            lines:
              type: array
              items:
                type: object
    responses:
      201:
        description: Asiento creado exitosamente
      400:
        description: Error de validación
    """
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
    """
    Obtener asiento contable
    ---
    tags:
      - Accounting
    summary: Obtener un asiento contable por ID
    description: |
      Retorna los detalles de un asiento contable específico.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: entry_id
        in: path
        required: true
        type: string
        description: ID del asiento contable
    responses:
      200:
        description: Operación exitosa
      404:
        description: Asiento no encontrado
    """
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
    """
    Balance general
    ---
    tags:
      - Accounting
    summary: Obtener balance general
    description: |
      Retorna el balance general (estado de situación financiera) a una fecha determinada.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: date
        in: query
        required: false
        type: string
        description: Fecha de corte (YYYY-MM-DD)
    responses:
      200:
        description: Operación exitosa
    """
    date = request.args.get('date', '')
    result = AccountingService.get_balance_sheet(g.owner_uid, date=date or None)
    return jsonify({"success": True, "result": result})


@api_accounting_bp.route('/accounting/reports/income-statement', methods=['GET'])
@require_api_key
def income_statement():
    """
    Estado de resultados
    ---
    tags:
      - Accounting
    summary: Obtener estado de resultados
    description: |
      Retorna el estado de resultados (pérdidas y ganancias) para un período determinado.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: dateFrom
        in: query
        required: false
        type: string
        description: Fecha de inicio (YYYY-MM-DD)
      - name: dateTo
        in: query
        required: false
        type: string
        description: Fecha de fin (YYYY-MM-DD)
    responses:
      200:
        description: Operación exitosa
    """
    date_from = request.args.get('dateFrom', '')
    date_to = request.args.get('dateTo', '')
    result = AccountingService.get_income_statement(g.owner_uid, date_from=date_from or None, date_to=date_to or None)
    return jsonify({"success": True, "result": result})


@api_accounting_bp.route('/accounting/reports/trial-balance', methods=['GET'])
@require_api_key
def trial_balance():
    """
    Balance de comprobación
    ---
    tags:
      - Accounting
    summary: Obtener balance de comprobación
    description: |
      Retorna el balance de comprobación (sumas y saldos) a una fecha determinada.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: date
        in: query
        required: false
        type: string
        description: Fecha de corte (YYYY-MM-DD)
    responses:
      200:
        description: Operación exitosa
    """
    date = request.args.get('date', '')
    result = AccountingService.get_trial_balance(g.owner_uid, date=date or None)
    return jsonify({"success": True, "result": result})


# =========================================================================
# FIXED ASSETS
# =========================================================================
@api_accounting_bp.route('/accounting/fixed-assets', methods=['GET'])
@require_api_key
def get_fixed_assets():
    """
    Listar activos fijos
    ---
    tags:
      - Accounting
    summary: Obtener activos fijos
    description: |
      Retorna la lista de activos fijos registrados.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Operación exitosa
    """
    sandbox = g.get('sandbox_mode', True)
    assets = DatabaseService.get_fixed_assets(g.owner_uid, sandbox=sandbox)
    return jsonify({"success": True, "assets": assets})


@api_accounting_bp.route('/accounting/fixed-assets', methods=['POST'])
@require_api_key
def create_fixed_asset():
    """
    Registrar activo fijo
    ---
    tags:
      - Accounting
    summary: Registrar un nuevo activo fijo
    description: |
      Registra un nuevo activo fijo con su configuración de depreciación.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
            description:
              type: string
            acquisitionDate:
              type: string
            acquisitionCost:
              type: number
            usefulLifeYears:
              type: integer
            salvageValue:
              type: number
            depreciationMethod:
              type: string
            accountId:
              type: string
    responses:
      201:
        description: Activo fijo registrado exitosamente
      400:
        description: Error de validación
    """
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
    """
    Estado de obligaciones tributarias
    ---
    tags:
      - Accounting
    summary: Consultar estado de obligaciones tributarias DGII
    description: |
      Retorna el estado actual de las obligaciones tributarias ante la DGII,
      incluyendo las pendientes, vencidas y próximas a vencer.
    security:
      - ApiKeyHeader: []
    responses:
      200:
        description: Operación exitosa
    """
    from app.services.tax_obligation_service import TaxObligationService
    status_list = TaxObligationService.get_status(g.owner_uid)
    pending = [s for s in status_list if s["status"] in ("due_soon", "overdue", "upcoming")]
    return jsonify({
        "success": True,
        "obligations": status_list,
        "pending_count": len(pending),
        "pending": pending,
    })
