import uuid
import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
from app.services.purchase_order_service import PurchaseOrderService
from app.services.supplier_service import SupplierService
from app.services.goods_receipt_service import GoodsReceiptService
from app.utils.decorators import check_permission
from app.services.audit_service import AuditService, ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE

web_purchase_orders_bp = Blueprint('web_purchase_orders', __name__)

MODULE_PO = "Órdenes de Compra"


@web_purchase_orders_bp.route('/purchase-orders')
def list_purchase_orders():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    orders = PurchaseOrderService.get_purchase_orders(owner_uid, sandbox=sandbox)

    total_items = len(orders)
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    per_page = request.args.get('per_page', '10').strip()
    if per_page == 'all':
        per_page_val = max(1, total_items)
    else:
        try:
            per_page_val = int(per_page)
            if per_page_val not in [10, 25, 50, 100]:
                per_page_val = 10
        except ValueError:
            per_page_val = 10
    total_pages = max(1, (total_items + per_page_val - 1) // per_page_val)
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start_idx = (page - 1) * per_page_val
    end_idx = start_idx + per_page_val
    paginated = orders[start_idx:end_idx]
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    return render_template('purchase_orders/list.html',
                           orders=paginated,
                           page=page,
                           total_pages=total_pages,
                           total_items=total_items,
                           pages_range=range(1, total_pages + 1),
                           has_prev=page > 1,
                           has_next=page < total_pages,
                           start_count=start_count,
                           end_count=end_count,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/new', methods=['GET', 'POST'])
def new_purchase_order():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        po_id = str(uuid.uuid4())
        items_raw = request.form.getlist('items[][name]')
        items_qty = request.form.getlist('items[][quantity]')
        items_price = request.form.getlist('items[][unitPrice]')
        items_itbis = request.form.getlist('items[][itbisRate]')
        items_discount = request.form.getlist('items[][discount]')

        items = []
        subtotal = 0.0
        total_itbis = 0.0
        total_discount = 0.0
        for i in range(len(items_raw)):
            name = items_raw[i].strip()
            if not name:
                continue
            qty = float(items_qty[i]) if i < len(items_qty) and items_qty[i] else 0
            price = float(items_price[i]) if i < len(items_price) and items_price[i] else 0
            itbis_rate = float(items_itbis[i]) if i < len(items_itbis) and items_itbis[i] else 0.0
            discount_pct = float(items_discount[i]) if i < len(items_discount) and items_discount[i] else 0.0

            line_sub = qty * price
            line_discount = line_sub * (discount_pct / 100.0)
            line_itbis = (line_sub - line_discount) * itbis_rate
            line_total = line_sub - line_discount + line_itbis
            subtotal += line_sub
            total_discount += line_discount
            total_itbis += line_itbis

            items.append({
                "id": str(uuid.uuid4()),
                "name": name,
                "quantity": qty,
                "unit": "Unidad",
                "unitPrice": price,
                "itbisRate": itbis_rate,
                "discount": discount_pct,
                "subtotal": round(line_sub, 2),
                "itbisAmount": round(line_itbis, 2),
                "total": round(line_total, 2),
                "receivedQuantity": 0,
            })

        po_number = PurchaseOrderService.get_next_po_number(owner_uid, sandbox=sandbox)
        supplier_id = request.form.get('supplierId', '')

        po_dict = {
            "poNumber": po_number,
            "supplierId": supplier_id,
            "supplierName": request.form.get('supplierName', ''),
            "supplierRnc": request.form.get('supplierRnc', ''),
            "status": "borrador",
            "orderDate": request.form.get('orderDate', datetime.utcnow().strftime('%Y-%m-%d')),
            "expectedDate": request.form.get('expectedDate', ''),
            "deliveryAddress": request.form.get('deliveryAddress', ''),
            "paymentTerms": request.form.get('paymentTerms', 'contado'),
            "currency": request.form.get('currency', 'DOP'),
            "exchangeRate": float(request.form.get('exchangeRate', 1.0)),
            "subtotal": round(subtotal, 2),
            "itbis": round(total_itbis, 2),
            "discount": round(total_discount, 2),
            "total": round(subtotal - total_discount + total_itbis, 2),
            "notes": request.form.get('notes', ''),
            "internalNotes": request.form.get('internalNotes', ''),
            "items": items,
            "createdBy": session['user'].get('displayName', 'Usuario'),
        }

        PurchaseOrderService.save_purchase_order(owner_uid, po_id, po_dict, sandbox=sandbox)

        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_PO,
            entity_id=po_id,
            entity_label=po_number,
            after=po_dict,
        )

        flash(f'✅ Orden de compra {po_number} creada exitosamente.', 'success')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))

    po_number = PurchaseOrderService.get_next_po_number(owner_uid, sandbox=sandbox)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    suppliers = SupplierService.get_suppliers(owner_uid, sandbox=sandbox)
    return render_template('purchase_orders/new.html',
                           po_number=po_number,
                           today=today,
                           suppliers=suppliers,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>')
def purchase_order_detail(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))
    receipts = GoodsReceiptService.get_receipts_by_po(owner_uid, po_id, sandbox=sandbox)
    order['receipts'] = receipts
    supplier_invoices = SupplierInvoiceService.get_by_po(owner_uid, po_id, sandbox=sandbox)
    order['supplier_invoices'] = supplier_invoices
    return render_template('purchase_orders/detail.html',
                           order=order,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/edit', methods=['GET', 'POST'])
def edit_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))

    if order.get('status') not in ('borrador', 'pendiente_aprobacion'):
        flash('❌ Solo se pueden editar órdenes en estado borrador o pendiente de aprobación.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    if request.method == 'POST':
        items_raw = request.form.getlist('items[][name]')
        items_qty = request.form.getlist('items[][quantity]')
        items_price = request.form.getlist('items[][unitPrice]')
        items_itbis = request.form.getlist('items[][itbisRate]')
        items_discount = request.form.getlist('items[][discount]')

        items = []
        subtotal = 0.0
        total_itbis = 0.0
        total_discount = 0.0
        for i in range(len(items_raw)):
            name = items_raw[i].strip()
            if not name:
                continue
            qty = float(items_qty[i]) if i < len(items_qty) and items_qty[i] else 0
            price = float(items_price[i]) if i < len(items_price) and items_price[i] else 0
            itbis_rate = float(items_itbis[i]) if i < len(items_itbis) and items_itbis[i] else 0.0
            discount_pct = float(items_discount[i]) if i < len(items_discount) and items_discount[i] else 0.0

            line_sub = qty * price
            line_discount = line_sub * (discount_pct / 100.0)
            line_itbis = (line_sub - line_discount) * itbis_rate
            line_total = line_sub - line_discount + line_itbis
            subtotal += line_sub
            total_discount += line_discount
            total_itbis += line_itbis

            items.append({
                "id": str(uuid.uuid4()),
                "name": name,
                "quantity": qty,
                "unit": "Unidad",
                "unitPrice": price,
                "itbisRate": itbis_rate,
                "discount": discount_pct,
                "subtotal": round(line_sub, 2),
                "itbisAmount": round(line_itbis, 2),
                "total": round(line_total, 2),
                "receivedQuantity": 0,
            })

        supplier_id = request.form.get('supplierId', '')

        before = dict(order)
        order.update({
            "supplierId": supplier_id,
            "supplierName": request.form.get('supplierName', ''),
            "supplierRnc": request.form.get('supplierRnc', ''),
            "orderDate": request.form.get('orderDate', order.get('orderDate', '')),
            "expectedDate": request.form.get('expectedDate', ''),
            "deliveryAddress": request.form.get('deliveryAddress', ''),
            "paymentTerms": request.form.get('paymentTerms', 'contado'),
            "currency": request.form.get('currency', 'DOP'),
            "exchangeRate": float(request.form.get('exchangeRate', 1.0)),
            "subtotal": round(subtotal, 2),
            "itbis": round(total_itbis, 2),
            "discount": round(total_discount, 2),
            "total": round(subtotal - total_discount + total_itbis, 2),
            "notes": request.form.get('notes', ''),
            "internalNotes": request.form.get('internalNotes', ''),
            "items": items,
        })

        PurchaseOrderService.save_purchase_order(owner_uid, po_id, order, sandbox=sandbox)

        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_PO,
            entity_id=po_id,
            entity_label=order.get('poNumber', ''),
            before=before,
            after=order,
        )

        flash(f'✅ Orden de compra {order.get("poNumber")} actualizada.', 'success')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    today = datetime.utcnow().strftime('%Y-%m-%d')
    suppliers = SupplierService.get_suppliers(owner_uid, sandbox=sandbox)
    return render_template('purchase_orders/edit.html',
                           order=order,
                           today=today,
                           suppliers=suppliers,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/delete', methods=['POST'])
def delete_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))

    po_number = order.get('poNumber', '')
    PurchaseOrderService.delete_purchase_order(owner_uid, po_id, sandbox=sandbox)

    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_DELETE,
        module=MODULE_PO,
        entity_id=po_id,
        entity_label=po_number,
        before=order,
    )

    flash(f'🗑️ Orden de compra {po_number} eliminada.', 'success')
    return redirect(url_for('web_purchase_orders.list_purchase_orders'))


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/approve', methods=['POST'])
def approve_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    user = session['user'].get('displayName', 'Usuario')

    po = PurchaseOrderService.update_status(owner_uid, po_id, 'aprobada', sandbox=sandbox, user=user)
    if not po:
        return jsonify(success=False, error="Orden no encontrada"), 404

    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_PO,
        entity_id=po_id, entity_label=po.get('poNumber', ''),
        after=po,
    )
    return jsonify(success=True)


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/receive', methods=['POST'])
def receive_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    po = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not po:
        return jsonify(success=False, error="Orden no encontrada"), 404

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    received_qty_map = data.get('receivedQuantities', {})
    items = po.get('items', [])
    all_complete = True
    for item in items:
        item_id = item.get('id', '')
        qty = float(received_qty_map.get(item_id, item.get('quantity', 0)))
        item['receivedQuantity'] = qty
        if qty < item.get('quantity', 0):
            all_complete = False

    new_status = 'recibida_completa' if all_complete else 'recibida_parcial'
    user = session['user'].get('displayName', 'Usuario')
    po['status'] = new_status
    po['receivedBy'] = user
    po['receivedAt'] = datetime.utcnow().isoformat()
    po['items'] = items
    PurchaseOrderService.save_purchase_order(owner_uid, po_id, po, sandbox=sandbox)

    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_PO,
        entity_id=po_id, entity_label=po.get('poNumber', ''),
        after=po,
    )
    return jsonify(success=True, status=new_status)


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/cancel', methods=['POST'])
def cancel_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    user = session['user'].get('displayName', 'Usuario')

    po = PurchaseOrderService.update_status(owner_uid, po_id, 'cancelada', sandbox=sandbox, user=user)
    if not po:
        return jsonify(success=False, error="Orden no encontrada"), 404

    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_PO,
        entity_id=po_id, entity_label=po.get('poNumber', ''),
        after=po,
    )
    return jsonify(success=True)


@web_purchase_orders_bp.route('/api/purchase-orders/next-number')
def api_next_po_number():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    number = PurchaseOrderService.get_next_po_number(owner_uid, sandbox=sandbox)
    return jsonify(success=True, poNumber=number)


@web_purchase_orders_bp.route('/api/purchase-orders/supplier-items')
def api_supplier_items():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = session['user']['ownerUID']
    items = DatabaseService.get_items(owner_uid, sandbox=session.get('is_sandbox_mode', True))
    active = [i for i in items if i.get('isActive', True)]
    return jsonify(success=True, items=active)


# ═════════════════════════════════════════════════════════════════════
# GOODS RECEIPT (Recepción de Mercancía)
# ═════════════════════════════════════════════════════════════════════

MODULE_RECEIPT = "Recepción de Mercancía"


@web_purchase_orders_bp.route('/purchase-orders/receipts')
def list_receipts():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='receipts')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    receipts = GoodsReceiptService.get_receipts(owner_uid, sandbox=sandbox)
    return render_template('purchase_orders/receipts_list.html',
                           receipts=receipts, active_page='receipts')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/receive-goods', methods=['GET', 'POST'])
def new_receipt(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='receipts')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    po = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not po:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))
    if po.get('status') not in ('aprobada', 'recibida_parcial'):
        flash('❌ Solo se pueden recibir órdenes aprobadas o con recepción parcial.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    if request.method == 'POST':
        receipt_id = str(uuid.uuid4())
        receipt_number = GoodsReceiptService.get_next_receipt_number(owner_uid, sandbox=sandbox)
        warehouse_id = request.form.get('warehouseId', '')
        warehouse_name = request.form.get('warehouseName', '')

        po_items = po.get('items', [])
        receipt_items = []
        for item in po_items:
            item_id = item.get('id', '')
            rqty_str = request.form.get(f'received_qty_{item_id}', '0')
            cat_item_id = request.form.get(f'catalog_item_{item_id}', '')
            rqty = float(rqty_str) if rqty_str else 0
            if rqty <= 0:
                continue
            receipt_items.append({
                "poItemId": item_id,
                "itemId": cat_item_id,
                "poItemName": item.get("name", ""),
                "itemName": request.form.get(f'catalog_name_{item_id}', item.get("name", "")),
                "orderedQuantity": float(item.get("quantity", 0)),
                "receivedQuantity": rqty,
                "unit": item.get("unit", "Unidad"),
                "unitPrice": float(item.get("unitPrice", 0)),
            })

        if not receipt_items:
            flash('❌ Debes indicar al menos una partida con cantidad > 0.', 'error')
            return redirect(url_for('web_purchase_orders.new_receipt', po_id=po_id))

        user = session['user'].get('displayName', 'Usuario')

        receipt_data = {
            "receiptNumber": receipt_number,
            "poId": po_id,
            "poNumber": po.get("poNumber", ""),
            "supplierId": po.get("supplierId", ""),
            "supplierName": po.get("supplierName", ""),
            "supplierRnc": po.get("supplierRnc", ""),
            "warehouseId": warehouse_id,
            "warehouseName": warehouse_name,
            "receiptDate": request.form.get('receiptDate', datetime.utcnow().strftime('%Y-%m-%d')),
            "items": receipt_items,
            "status": "completada",
            "notes": request.form.get('notes', ''),
            "createdBy": user,
            "createdAt": datetime.utcnow().isoformat(),
        }

        GoodsReceiptService.create_receipt(owner_uid, receipt_data, sandbox=sandbox)

        # Register inventory ENTRADA transactions for catalog-linked items
        GoodsReceiptService.register_receipt_inventory(owner_uid, receipt_data, sandbox=sandbox)

        # Update PO received quantities and status
        po_items_map = {item['poItemId']: item for item in receipt_items}
        total_ordered = 0
        total_received = 0
        for item in po.get('items', []):
            item_id = item.get('id', '')
            received_here = po_items_map.get(item_id, {}).get('receivedQuantity', 0)
            item['receivedQuantity'] = float(item.get('receivedQuantity', 0)) + received_here
            total_ordered += float(item.get('quantity', 0))
            total_received += item['receivedQuantity']

        all_complete = all(
            float(it.get('receivedQuantity', 0)) >= float(it.get('quantity', 0))
            for it in po.get('items', [])
        )
        po['status'] = 'recibida_completa' if all_complete else 'recibida_parcial'
        po['receivedBy'] = user
        po['receivedAt'] = datetime.utcnow().isoformat()
        po['updatedAt'] = datetime.utcnow().isoformat()
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
            module=MODULE_PO,
            entity_id=po_id,
            entity_label=po.get('poNumber', ''),
            after=po,
        )

        flash(f'✅ Recepción {receipt_number} registrada exitosamente.', 'success')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    receipt_number = GoodsReceiptService.get_next_receipt_number(owner_uid, sandbox=sandbox)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    catalog_items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    catalog_items = [i for i in catalog_items if i.get('isActive', True)]
    return render_template('purchase_orders/new_receipt.html',
                           order=po, receipt_number=receipt_number, today=today,
                           warehouses=warehouses, catalog_items=catalog_items,
                           active_page='receipts')


@web_purchase_orders_bp.route('/purchase-orders/receipts/<receipt_id>')
def receipt_detail(receipt_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    receipt = GoodsReceiptService.get_receipt(owner_uid, receipt_id, sandbox=sandbox)
    if not receipt:
        flash('❌ Recepción no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_receipts'))
    return render_template('purchase_orders/receipt_detail.html',
                           receipt=receipt, active_page='receipts')


# ═════════════════════════════════════════════════════════════════════
# SUPPLIER INVOICES (Facturas de Proveedor + CxP Compras)
# ═════════════════════════════════════════════════════════════════════

from app.services.supplier_invoice_service import SupplierInvoiceService, ALLOWED_MIME_TYPES, MAX_FILE_SIZE

MODULE_SINV = "Facturas de Proveedor"


@web_purchase_orders_bp.route('/purchase-orders/cxp/consolidado')
def consolidated_cxp():
    """Vista consolidada de Cuentas por Pagar (Compras + Gastos)."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    # 1. Purchase invoices
    purchase_invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox)
    # 2. Expense CxP
    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)

    unified = []
    total_pending = 0.0
    total_overdue = 0.0

    # Normalize purchase invoices
    for inv in purchase_invoices:
        due_date = inv.get('dueDate', '')
        rem_bal = float(inv.get('cxpRemainingBalance', inv.get('total', 0)))
        inv['cxpRemainingBalance'] = rem_bal
        status = inv.get('cxpStatus', 'Pendiente')
        if status in ('Pendiente', 'Abonado') and due_date and due_date < today_str:
            status = 'Vencido'
            inv['cxpStatus'] = 'Vencido'
        if status in ('Pendiente', 'Abonado', 'Vencido'):
            total_pending += rem_bal
            if status == 'Vencido' or (due_date and due_date < today_str):
                total_overdue += rem_bal
        unified.append({
            "id": inv["id"],
            "type": "compra",
            "documentNumber": inv.get("invoiceNumber", ""),
            "referenceNumber": inv.get("poNumber", ""),
            "supplierName": inv.get("supplierName", ""),
            "supplierRnc": inv.get("supplierRnc", ""),
            "ncf": inv.get("ncf", ""),
            "concept": f"Factura {inv.get('invoiceNumber', '')}" + (f" (OC {inv.get('poNumber', '')})" if inv.get('poNumber') else ""),
            "date": str(inv.get("date", ""))[:10],
            "dueDate": str(inv.get("dueDate", ""))[:10] if inv.get("dueDate") else "",
            "total": float(inv.get("total", 0)),
            "balance": rem_bal,
            "status": inv.get("cxpStatus", "Pendiente"),
            "detail_url": url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=inv["id"]),
        })

    # Normalize expense CxP
    for exp in all_expenses:
        if exp.get('approvalStatus') == 'Pendiente':
            continue
        if exp.get('paymentType') != 'Crédito':
            continue
        due_date = exp.get('dueDate', '')
        rem_bal = float(exp.get('cxpRemainingBalance', exp.get('amount', 0.0)))
        status = exp.get('cxpStatus', 'Pendiente')
        if status in ('Pendiente', 'Abonado') and due_date and due_date < today_str:
            status = 'Vencido'
        if status in ('Pendiente', 'Abonado', 'Vencido'):
            total_pending += rem_bal
            if status == 'Vencido' or (due_date and due_date < today_str):
                total_overdue += rem_bal
        unified.append({
            "id": exp["id"],
            "type": "gasto",
            "documentNumber": exp.get("ncf", ""),
            "referenceNumber": "",
            "supplierName": exp.get("providerName", ""),
            "supplierRnc": exp.get("rncEmisor", ""),
            "ncf": exp.get("ncf", ""),
            "concept": exp.get("concept", ""),
            "date": str(exp.get("date", ""))[:10],
            "dueDate": str(exp.get("dueDate", ""))[:10] if exp.get("dueDate") else "",
            "total": float(exp.get("amount", 0)),
            "balance": rem_bal,
            "status": status,
            "detail_url": url_for('web_invoices.expense_detail', expense_id=exp["id"]),
        })

    # Sort by date descending
    unified.sort(key=lambda x: x["date"], reverse=True)

    # Filters
    status_filter = request.args.get('status', '').strip()
    search_query = request.args.get('search', '').strip().lower()
    type_filter = request.args.get('type', '').strip()

    filtered = []
    for item in unified:
        if status_filter and item["status"] != status_filter:
            continue
        if type_filter and item["type"] != type_filter:
            continue
        if search_query:
            haystack = f"{item['supplierName']} {item['supplierRnc']} {item['ncf']} {item['concept']} {item['documentNumber']}".lower()
            if search_query not in haystack:
                continue
        filtered.append(item)

    return render_template('purchase_orders/consolidated_cxp.html',
                           active_page='consolidated_cxp',
                           items=filtered,
                           total_pending=total_pending,
                           total_overdue=total_overdue,
                           today_str=today_str,
                           status_filter=status_filter,
                           search_query=search_query,
                           type_filter=type_filter)


@web_purchase_orders_bp.route('/purchase-orders/invoices')
def list_purchase_cxp():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', feature_name="CxP Compras", required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox)

    total_pending = 0.0
    total_overdue = 0.0
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    for inv in invoices:
        status = inv.get('cxpStatus', 'Pendiente')
        due_date = inv.get('dueDate', '')
        rem_bal = float(inv.get('cxpRemainingBalance', inv.get('total', 0)))
        inv['cxpRemainingBalance'] = rem_bal
        if status in ('Pendiente', 'Abonado') and due_date and due_date < today_str:
            status = 'Vencido'
            inv['cxpStatus'] = 'Vencido'
        if status in ('Pendiente', 'Abonado', 'Vencido'):
            total_pending += rem_bal
            if status == 'Vencido' or (due_date and due_date < today_str):
                total_overdue += rem_bal

    status_filter = request.args.get('status', '').strip()
    search_query = request.args.get('search', '').strip().lower()

    filtered = []
    for inv in invoices:
        st = inv.get('cxpStatus', 'Pendiente')
        if status_filter and st != status_filter:
            continue
        if search_query:
            haystack = f"{inv.get('supplierName', '')} {inv.get('supplierRnc', '')} {inv.get('invoiceNumber', '')} {inv.get('ncf', '')}".lower()
            if search_query not in haystack:
                continue
        filtered.append(inv)

    if request.args.get('export') == 'csv':
        import csv, io
        from flask import send_file
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Factura#", "OC#", "Proveedor", "RNC", "NCF", "Fecha Emisión", "Vencimiento", "Total (RD$)", "Balance (RD$)", "Estado"])
        for inv in filtered:
            writer.writerow([
                inv.get("invoiceNumber", ""), inv.get("poNumber", ""),
                inv.get("supplierName", ""), inv.get("supplierRnc", ""),
                inv.get("ncf", ""), str(inv.get("date", ""))[:10],
                str(inv.get("dueDate", ""))[:10],
                f"{float(inv.get('total', 0)):.2f}",
                f"{float(inv.get('cxpRemainingBalance', inv.get('total', 0))):.2f}",
                inv.get("cxpStatus", "Pendiente"),
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"cxp_compras_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)

    return render_template('purchase_orders/purchase_cxp_dashboard.html',
                           active_page='purchase_cxp',
                           invoices=filtered,
                           total_pending=total_pending,
                           total_overdue=total_overdue,
                           today_str=today_str,
                           status_filter=status_filter,
                           search_query=search_query)


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/register-invoice', methods=['GET', 'POST'])
def register_supplier_invoice(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    po = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not po:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))

    po_status = po.get('status', '')
    if po_status not in ('recibida_parcial', 'recibida_completa'):
        flash('❌ Solo se pueden facturar órdenes con recepción parcial o completa.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    po_items = po.get('items', [])
    total_received = sum(float(item.get('receivedQuantity', 0)) for item in po_items)
    if total_received <= 0:
        flash('❌ La orden de compra no tiene cantidades recibidas. Debe recibir mercancía antes de facturar.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    if request.method == 'POST':
        invoice_number = request.form.get('invoiceNumber', '').strip()
        if not invoice_number:
            flash('❌ El número de factura del proveedor es obligatorio.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=datetime.utcnow().strftime('%Y-%m-%d'), active_page='purchase_orders')

        if not SupplierInvoiceService._check_ncf_unique(owner_uid, invoice_number, sandbox=sandbox):
            flash('❌ El número de factura del proveedor o NCF ya existe. Verifique los datos.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=datetime.utcnow().strftime('%Y-%m-%d'), active_page='purchase_orders')

        ncf = request.form.get('ncf', '').strip()
        inv_date = request.form.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
        due_date = request.form.get('dueDate', '')
        notes = request.form.get('notes', '').strip()

        today_str = datetime.utcnow().strftime('%Y-%m-%d')
        if inv_date > today_str:
            flash('❌ La fecha de emisión no puede ser futura.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=today_str, active_page='purchase_orders')
        if due_date and due_date < inv_date:
            flash('❌ La fecha de vencimiento no puede ser anterior a la fecha de emisión.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=today_str, active_page='purchase_orders')

        if ncf and not SupplierInvoiceService._check_ncf_unique(owner_uid, ncf, sandbox=sandbox):
            flash('❌ El NCF ya está registrado en otra factura.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=today_str, active_page='purchase_orders')

        attachment_urls = []
        file_upload_error = None
        attachment_file = request.files.get('attachment')
        if attachment_file and attachment_file.filename:
            file_data = attachment_file.read()
            if len(file_data) > MAX_FILE_SIZE:
                flash('❌ El archivo excede el límite de 10 MB.', 'error')
                return render_template('purchase_orders/register_invoice.html', po=po, today=today_str, active_page='purchase_orders')
            mime_type = attachment_file.content_type or "application/octet-stream"
            if mime_type not in ALLOWED_MIME_TYPES:
                flash('❌ Tipo de archivo no permitido. Solo PDF, JPG y PNG.', 'error')
                return render_template('purchase_orders/register_invoice.html', po=po, today=today_str, active_page='purchase_orders')
            try:
                safe_name = attachment_file.filename.replace(' ', '_')
                dest_path = f"users/{owner_uid}/supplier_invoices/{uuid.uuid4().hex}/{safe_name}"
                public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
                attachment_urls.append(public_url)
            except Exception as e:
                file_upload_error = str(e)
                print(f"⚠️ Error al subir PDF factura proveedor: {e}")

        items = []
        subtotal = 0.0
        total_itbis = 0.0
        total_discount = 0.0
        for item in po_items:
            qty = float(item.get('receivedQuantity', item.get('quantity', 0)))
            price = float(item.get('unitPrice', 0))
            itbis_rate = float(item.get('itbisRate', 0))
            discount_pct = float(item.get('discount', 0))
            line_sub = qty * price
            line_discount = line_sub * (discount_pct / 100.0)
            line_itbis = (line_sub - line_discount) * itbis_rate
            line_total = line_sub - line_discount + line_itbis
            subtotal += line_sub
            total_discount += line_discount
            total_itbis += line_itbis
            items.append({
                "poItemId": item.get("id", ""),
                "itemName": item.get("name", ""),
                "quantity": qty,
                "unitPrice": price,
                "itbisRate": itbis_rate,
                "discount": discount_pct,
                "subtotal": round(line_sub, 2),
                "itbisAmount": round(line_itbis, 2),
                "total": round(line_total, 2),
            })

        total = subtotal - total_discount + total_itbis
        sinv_number = SupplierInvoiceService.get_next_invoice_number(owner_uid, sandbox=sandbox)

        inv_data = {
            "invoiceNumber": sinv_number,
            "supplierInvoiceNumber": invoice_number,
            "ncf": ncf,
            "poId": po_id,
            "poNumber": po.get("poNumber", ""),
            "supplierId": po.get("supplierId", ""),
            "supplierName": po.get("supplierName", ""),
            "supplierRnc": po.get("supplierRnc", ""),
            "date": inv_date,
            "dueDate": due_date,
            "paymentTerms": po.get("paymentTerms", "contado"),
            "currency": po.get("currency", "DOP"),
            "exchangeRate": float(po.get("exchangeRate", 1.0)),
            "subtotal": round(subtotal, 2),
            "itbis": round(total_itbis, 2),
            "discount": round(total_discount, 2),
            "total": round(total, 2),
            "items": items,
            "attachmentUrls": attachment_urls,
            "notes": notes,
            "createdBy": session['user'].get('displayName', 'Usuario'),
        }

        SupplierInvoiceService.create(owner_uid, inv_data, sandbox=sandbox)

        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_SINV,
            entity_id=inv_data["id"],
            entity_label=f"Factura Proveedor {sinv_number} - {inv_data.get('supplierName', '')}",
            after=inv_data, sandbox=sandbox
        )

        msg = f'✅ Factura proveedor {sinv_number} registrada exitosamente.'
        if file_upload_error:
            msg += ' ⚠️ El PDF no pudo subirse. Puede adjuntarlo después desde el detalle.'
        flash(msg, 'success')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))

    today = datetime.utcnow().strftime('%Y-%m-%d')
    return render_template('purchase_orders/register_invoice.html',
                           po=po, today=today, active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>')
def supplier_invoice_detail(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = SupplierInvoiceService.get(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('❌ Factura proveedor no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))

    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    status = invoice.get('cxpStatus', 'Pendiente')
    due_date = invoice.get('dueDate', '')
    if status in ('Pendiente', 'Abonado') and due_date and due_date < today_str:
        invoice['cxpStatus'] = 'Vencido'

    payments = SupplierInvoiceService.get_payments(owner_uid, invoice_id, sandbox=sandbox)
    return render_template('purchase_orders/supplier_invoice_detail.html',
                           invoice=invoice, payments=payments,
                           active_page='purchase_cxp')


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/pay', methods=['POST'])
def pay_supplier_invoice(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        flash('❌ No tienes permiso para registrar pagos.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    try:
        amount = float(request.form.get('amount', 0))
    except (ValueError, TypeError):
        amount = 0
    if amount <= 0:
        flash('❌ El monto debe ser mayor a 0.', 'error')
        return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=invoice_id))

    payment_method = request.form.get('paymentMethod', '').strip()
    payment_reference = request.form.get('paymentReference', '').strip()
    registered_by = session['user'].get('displayName', 'Usuario')

    success, message = SupplierInvoiceService.save_payment(
        owner_uid, invoice_id, amount, registered_by=registered_by,
        sandbox=sandbox, payment_method=payment_method,
        payment_reference=payment_reference
    )

    if success:
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_SINV,
            entity_id=invoice_id,
            entity_label=f"Pago registrado: RD$ {amount:,.2f}",
            sandbox=sandbox
        )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=invoice_id))


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/edit', methods=['GET', 'POST'])
def edit_supplier_invoice(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = SupplierInvoiceService.get(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('❌ Factura proveedor no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))

    if request.method == 'POST':
        updates = {}
        notes = request.form.get('notes', '').strip()
        if notes != invoice.get('notes', ''):
            updates['notes'] = notes
        due_date = request.form.get('dueDate', '')
        if due_date and due_date != invoice.get('dueDate', ''):
            updates['dueDate'] = due_date
        date = request.form.get('date', '')
        if date and date != invoice.get('date', ''):
            updates['date'] = date

        if updates:
            SupplierInvoiceService.update(owner_uid, invoice_id, updates, sandbox=sandbox)
            AuditService.log_from_request(
                owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_SINV,
                entity_id=invoice_id,
                entity_label=f"Factura Proveedor {invoice.get('invoiceNumber', '')} editada",
                sandbox=sandbox
            )
            flash('✅ Factura actualizada.', 'success')
        else:
            flash('ℹ️ No hay cambios para guardar.', 'info')
        return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=invoice_id))

    return render_template('purchase_orders/edit_supplier_invoice.html',
                           invoice=invoice, active_page='purchase_cxp')


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/add-attachment', methods=['POST'])
def add_invoice_attachment(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = SupplierInvoiceService.get(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify(success=False, error="Factura no encontrada"), 404

    attachment_file = request.files.get('attachment')
    if not attachment_file or not attachment_file.filename:
        return jsonify(success=False, error="No se seleccionó archivo"), 400

    file_data = attachment_file.read()
    if len(file_data) > MAX_FILE_SIZE:
        return jsonify(success=False, error="El archivo excede el límite de 10 MB"), 400

    mime_type = attachment_file.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        return jsonify(success=False, error="Tipo de archivo no permitido"), 400

    url = SupplierInvoiceService.add_attachment(owner_uid, invoice_id, file_data,
                                                 attachment_file.filename, mime_type, sandbox=sandbox)
    if url:
        return jsonify(success=True, url=url)
    return jsonify(success=False, error="Error al subir archivo"), 500


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/void-payment/<payment_id>', methods=['POST'])
def void_payment(invoice_id, payment_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        flash('❌ No tienes permiso para revertir pagos.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    success, message = SupplierInvoiceService.void_payment(owner_uid, invoice_id, payment_id, sandbox=sandbox)
    if success:
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_SINV,
            entity_id=invoice_id,
            entity_label=f"Pago revertido en factura {invoice_id}",
            sandbox=sandbox
        )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=invoice_id))


@web_purchase_orders_bp.route('/api/purchase-orders/invoices/next-number')
def api_next_supplier_invoice_number():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    number = SupplierInvoiceService.get_next_invoice_number(owner_uid, sandbox=sandbox)
    return jsonify(success=True, invoiceNumber=number)
