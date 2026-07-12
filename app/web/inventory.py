"""Blueprint de Inventario Avanzado: transferencias, conteos físicos, costeo, lotes, alertas, recepciones de mercancía."""

import uuid
from datetime import datetime, timezone, date

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g

from app.utils.decorators import check_permission
from app.services.purchase_order_service import PurchaseOrderService
from app.services.goods_receipt_service import GoodsReceiptService
from app.services.audit_service import AuditService, ACTION_CREATE, ACTION_UPDATE

MODULE_RECEIPT = "Recepción de Mercancía"

web_inventory_bp = Blueprint("web_inventory", __name__, template_folder="templates")


def _owner():
    return session["user"]["ownerUID"]

def _sandbox():
    return session.get("is_sandbox_mode", True)


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD AVANZADO DE INVENTARIO
# ═══════════════════════════════════════════════════════════════════════════

@web_inventory_bp.route("/inventory/advanced")
def advanced_dashboard():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not check_permission("canManageInventory"):
        return render_template("auth/restricted.html", feature_name="Inventario Avanzado", required_permission="canManageInventory")

    from app.services.db_service import DatabaseService
    from app.services.inventory_alert_service import InventoryAlertService

    owner_uid, sb = _owner(), _sandbox()
    items = DatabaseService.get_items(owner_uid, sandbox=sb, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sb)
    stocks = DatabaseService.get_inventory_stock(owner_uid, sandbox=sb)

    # Total valuation
    total_cost = 0.0
    for it in items:
        if it.get("type", "Bien") == "Bien":
            qty = float(it.get("totalStock", 0))
            cost = float(it.get("costPrice", 0))
            total_cost += qty * cost

    reorder = InventoryAlertService.get_reorder_suggestions(owner_uid, sandbox=sb)
    expirations = InventoryAlertService.get_expiration_alerts(owner_uid, sandbox=sb)

    return render_template("inventario/advanced_dashboard.html",
        active_page="inventory_advanced",
        items=items, warehouses=warehouses,
        totalCost=round(total_cost, 2),
        totalItems=len(items),
        reorder=reorder,
        expirations=expirations)


# ═══════════════════════════════════════════════════════════════════════════
# TRANSFERENCIAS ENTRE ALMACENES
# ═══════════════════════════════════════════════════════════════════════════

@web_inventory_bp.route("/inventory/transfers")
def transfer_list():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    from app.services.warehouse_transfer_service import WarehouseTransferService
    transfers = WarehouseTransferService.get_transfers(_owner(), sandbox=_sandbox())
    return render_template("inventario/transfer_list.html", active_page="inventory_transfers", transfers=transfers)


@web_inventory_bp.route("/inventory/transfers/new", methods=["GET", "POST"])
def transfer_new():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    from app.services.db_service import DatabaseService
    from app.services.warehouse_transfer_service import WarehouseTransferService

    owner_uid, sb = _owner(), _sandbox()
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sb)
    items = [it for it in DatabaseService.get_items(owner_uid, sandbox=sb, branch_id=g.get('branch_id'), project_id=g.get('project_id')) if it.get("type", "Bien") == "Bien"]

    if request.method == "POST":
        lines = []
        for item in items:
            qty_str = request.form.get(f"qty_{item['id']}", "0")
            try:
                qty = float(qty_str)
            except ValueError:
                qty = 0.0
            if qty > 0:
                lines.append({
                    "itemId": item["id"],
                    "itemName": item.get("name", ""),
                    "quantity": qty,
                    "unitCost": float(item.get("costPrice", 0)),
                })

        if not lines:
            flash("Debe especificar al menos un producto con cantidad > 0.", "error")
            return render_template("inventario/transfer_form.html", active_page="inventory_transfers",
                                   warehouses=warehouses, items=items)

        origin_id = request.form.get("originWarehouseId", "")
        dest_id = request.form.get("destinationWarehouseId", "")
        if origin_id == dest_id:
            flash("El almacén origen y destino deben ser diferentes.", "error")
            return render_template("inventario/transfer_form.html", active_page="inventory_transfers",
                                   warehouses=warehouses, items=items)

        wh_map = {w["id"]: w["name"] for w in warehouses}
        transfer_dict = {
            "originWarehouseId": origin_id,
            "originWarehouseName": wh_map.get(origin_id, ""),
            "destinationWarehouseId": dest_id,
            "destinationWarehouseName": wh_map.get(dest_id, ""),
            "lines": lines,
            "requestedBy": session["user"].get("email", ""),
            "notes": request.form.get("notes", ""),
        }
        tid = WarehouseTransferService.request_transfer(owner_uid, transfer_dict, sandbox=sb)
        if tid:
            flash("Transferencia solicitada. Pendiente de aprobación.", "success")
        else:
            flash("Error al crear transferencia.", "error")
        return redirect(url_for("web_inventory.transfer_list"))

    return render_template("inventario/transfer_form.html", active_page="inventory_transfers",
                           warehouses=warehouses, items=items)


@web_inventory_bp.route("/inventory/transfers/<transfer_id>/approve", methods=["POST"])
def transfer_approve(transfer_id):
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    from app.services.warehouse_transfer_service import WarehouseTransferService
    ok, msg = WarehouseTransferService.approve_transfer(
        _owner(), transfer_id, session["user"].get("email", ""), sandbox=_sandbox())
    flash(msg, "success" if ok else "error")
    return redirect(url_for("web_inventory.transfer_list"))


@web_inventory_bp.route("/inventory/transfers/<transfer_id>/reject", methods=["POST"])
def transfer_reject(transfer_id):
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    reason = request.form.get("reason", "Sin motivo especificado")
    from app.services.warehouse_transfer_service import WarehouseTransferService
    ok, msg = WarehouseTransferService.reject_transfer(_owner(), transfer_id, reason, sandbox=_sandbox())
    flash(msg, "success" if ok else "error")
    return redirect(url_for("web_inventory.transfer_list"))


# ═══════════════════════════════════════════════════════════════════════════
# CONTEOS FÍSICOS
# ═══════════════════════════════════════════════════════════════════════════

@web_inventory_bp.route("/inventory/physical-counts")
def physical_count_list():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    from app.services.physical_count_service import PhysicalCountService
    counts = PhysicalCountService.get_counts(_owner(), sandbox=_sandbox())
    return render_template("inventario/physical_count_list.html", active_page="inventory_counts", counts=counts)


@web_inventory_bp.route("/inventory/physical-counts/new", methods=["GET", "POST"])
def physical_count_new():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    from app.services.db_service import DatabaseService
    from app.services.physical_count_service import PhysicalCountService

    owner_uid, sb = _owner(), _sandbox()
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sb)

    if request.method == "POST":
        wh_id = request.form["warehouseId"]
        wh_name = next((w["name"] for w in warehouses if w["id"] == wh_id), "")
        cid = PhysicalCountService.start_count(
            owner_uid, wh_id, wh_name, session["user"].get("email", ""), sandbox=sb)
        if cid:
            flash("Conteo físico iniciado.", "success")
            return redirect(url_for("web_inventory.physical_count_detail", count_id=cid))
        flash("Error al iniciar conteo.", "error")
        return redirect(url_for("web_inventory.physical_count_list"))

    return render_template("inventario/physical_count_new.html", active_page="inventory_counts", warehouses=warehouses)


@web_inventory_bp.route("/inventory/physical-counts/<count_id>", methods=["GET", "POST"])
def physical_count_detail(count_id):
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    from app.services.physical_count_service import PhysicalCountService

    owner_uid, sb = _owner(), _sandbox()
    count = PhysicalCountService.get_count(owner_uid, count_id, sandbox=sb)
    if not count:
        flash("Conteo no encontrado.", "error")
        return redirect(url_for("web_inventory.physical_count_list"))

    if request.method == "POST":
        if "finalize" in request.form:
            ok, result = PhysicalCountService.finalize_count(
                owner_uid, count_id, session["user"].get("email", ""), sandbox=sb)
            if ok:
                flash(f"Conteo finalizado. {result['linesWithDifference']} líneas con diferencia, "
                      f"{result['adjustments']} ajustes generados.", "success")
            else:
                flash(result, "error")
            return redirect(url_for("web_inventory.physical_count_list"))
        else:
            for key, val in request.form.items():
                if key.startswith("qty_"):
                    item_id = key[4:]
                    try:
                        qty = float(val)
                    except ValueError:
                        qty = 0.0
                    PhysicalCountService.record_count_line(owner_uid, count_id, item_id, qty, sandbox=sb)
            flash("Líneas actualizadas.", "success")
            count = PhysicalCountService.get_count(owner_uid, count_id, sandbox=sb)

    return render_template("inventario/physical_count_detail.html", active_page="inventory_counts", count=count)


# ═══════════════════════════════════════════════════════════════════════════
# LOTES Y SERIES
# ═══════════════════════════════════════════════════════════════════════════

@web_inventory_bp.route("/inventory/lots")
def lot_list():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    from app.services.db_service import db_firestore, firebase_initialized

    lots = []
    if firebase_initialized:
        sb = _sandbox()
        coll = "sandbox_inventory_lots" if sb else "inventory_lots"
        try:
            docs = db_firestore.collection("users").document(_owner()).collection(coll).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                lots.append(data)
            lots.sort(key=lambda l: l.get("expirationDate", ""))
        except Exception as e:
            print(f"⚠️ Error al obtener lotes: {e}")

    return render_template("inventario/lot_list.html", active_page="inventory_lots", lots=lots)


# ═══════════════════════════════════════════════════════════════════════════
# ALERTAS
# ═══════════════════════════════════════════════════════════════════════════

@web_inventory_bp.route("/inventory/alerts")
def alert_dashboard():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    from app.services.inventory_alert_service import InventoryAlertService

    owner_uid, sb = _owner(), _sandbox()
    reorder = InventoryAlertService.get_reorder_suggestions(owner_uid, sandbox=sb)
    expirations = InventoryAlertService.get_expiration_alerts(owner_uid, sandbox=sb)

    return render_template("inventario/alerts.html", active_page="inventory_alerts",
                           reorder=reorder, expirations=expirations)


# ═══════════════════════════════════════════════════════════════════════════
# RECEPCIONES DE MERCANCÍA
# ═══════════════════════════════════════════════════════════════════════════

@web_inventory_bp.route("/inventory/receipts")
def list_receipts():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not check_permission("canManageInventory"):
        return render_template("auth/restricted.html", feature_name="Recepciones de Mercancía", required_permission="canManageInventory")
    owner_uid = _owner()
    sandbox = _sandbox()
    from app.services.db_service import DatabaseService
    receipts = GoodsReceiptService.get_receipts(owner_uid, sandbox=sandbox)
    return render_template("inventario/receipts_list.html",
                           receipts=receipts, active_page="inventory_receipts")


@web_inventory_bp.route("/inventory/receipts/new", methods=["GET", "POST"])
def new_receipt():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not check_permission("canManageInventory"):
        return render_template("auth/restricted.html", feature_name="Recepciones de Mercancía", required_permission="canManageInventory")
    owner_uid = _owner()
    sandbox = _sandbox()
    from app.services.db_service import DatabaseService

    po_id = request.args.get("po_id", request.form.get("po_id", ""))
    if not po_id:
        flash("Debe especificar una orden de compra.", "error")
        return redirect(url_for("web_inventory.list_receipts"))

    po = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not po:
        flash("Orden de compra no encontrada.", "error")
        return redirect(url_for("web_inventory.list_receipts"))
    if po.get("status") not in ("aprobada", "recibida_parcial"):
        flash("Solo se pueden recibir órdenes aprobadas o con recepción parcial.", "error")
        return redirect(url_for("web_purchase_orders.purchase_order_detail", po_id=po_id))

    if request.method == "POST":
        receipt_id = str(uuid.uuid4())
        receipt_number = GoodsReceiptService.get_next_receipt_number(owner_uid, sandbox=sandbox)
        warehouse_id = request.form.get("warehouseId", "")
        warehouse_name = request.form.get("warehouseName", "")

        po_items = po.get("items", [])
        receipt_items = []
        for item in po_items:
            item_id = item.get("id", "")
            rqty_str = request.form.get(f"received_qty_{item_id}", "0")
            cat_item_id = request.form.get(f"catalog_item_{item_id}", "")
            rqty = float(rqty_str) if rqty_str else 0
            if rqty <= 0:
                continue
            receipt_items.append({
                "poItemId": item_id,
                "itemId": cat_item_id,
                "poItemName": item.get("name", ""),
                "itemName": request.form.get(f"catalog_name_{item_id}", item.get("name", "")),
                "orderedQuantity": float(item.get("quantity", 0)),
                "receivedQuantity": rqty,
                "unit": item.get("unit", "Unidad"),
                "unitPrice": float(item.get("unitPrice", 0)),
            })

        if not receipt_items:
            flash("Debes indicar al menos una partida con cantidad > 0.", "error")
            return redirect(url_for("web_inventory.new_receipt", po_id=po_id))

        user = session["user"].get("displayName", "Usuario")

        receipt_data = {
            "receiptNumber": receipt_number,
            "poId": po_id,
            "poNumber": po.get("poNumber", ""),
            "supplierId": po.get("supplierId", ""),
            "supplierName": po.get("supplierName", ""),
            "supplierRnc": po.get("supplierRnc", ""),
            "warehouseId": warehouse_id,
            "warehouseName": warehouse_name,
            "receiptDate": request.form.get("receiptDate", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            "items": receipt_items,
            "status": "completada",
            "notes": request.form.get("notes", ""),
            "createdBy": user,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }

        GoodsReceiptService.create_receipt(owner_uid, receipt_data, sandbox=sandbox)
        GoodsReceiptService.register_receipt_inventory(owner_uid, receipt_data, sandbox=sandbox)

        po_items_map = {item["poItemId"]: item for item in receipt_items}
        for item in po.get("items", []):
            item_id = item.get("id", "")
            received_here = po_items_map.get(item_id, {}).get("receivedQuantity", 0)
            item["receivedQuantity"] = float(item.get("receivedQuantity", 0)) + received_here

        all_complete = all(
            float(it.get("receivedQuantity", 0)) >= float(it.get("quantity", 0))
            for it in po.get("items", [])
        )
        po["status"] = "recibida_completa" if all_complete else "recibida_parcial"
        po["receivedBy"] = user
        po["receivedAt"] = datetime.now(timezone.utc).isoformat()
        po["updatedAt"] = datetime.now(timezone.utc).isoformat()
        PurchaseOrderService.save_purchase_order(owner_uid, po_id, po, sandbox=sandbox)

        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_RECEIPT,
            entity_id=receipt_id,
            entity_label=receipt_number,
            after=receipt_data,
        )
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module="Órdenes de Compra",
            entity_id=po_id,
            entity_label=po.get("poNumber", ""),
            after=po,
        )

        flash(f"Recepción {receipt_number} registrada exitosamente.", "success")
        return redirect(url_for("web_purchase_orders.purchase_order_detail", po_id=po_id))

    receipt_number = GoodsReceiptService.get_next_receipt_number(owner_uid, sandbox=sandbox)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    catalog_items = DatabaseService.get_items(owner_uid, sandbox=sandbox, branch_id=g.get("branch_id"), project_id=g.get("project_id"))
    catalog_items = [i for i in catalog_items if i.get("isActive", True)]
    return render_template("inventario/new_receipt.html",
                           order=po, receipt_number=receipt_number, today=today,
                           warehouses=warehouses, catalog_items=catalog_items,
                           active_page="inventory_receipts")


@web_inventory_bp.route("/inventory/receipts/<receipt_id>")
def receipt_detail(receipt_id):
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not check_permission("canManageInventory"):
        return render_template("auth/restricted.html", feature_name="Recepciones de Mercancía", required_permission="canManageInventory")
    owner_uid = _owner()
    sandbox = _sandbox()
    receipt = GoodsReceiptService.get_receipt(owner_uid, receipt_id, sandbox=sandbox)
    if not receipt:
        flash("Recepción no encontrada.", "error")
        return redirect(url_for("web_inventory.list_receipts"))
    return render_template("inventario/receipt_detail.html",
                           receipt=receipt, active_page="inventory_receipts")
