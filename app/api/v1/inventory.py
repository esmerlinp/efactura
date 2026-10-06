"""API REST para el módulo de Inventario y Kardex Valorizado."""

from flask import Blueprint, request, jsonify, g
from app.services.kardex_service import KardexService
from app.api.auth import require_api_key

api_inventory_bp = Blueprint("api_inventory", __name__)


@api_inventory_bp.route("/inventory/kardex", methods=["GET"])
@require_api_key
def get_kardex():
    """
    Consultar Kardex Valorizado Continuo
    ---
    tags:
      - Inventory
    summary: Obtener Kardex de un artículo
    description: |
      Retorna los movimientos físicos y valorizados continuos (FIFO) de un artículo
      para un período y almacén determinados, incluyendo saldo inicial y saldo final.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: itemId
        in: query
        type: string
        required: true
        description: ID del artículo a consultar
      - name: warehouseId
        in: query
        type: string
        required: false
        description: ID del almacén (opcional, por defecto todos los almacenes)
      - name: dateFrom
        in: query
        type: string
        required: false
        description: Fecha inicial del período (YYYY-MM-DD)
      - name: dateTo
        in: query
        type: string
        required: false
        description: Fecha final del período (YYYY-MM-DD)
      - name: sandbox
        in: query
        type: boolean
        required: false
        default: true
        description: Indica si consulta el entorno sandbox o producción
    responses:
      200:
        description: Consulta exitosa
      400:
        description: Parámetros inválidos
    """
    company_id = g.company_id
    owner_uid = g.owner_uid
    sandbox = request.args.get("sandbox", "true").lower() in ("true", "1")

    item_id = (request.args.get("itemId") or request.args.get("item_id") or "").strip()
    if not item_id:
        return jsonify({"success": False, "error": "El parámetro 'itemId' es obligatorio."}), 400

    warehouse_id = (request.args.get("warehouseId") or request.args.get("warehouse_id") or "").strip() or None
    date_from = (request.args.get("dateFrom") or request.args.get("date_from") or "").strip() or None
    date_to = (request.args.get("dateTo") or request.args.get("date_to") or "").strip() or None

    kardex_res = KardexService.get_kardex_summary(
        company_id=company_id,
        item_id=item_id,
        warehouse_id=warehouse_id,
        date_from=date_from,
        date_to=date_to,
        sandbox=sandbox,
        owner_uid=owner_uid
    )

    return jsonify({
        "success": True,
        "kardex": kardex_res
    })


@api_inventory_bp.route("/inventory/kardex/summary", methods=["GET"])
@require_api_key
def get_kardex_summary():
    """
    Consultar Resumen y Conciliación de Kardex
    ---
    tags:
      - Inventory
    summary: Resumen valorizado de inventario por artículo
    description: |
      Retorna el resumen consolidado de inventario con conciliación automática
      frente a inventory_stock y capas de costo FIFO (inventory_cost_ledger).
    security:
      - ApiKeyHeader: []
    parameters:
      - name: warehouseId
        in: query
        type: string
        required: false
        description: ID del almacén
      - name: dateFrom
        in: query
        type: string
        required: false
        description: Fecha inicial del período (YYYY-MM-DD)
      - name: dateTo
        in: query
        type: string
        required: false
        description: Fecha final del período (YYYY-MM-DD)
      - name: sandbox
        in: query
        type: boolean
        required: false
        default: true
    responses:
      200:
        description: Consulta exitosa
    """
    company_id = g.company_id
    owner_uid = g.owner_uid
    sandbox = request.args.get("sandbox", "true").lower() in ("true", "1")

    item_id = (request.args.get("itemId") or request.args.get("item_id") or "").strip() or None
    warehouse_id = (request.args.get("warehouseId") or request.args.get("warehouse_id") or "").strip() or None
    date_from = (request.args.get("dateFrom") or request.args.get("date_from") or "").strip() or None
    date_to = (request.args.get("dateTo") or request.args.get("date_to") or "").strip() or None

    summary_res = KardexService.get_kardex_summary(
        company_id=company_id,
        item_id=item_id,
        warehouse_id=warehouse_id,
        date_from=date_from,
        date_to=date_to,
        sandbox=sandbox,
        owner_uid=owner_uid
    )

    return jsonify({
        "success": True,
        "summary": summary_res
    })
