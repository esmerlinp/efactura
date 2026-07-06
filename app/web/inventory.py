"""Blueprint de Inventario Avanzado: transferencias, conteos físicos, costeo, lotes, alertas."""

import uuid
from datetime import datetime, timezone, date

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from app.utils.decorators import check_permission

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
    items = DatabaseService.get_items(owner_uid, sandbox=sb)
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
    items = [it for it in DatabaseService.get_items(owner_uid, sandbox=sb) if it.get("type", "Bien") == "Bien"]

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
