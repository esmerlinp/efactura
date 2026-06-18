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
        return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    orders = PurchaseOrderService.get_purchase_orders(owner_uid, sandbox=sandbox)
    return render_template('purchase_orders/list.html',
                           orders=orders,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/new', methods=['GET', 'POST'])
def new_purchase_order():
    if 'user' not in session:
        return redirect(url_for('login'))
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
        return redirect(url_for('list_purchase_orders'))

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
        return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('list_purchase_orders'))
    receipts = GoodsReceiptService.get_receipts_by_po(owner_uid, po_id, sandbox=sandbox)
    order['receipts'] = receipts
    return render_template('purchase_orders/detail.html',
                           order=order,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/edit', methods=['GET', 'POST'])
def edit_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('list_purchase_orders'))

    if order.get('status') not in ('borrador', 'pendiente_aprobacion'):
        flash('❌ Solo se pueden editar órdenes en estado borrador o pendiente de aprobación.', 'error')
        return redirect(url_for('purchase_order_detail', po_id=po_id))

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
        return redirect(url_for('purchase_order_detail', po_id=po_id))

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
        return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('list_purchase_orders'))

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
    return redirect(url_for('list_purchase_orders'))


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/approve', methods=['POST'])
def approve_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('login'))
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
        return redirect(url_for('login'))
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
        return redirect(url_for('login'))
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
        return redirect(url_for('login'))
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
        return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='receipts')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    po = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not po:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('list_purchase_orders'))
    if po.get('status') not in ('aprobada', 'recibida_parcial'):
        flash('❌ Solo se pueden recibir órdenes aprobadas o con recepción parcial.', 'error')
        return redirect(url_for('purchase_order_detail', po_id=po_id))

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
            return redirect(url_for('new_receipt', po_id=po_id))

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
        return redirect(url_for('purchase_order_detail', po_id=po_id))

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
        return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    receipt = GoodsReceiptService.get_receipt(owner_uid, receipt_id, sandbox=sandbox)
    if not receipt:
        flash('❌ Recepción no encontrada.', 'error')
        return redirect(url_for('list_receipts'))
    return render_template('purchase_orders/receipt_detail.html',
                           receipt=receipt, active_page='receipts')
